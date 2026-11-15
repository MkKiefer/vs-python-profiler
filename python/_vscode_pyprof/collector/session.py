"""The profiling session of a collector process.

One collector process serves exactly one profiling session. It always runs
with the *target's* interpreter (Tachyon's remote unwinder is tied to the
target's CPython version and build).
"""

import os
import sys
import threading
from dataclasses import replace

from _vscode_pyprof import PACKAGE_DIR, PROTOCOL_VERSION
from _vscode_pyprof.agent_protocol.commands import (
    AgentRequest,
    CountObjects,
    SetAsyncioDebug,
    StartTracing,
    StopTracing,
    TakeSnapshot,
)
from _vscode_pyprof.agent_protocol.hello import ThreadName
from _vscode_pyprof.agent_protocol.metrics import AgentMetrics
from _vscode_pyprof.agent_protocol.names import EventKind
from _vscode_pyprof.agent_protocol.replies import (
    Acknowledgement,
    AsyncioDebugStatus,
    HeapSnapshot,
    ObjectCounts,
    TracingStatus,
)
from _vscode_pyprof.collector.agent.connection import AgentConnection, AgentError
from _vscode_pyprof.collector.agent.injector import AgentInjectionError, AgentInjector
from _vscode_pyprof.collector.agent.listener import AgentListener
from _vscode_pyprof.collector.agent.server import AgentServer
from _vscode_pyprof.collector.memory_snapshot_builder import MemorySnapshotBuilder
from _vscode_pyprof.collector.notifications import (
    AgentConnected,
    AgentDisconnected,
    ChildrenFound,
    ErrorOccurred,
    Notification,
    StateChanged,
)
from _vscode_pyprof.collector.options import CollectorOptions
from _vscode_pyprof.collector.profile_writer import ProfileWriter
from _vscode_pyprof.collector.protocol import RpcMethod, RpcNotification, SessionState, StopReason
from _vscode_pyprof.collector.rpc import RpcError, RpcServer
from _vscode_pyprof.collector.rpc_params import (
    AsyncioDebugParams,
    AttachParams,
    InitializeParams,
    MarkParams,
    NoParams,
    ObjectCountsParams,
    SaveParams,
    SnapshotParams,
    StopParams,
    TracemallocParams,
)
from _vscode_pyprof.collector.rpc_results import (
    AttachResult,
    Features,
    InitializeResult,
    SaveResult,
    SnapshotResult,
    StatusResult,
)
from _vscode_pyprof.collector.sampling.sampler import Sampler
from _vscode_pyprof.collector.sampling.sampler_factory import SamplerFactory
from _vscode_pyprof.collector.sampling.sampler_listener import SamplerListener
from _vscode_pyprof.collector.sampling.tachyon import Tachyon, TachyonError
from _vscode_pyprof.collector.store.session_clock import SessionClock
from _vscode_pyprof.collector.store.store import Store
from _vscode_pyprof.collector.store.track import Track
from _vscode_pyprof.wire import WireMessage


class CollectorSession(AgentListener, SamplerListener):
    """Serves the extension's RPC requests and ties sampler, agent and store together.

    Requests arrive on RPC threads, agent messages on the agent reader thread
    and target events on the sampler thread.
    """

    _FLUSH_INTERVAL = 0.25  # seconds between live deltas
    _EXIT_DELAY = 0.2  # lets the shutdown response reach the extension
    _SLOW_AGENT_TIMEOUT = 120.0  # snapshots and object counts walk the whole heap

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
        rpc = self._rpc
        rpc.register(RpcMethod.INITIALIZE, InitializeParams, self._initialize)
        rpc.register(RpcMethod.ATTACH, AttachParams, self._attach)
        rpc.register(RpcMethod.STOP, StopParams, self._stop)
        rpc.register(RpcMethod.STATUS, NoParams, self._status)
        rpc.register(RpcMethod.TRACEMALLOC, TracemallocParams, self._set_tracemalloc)
        rpc.register(RpcMethod.SNAPSHOT, SnapshotParams, self._take_snapshot)
        rpc.register(RpcMethod.OBJECT_COUNTS, ObjectCountsParams, self._count_objects)
        rpc.register(RpcMethod.ASYNCIO_DEBUG, AsyncioDebugParams, self._set_asyncio_debug)
        rpc.register(RpcMethod.MARK, MarkParams, self._mark)
        rpc.register(RpcMethod.SAVE, SaveParams, self._save)
        rpc.register(RpcMethod.SHUTDOWN, NoParams, self._shutdown)
        self._agent_server.start(self)

    # ---- RPC API: one handler per request of ``CollectorRequests`` in ``src/shared/protocol.ts``
    def _initialize(self, params: InitializeParams) -> InitializeResult:
        Tachyon.require()
        self._options = params.options
        self._store.describe_session(self._options, params.label)
        self._start_pump()
        return InitializeResult(
            protocol=PROTOCOL_VERSION,
            python=sys.version.split()[0],
            executable=sys.executable,
            platform=sys.platform,
            pid=os.getpid(),
            agent_address=self._agent_server.address,
            package_dir=PACKAGE_DIR,
            features=Features(
                gc_stats=Tachyon.supports_gc_stats(),
                remote_exec=self._injector.is_supported(),
                async_aware=Tachyon.supports_async_stacks(),
            ),
        )

    def _attach(self, params: AttachParams) -> AttachResult:
        sampler = self._start_sampler(params.pid)
        injected = False
        inject_error: str | None = None
        if params.inject and self._agent is None:
            try:
                self._injector.inject(params.pid, self._agent_server.address, self._options.agent_options())
                injected = True
            except AgentInjectionError as error:  # sampling still works without the agent
                inject_error = str(error)
                self._store.add_event(EventKind.AGENT, f"Agent injection failed: {error}")
        return AttachResult(sampler.pid, injected, inject_error)

    def _stop(self, params: StopParams) -> Acknowledgement:
        self._stop_profiling(params.reason)
        return Acknowledgement()

    def _status(self, _params: NoParams) -> StatusResult:
        return StatusResult(
            state=self._state,
            pid=self._sampler.pid if self._sampler else None,
            agent=self._agent is not None,
            stats=self._store.stats(),
        )

    def _set_tracemalloc(self, params: TracemallocParams) -> TracingStatus:
        agent = self._require_agent()
        self._options = self._options.with_tracemalloc(params.enabled)
        if not params.enabled:
            return self._ask(agent, StopTracing(), TracingStatus)
        frames = self._options.tracemalloc_frames if params.frames is None else params.frames
        return self._ask(agent, StartTracing(frames), TracingStatus)

    def _take_snapshot(self, params: SnapshotParams) -> SnapshotResult:
        agent = self._require_agent()
        heap = self._ask(agent, TakeSnapshot(params.limit), HeapSnapshot, self._SLOW_AGENT_TIMEOUT)
        snapshot = self._snapshot_builder.build(heap, params.label)
        self._store.add_snapshot(snapshot)
        self._store.add_marker(snapshot.label, snapshot.t)
        return SnapshotResult(snapshot.snapshot_id, snapshot.total_size, len(snapshot.sites))

    def _count_objects(self, params: ObjectCountsParams) -> ObjectCounts:
        agent = self._require_agent()
        counted = self._ask(agent, CountObjects(params.limit), ObjectCounts, self._SLOW_AGENT_TIMEOUT)
        counts = replace(counted, t=self._clock.from_perf_counter(counted.t))  # agent time -> session time
        self._store.add_object_counts(counts)
        return counts

    def _set_asyncio_debug(self, params: AsyncioDebugParams) -> AsyncioDebugStatus:
        agent = self._require_agent()
        self._options = self._options.with_asyncio_debug(params.enabled)
        slow_ms = self._options.slow_callback_ms if params.slow_ms is None else params.slow_ms
        return self._ask(agent, SetAsyncioDebug(params.enabled, slow_ms), AsyncioDebugStatus)

    def _mark(self, params: MarkParams) -> Acknowledgement:
        self._store.add_marker(params.name)
        return Acknowledgement()

    def _save(self, params: SaveParams) -> SaveResult:
        self._flush()
        return SaveResult(params.path, self._profile_writer.write(params.path, self._store.full()))

    def _shutdown(self, _params: NoParams) -> Acknowledgement:
        try:
            self._stop_profiling(StopReason.SHUTDOWN)
        finally:
            self._agent_server.close()
            self._pump_stop.set()
            timer = threading.Timer(self._EXIT_DELAY, os._exit, args=(0,))
            timer.daemon = True
            timer.start()
        return Acknowledgement()

    # ---- agent events
    def on_agent_hello(self, connection: AgentConnection) -> None:
        hello = connection.hello
        self._agent = connection
        self._injector.cleanup()
        self._store.set_agent_process(hello.executable, hello.argv, hello.cwd)
        self._name_threads(hello.threads)
        self._store.add_event(EventKind.AGENT, f"Agent connected (pid {hello.pid})")
        self._notify(AgentConnected(hello.pid, hello.argv, hello.cwd))
        # launch mode: the launcher's agent tells us which pid to sample
        if self._sampler is None:
            try:
                self._start_sampler(hello.pid)
            except RpcError as error:
                self._notify(ErrorOccurred(str(error)))

    def on_agent_metrics(self, connection: AgentConnection, metrics: AgentMetrics) -> None:
        self._record_metrics(metrics)

    def on_agent_close(self, connection: AgentConnection) -> None:
        if self._agent is connection:
            self._agent = None
            self._store.add_event(EventKind.AGENT, "Agent disconnected")
            self._notify(AgentDisconnected())

    # ---- sampler events
    def on_target_exit(self, reason: StopReason) -> None:
        self._state = SessionState.EXITED
        self._agent = None
        self._flush()
        self._notify(StateChanged(self._state, reason=reason))

    def on_children(self, pids: list[int]) -> None:
        self._notify(ChildrenFound(pids))

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
            self._store.set_target(sampler.pid)
            sampler.start()
            self._state = SessionState.RUNNING
        self._notify(StateChanged(SessionState.RUNNING, pid=sampler.pid))
        return sampler

    def _stop_profiling(self, reason: str) -> None:
        """``reason`` is a ``StopReason`` value or whatever the extension sent."""
        with self._lock:
            if self._sampler is not None:
                self._sampler.stop()
            agent, self._agent = self._agent, None
            self._state = SessionState.STOPPED
        if agent is not None:
            agent.close()
        self._flush()
        self._notify(StateChanged(SessionState.STOPPED, reason=reason))

    def _record_metrics(self, metrics: AgentMetrics) -> None:
        store = self._store
        t = self._clock.now()
        self._name_threads(metrics.threads)
        if metrics.traced is not None:
            store.add_track(Track.TRACED, t, metrics.traced.current)
            store.add_track(Track.TRACED_PEAK, t, metrics.traced.peak)
        if metrics.loops:
            store.add_track(Track.LOOP_LAG, t, round(max(loop.lag_ms for loop in metrics.loops), 3))
            task_counts = [loop.tasks for loop in metrics.loops if loop.tasks is not None]
            if task_counts:
                store.add_track(Track.LOOP_TASKS, t, sum(task_counts))
        for event in metrics.events:
            happened = t if event.perf_counter is None else self._clock.from_perf_counter(event.perf_counter)
            store.add_event(event.kind, event.message, happened, event.details)

    def _require_agent(self) -> AgentConnection:
        agent = self._agent
        if agent is None or not agent.alive:
            raise RpcError(
                "The in-process agent is not connected. Memory and asyncio-debug features need it; "
                "CPU sampling works without it."
            )
        return agent

    @staticmethod
    def _ask[R: WireMessage](
        agent: AgentConnection,
        request: AgentRequest,
        reply_type: type[R],
        timeout: float = AgentConnection.DEFAULT_TIMEOUT,
    ) -> R:
        """Run a command in the target and read its answer as ``reply_type``."""
        try:
            return agent.request(request, reply_type, timeout)
        except AgentError as error:
            raise RpcError(str(error)) from error

    def _name_threads(self, threads: list[ThreadName]) -> None:
        for thread in threads:
            for thread_id in thread.ids():
                self._store.set_thread_name(thread_id, thread.name)

    def _notify(self, notification: Notification) -> None:
        self._rpc.notify(notification.method, notification.to_wire())

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
