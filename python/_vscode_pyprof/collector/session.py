"""The profiling session of a collector process.

One collector process serves exactly one profiling session. It always runs
with the *target's* interpreter (Tachyon's remote unwinder is tied to the
target's CPython version and build).
"""

import os
import sys
import threading

from _vscode_pyprof import PACKAGE_DIR, PROTOCOL_VERSION
from _vscode_pyprof.agent_protocol import AgentCommand, AgentMessageType, EventKind
from _vscode_pyprof.collector.agent.connection import AgentConnection, AgentError
from _vscode_pyprof.collector.agent.injector import AgentInjectionError, AgentInjector
from _vscode_pyprof.collector.agent.listener import AgentListener
from _vscode_pyprof.collector.agent.metrics import AgentMetrics
from _vscode_pyprof.collector.agent.server import AgentServer
from _vscode_pyprof.collector.agent.thread_name import ThreadName
from _vscode_pyprof.collector.memory_snapshot_builder import MemorySnapshotBuilder
from _vscode_pyprof.collector.options import CollectorOptions
from _vscode_pyprof.collector.profile_writer import ProfileWriter
from _vscode_pyprof.collector.protocol import RpcMethod, RpcNotification, SessionState, StopReason
from _vscode_pyprof.collector.rpc import RpcError, RpcHandler, RpcServer
from _vscode_pyprof.collector.sampling.sampler import Sampler
from _vscode_pyprof.collector.sampling.sampler_factory import SamplerFactory
from _vscode_pyprof.collector.sampling.sampler_listener import SamplerListener
from _vscode_pyprof.collector.sampling.tachyon import Tachyon, TachyonError
from _vscode_pyprof.collector.store.session_clock import SessionClock
from _vscode_pyprof.collector.store.store import Store
from _vscode_pyprof.collector.store.track import Track
from _vscode_pyprof.wire import JsonObject, WireReader


class CollectorSession(AgentListener, SamplerListener):
    """Serves the extension's RPC requests and ties sampler, agent and store together.

    Requests arrive on RPC threads, agent messages on the agent reader thread
    and target events on the sampler thread.
    """

    _FLUSH_INTERVAL = 0.25  # seconds between live deltas
    _EXIT_DELAY = 0.2  # lets the shutdown response reach the extension
    _SLOW_AGENT_TIMEOUT = 120.0  # snapshots and object counts walk the whole heap
    _DEFAULT_SNAPSHOT_LIMIT = 3000
    _DEFAULT_OBJECT_COUNT_LIMIT = 60

    def __init__(
        self,
        rpc: RpcServer,
        store: Store,
        clock: SessionClock,
        agent_server: AgentServer,
        injector: AgentInjector,
        sampler_factory: SamplerFactory,
        snapshot_builder: MemorySnapshotBuilder,
        profile_writer: ProfileWriter,
    ) -> None:
        self._rpc = rpc
        self._store = store
        self._clock = clock
        self._agent_server = agent_server
        self._injector = injector
        self._sampler_factory = sampler_factory
        self._snapshot_builder = snapshot_builder
        self._profile_writer = profile_writer
        self._options = CollectorOptions()
        self._sampler: Sampler | None = None
        self._agent: AgentConnection | None = None
        self._state = SessionState.IDLE
        self._lock = threading.RLock()
        self._pump_stop = threading.Event()
        self._pump_started = False

    def start(self) -> None:
        """Register the RPC API and start accepting agents."""
        handlers: dict[RpcMethod, RpcHandler] = {
            RpcMethod.INITIALIZE: self._initialize,
            RpcMethod.ATTACH: self._attach,
            RpcMethod.STOP: self._stop,
            RpcMethod.STATUS: self._status,
            RpcMethod.TRACEMALLOC: self._set_tracemalloc,
            RpcMethod.SNAPSHOT: self._take_snapshot,
            RpcMethod.OBJECT_COUNTS: self._count_objects,
            RpcMethod.ASYNCIO_DEBUG: self._set_asyncio_debug,
            RpcMethod.MARK: self._mark,
            RpcMethod.SAVE: self._save,
            RpcMethod.SHUTDOWN: self._shutdown,
        }
        for method, handler in handlers.items():
            self._rpc.register(method, handler)
        self._agent_server.start(self)

    # ---- RPC API: one handler per request of ``CollectorRequests`` in ``src/shared/protocol.ts``
    def _initialize(self, params: WireReader) -> JsonObject:
        Tachyon.require()
        self._options = CollectorOptions.from_wire(params.get_object("options"))
        self._store.configure(strip_launcher=self._options.strip_launcher)
        self._store.set_meta(options=self._options.to_wire(), label=params.get_optional_str("label"))
        self._start_pump()
        return {
            "protocol": PROTOCOL_VERSION,
            "python": sys.version.split()[0],
            "executable": sys.executable,
            "platform": sys.platform,
            "pid": os.getpid(),
            "agentAddress": self._agent_server.address,
            "packageDir": PACKAGE_DIR,
            "features": {
                "gcStats": Tachyon.supports_gc_stats(),
                "remoteExec": self._injector.is_supported(),
                "asyncAware": Tachyon.supports_async_stacks(),
            },
        }

    def _attach(self, params: WireReader) -> JsonObject:
        pid = params.get_int("pid")
        sampler = self._start_sampler(pid)
        injected = False
        inject_error: str | None = None
        if params.get_bool("inject", True) and self._agent is None:
            try:
                self._injector.inject(pid, self._agent_server.address, self._options.agent_options())
                injected = True
            except AgentInjectionError as error:  # sampling still works without the agent
                inject_error = str(error)
                self._store.add_event(EventKind.AGENT, f"Agent injection failed: {error}")
        return {"pid": sampler.pid, "injected": injected, "injectError": inject_error}

    def _stop(self, params: WireReader) -> JsonObject:
        self._stop_profiling(params.get_str("reason", StopReason.USER))
        return {"ok": True}

    def _status(self, _params: WireReader) -> JsonObject:
        return {
            "state": self._state,
            "pid": self._sampler.pid if self._sampler else None,
            "agent": self._agent is not None,
            "stats": self._store.stats().to_wire(),
        }

    def _set_tracemalloc(self, params: WireReader) -> JsonObject:
        agent = self._require_agent()
        enabled = params.get_bool("enabled", True)
        self._options = self._options.with_tracemalloc(enabled)
        if not enabled:
            return self._ask(agent, AgentCommand.TRACEMALLOC_STOP).to_dict()
        frames = params.get_int("frames", self._options.tracemalloc_frames)
        return self._ask(agent, AgentCommand.TRACEMALLOC_START, {"frames": frames}).to_dict()

    def _take_snapshot(self, params: WireReader) -> JsonObject:
        agent = self._require_agent()
        limit = params.get_int("limit", self._DEFAULT_SNAPSHOT_LIMIT)
        reply = self._ask(agent, AgentCommand.SNAPSHOT, {"limit": limit}, self._SLOW_AGENT_TIMEOUT)
        snapshot = self._snapshot_builder.build(reply, params.get_optional_str("label"))
        self._store.add_snapshot(snapshot)
        self._store.add_marker(snapshot.label, snapshot.t)
        return {"id": snapshot.snapshot_id, "totalSize": snapshot.total_size, "entries": len(snapshot.sites)}

    def _count_objects(self, params: WireReader) -> JsonObject:
        agent = self._require_agent()
        limit = params.get_int("limit", self._DEFAULT_OBJECT_COUNT_LIMIT)
        reply = self._ask(agent, AgentCommand.OBJECT_COUNTS, {"limit": limit}, self._SLOW_AGENT_TIMEOUT)
        t = self._clock.from_perf_counter(reply.get_float("t"))
        counts = reply.get_list("counts")
        self._store.add_object_counts(t, counts)
        return {"t": t, "counts": counts}

    def _set_asyncio_debug(self, params: WireReader) -> JsonObject:
        agent = self._require_agent()
        enabled = params.get_bool("enabled", True)
        self._options = self._options.with_asyncio_debug(enabled)
        slow_ms = params.get_float("slowMs", self._options.slow_callback_ms)
        return self._ask(agent, AgentCommand.ASYNCIO_DEBUG, {"enabled": enabled, "slowMs": slow_ms}).to_dict()

    def _mark(self, params: WireReader) -> JsonObject:
        self._store.add_marker(params.get_str("name", "marker"))
        return {"ok": True}

    def _save(self, params: WireReader) -> JsonObject:
        path = params.get_str("path")
        self._flush()
        return {"path": path, "bytes": self._profile_writer.write(path, self._store.full())}

    def _shutdown(self, _params: WireReader) -> JsonObject:
        try:
            self._stop_profiling(StopReason.SHUTDOWN)
        finally:
            self._agent_server.close()
            self._pump_stop.set()
            timer = threading.Timer(self._EXIT_DELAY, os._exit, args=(0,))
            timer.daemon = True
            timer.start()
        return {"ok": True}

    # ---- agent events
    def on_agent_hello(self, connection: AgentConnection) -> None:
        hello = connection.hello
        self._agent = connection
        self._injector.cleanup()
        self._store.set_meta(agent=True, executable=hello.executable, argv=hello.argv, cwd=hello.cwd)
        self._name_threads(hello.threads)
        self._store.add_event(EventKind.AGENT, f"Agent connected (pid {hello.pid})")
        self._rpc.notify(
            RpcNotification.AGENT, {"connected": True, "pid": hello.pid, "argv": hello.argv, "cwd": hello.cwd}
        )
        # launch mode: the launcher's agent tells us which pid to sample
        if self._sampler is None:
            try:
                self._start_sampler(hello.pid)
            except RpcError as error:
                self._rpc.notify(RpcNotification.ERROR, {"message": str(error)})

    def on_agent_message(self, connection: AgentConnection, message: WireReader) -> None:
        if message.get_optional_str("type") != AgentMessageType.METRICS:
            return
        metrics = AgentMetrics.from_wire(message)
        store = self._store
        t = self._clock.now()
        self._name_threads(metrics.threads)
        if metrics.traced is not None and metrics.traced_peak is not None:
            store.add_track(Track.TRACED, t, metrics.traced)
            store.add_track(Track.TRACED_PEAK, t, metrics.traced_peak)
        if metrics.loops:
            store.add_track(Track.LOOP_LAG, t, round(max(loop.lag_ms for loop in metrics.loops), 3))
            task_counts = [loop.tasks for loop in metrics.loops if loop.tasks is not None]
            if task_counts:
                store.add_track(Track.LOOP_TASKS, t, sum(task_counts))
        for event in metrics.events:
            happened = t if event.perf_counter is None else self._clock.from_perf_counter(event.perf_counter)
            store.add_event(event.kind, event.message, happened, event.extra)

    def on_agent_close(self, connection: AgentConnection) -> None:
        if self._agent is connection:
            self._agent = None
            self._store.add_event(EventKind.AGENT, "Agent disconnected")
            self._rpc.notify(RpcNotification.AGENT, {"connected": False})

    # ---- sampler events
    def on_target_exit(self, reason: StopReason) -> None:
        self._state = SessionState.EXITED
        self._agent = None
        self._flush()
        self._rpc.notify(RpcNotification.STATE, {"state": self._state, "reason": reason})

    def on_children(self, pids: list[int]) -> None:
        self._rpc.notify(RpcNotification.CHILDREN, {"pids": pids})

    # ---- internals
    def _start_sampler(self, pid: int) -> Sampler:
        """Start sampling ``pid`` unless the session already samples a process."""
        with self._lock:
            if self._sampler is not None:
                return self._sampler
            try:
                sampler = self._sampler_factory.create(pid, self._options, self)
            except TachyonError as error:
                raise RpcError(str(error)) from None
            self._sampler = sampler
            self._store.set_meta(pid=sampler.pid)
            sampler.start()
            self._state = SessionState.RUNNING
        self._rpc.notify(RpcNotification.STATE, {"state": self._state, "pid": sampler.pid})
        return sampler

    def _stop_profiling(self, reason: str) -> None:
        with self._lock:
            if self._sampler is not None:
                self._sampler.stop()
            agent, self._agent = self._agent, None
            self._state = SessionState.STOPPED
        if agent is not None:
            agent.close()
        self._flush()
        self._rpc.notify(RpcNotification.STATE, {"state": SessionState.STOPPED, "reason": reason})

    def _require_agent(self) -> AgentConnection:
        agent = self._agent
        if agent is None or not agent.alive:
            raise RpcError(
                "The in-process agent is not connected. Memory and asyncio-debug features need it; "
                "CPU sampling works without it."
            )
        return agent

    @staticmethod
    def _ask(
        agent: AgentConnection,
        command: AgentCommand,
        params: JsonObject | None = None,
        timeout: float = AgentConnection.DEFAULT_TIMEOUT,
    ) -> WireReader:
        try:
            return agent.request(command, params, timeout)
        except AgentError as error:
            raise RpcError(str(error)) from error

    def _name_threads(self, threads: list[ThreadName]) -> None:
        for thread in threads:
            for thread_id in thread.ids():
                self._store.set_thread_name(thread_id, thread.name)

    def _start_pump(self) -> None:
        with self._lock:
            if not self._pump_started:
                self._pump_started = True
                threading.Thread(target=self._pump, name="pyprof-pump", daemon=True).start()

    def _pump(self) -> None:
        """Stream what the store recorded to the extension until shutdown."""
        while not self._pump_stop.wait(self._FLUSH_INTERVAL):
            if self._rpc.closed:
                break
            self._flush()

    def _flush(self) -> None:
        self._rpc.notify(RpcNotification.DELTA, self._store.delta())
