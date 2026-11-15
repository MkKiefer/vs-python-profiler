"""The profiling session of a collector process.

One collector process serves exactly one profiling session. It always runs
with the *target's* interpreter (Tachyon's remote unwinder is tied to the
target's CPython version and build).
"""

import os
import sys
import threading
from dataclasses import replace

from _vspyprof import PACKAGE_DIR, PROTOCOL_VERSION
from _vspyprof.agent_protocol import commands
from _vspyprof.agent_protocol.hello import ThreadName
from _vspyprof.agent_protocol.metrics import AgentMetrics
from _vspyprof.agent_protocol.names import EventKind
from _vspyprof.agent_protocol.replies import AsyncioDebugStatus, HeapSnapshot, ObjectCounts, TracingStatus
from _vspyprof.collector import requests
from _vspyprof.collector.agent.connection import AgentConnection, AgentError
from _vspyprof.collector.agent.injector import AgentInjectionError, AgentInjector
from _vspyprof.collector.agent.listener import AgentListener
from _vspyprof.collector.agent.server import AgentServer
from _vspyprof.collector.memory_snapshot_builder import MemorySnapshotBuilder
from _vspyprof.collector.notifications import (
    AgentConnected,
    AgentDisconnected,
    ChildrenFound,
    Delta,
    ErrorOccurred,
    StateChanged,
)
from _vspyprof.collector.options import CollectorOptions
from _vspyprof.collector.profile_writer import ProfileWriter
from _vspyprof.collector.protocol import SessionState, StopReason
from _vspyprof.collector.rpc import RpcError, RpcServer
from _vspyprof.collector.rpc_results import (
    AttachResult,
    Features,
    InitializeResult,
    SaveResult,
    SnapshotResult,
    StatusResult,
)
from _vspyprof.collector.sampling.sampler import Sampler
from _vspyprof.collector.sampling.sampler_factory import SamplerFactory
from _vspyprof.collector.sampling.sampler_listener import SamplerListener
from _vspyprof.collector.sampling.tachyon import Tachyon, TachyonError
from _vspyprof.collector.store.session_clock import SessionClock
from _vspyprof.collector.store.store import Store
from _vspyprof.collector.store.track import Track
from _vspyprof.wire import WireEncoder


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
        encoder: WireEncoder,
    ) -> None:
        self._rpc = rpc
        self._store = store
        self._clock = clock
        self._agent_server = agent_server
        self._injector = injector
        self._sampler_factory = sampler_factory
        self._snapshot_builder = snapshot_builder
        self._profile_writer = profile_writer
        self._encoder = encoder
        self._options = CollectorOptions()
        self._sampler: Sampler | None = None
        self._agent: AgentConnection | None = None
        self._state = SessionState.IDLE
        self._lock = threading.RLock()
        self._pump_stop = threading.Event()
        self._pump_started = False

    def start(self) -> None:
        """Start accepting agents."""
        self._agent_server.start(self)

    def run(self, request: object) -> object:
        """Run one request of the extension and return its result (see ``collector.requests``)."""
        match request:
            case requests.Initialize():
                return self._initialize(request)
            case requests.Attach():
                return self._attach(request)
            case requests.Stop(reason=reason):
                self._stop_profiling(reason)
                return None
            case requests.GetStatus():
                return self._status()
            case requests.SetTracemalloc():
                return self._set_tracemalloc(request)
            case requests.TakeSnapshot():
                return self._take_snapshot(request)
            case requests.CountObjects(limit=limit):
                return self._count_objects(limit)
            case requests.SetAsyncioDebug():
                return self._set_asyncio_debug(request)
            case requests.Mark(name=name):
                self._store.add_marker(name)
                return None
            case requests.Save(path=path):
                return self._save(path)
            case requests.Shutdown():
                self._shutdown()
                return None
        raise RpcError(f"unknown request {type(request).__name__}")

    # ---- requests
    def _initialize(self, request: requests.Initialize) -> InitializeResult:
        Tachyon.require()
        self._options = request.options
        self._store.describe_session(self._options, request.label)
        self._start_pump()
        return InitializeResult(
            protocol=PROTOCOL_VERSION,
            python=sys.version.split()[0],
            executable=sys.executable,
            platform=sys.platform,
            pid=os.getpid(),
            agent_address=self._agent_server.address,
            agent_options=self._encoder.to_text(self._options.agent_options()),
            package_dir=PACKAGE_DIR,
            features=Features(
                gc_stats=Tachyon.supports_gc_stats(),
                remote_exec=self._injector.is_supported(),
                async_aware=Tachyon.supports_async_stacks(),
            ),
        )

    def _attach(self, request: requests.Attach) -> AttachResult:
        sampler = self._start_sampler(request.pid)
        injected = False
        inject_error: str | None = None
        if request.inject and self._agent is None:
            options = self._encoder.to_text(self._options.agent_options())
            try:
                self._injector.inject(request.pid, self._agent_server.address, options)
                injected = True
            except AgentInjectionError as error:  # sampling still works without the agent
                inject_error = str(error)
                self._store.add_event(EventKind.AGENT, f"Agent injection failed: {error}")
        return AttachResult(sampler.pid, injected, inject_error)

    def _status(self) -> StatusResult:
        return StatusResult(
            state=self._state,
            pid=self._sampler.pid if self._sampler else None,
            agent=self._agent is not None,
            stats=self._store.stats(),
        )

    def _set_tracemalloc(self, request: requests.SetTracemalloc) -> TracingStatus:
        agent = self._require_agent()
        self._options = self._options.with_tracemalloc(request.enabled)
        if not request.enabled:
            return self._ask(agent, commands.StopTracing(), TracingStatus)
        frames = self._options.tracemalloc_frames if request.frames is None else request.frames
        return self._ask(agent, commands.StartTracing(frames), TracingStatus)

    def _take_snapshot(self, request: requests.TakeSnapshot) -> SnapshotResult:
        agent = self._require_agent()
        heap = self._ask(agent, commands.TakeSnapshot(request.limit), HeapSnapshot, self._SLOW_AGENT_TIMEOUT)
        snapshot = self._snapshot_builder.build(heap, request.label)
        self._store.add_snapshot(snapshot)
        self._store.add_marker(snapshot.label, snapshot.t)
        return SnapshotResult(snapshot.snapshot_id, snapshot.total_size, len(snapshot.sites))

    def _count_objects(self, limit: int) -> ObjectCounts:
        agent = self._require_agent()
        counted = self._ask(agent, commands.CountObjects(limit), ObjectCounts, self._SLOW_AGENT_TIMEOUT)
        counts = replace(counted, t=self._clock.from_perf_counter(counted.t))  # agent time -> session time
        self._store.add_object_counts(counts)
        return counts

    def _set_asyncio_debug(self, request: requests.SetAsyncioDebug) -> AsyncioDebugStatus:
        agent = self._require_agent()
        self._options = self._options.with_asyncio_debug(request.enabled)
        slow_ms = self._options.slow_callback_ms if request.slow_ms is None else request.slow_ms
        return self._ask(agent, commands.SetAsyncioDebug(request.enabled, slow_ms), AsyncioDebugStatus)

    def _save(self, path: str) -> SaveResult:
        self._flush()
        return SaveResult(path, self._profile_writer.write(path, self._store.saved_profile()))

    def _shutdown(self) -> None:
        try:
            self._stop_profiling(StopReason.SHUTDOWN)
        finally:
            self._agent_server.close()
            self._pump_stop.set()
            timer = threading.Timer(self._EXIT_DELAY, os._exit, args=(0,))
            timer.daemon = True
            timer.start()

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

    def on_sampler_error(self, message: str) -> None:
        with self._lock:
            self._state = SessionState.STOPPED
        self._store.add_event(EventKind.SAMPLER, message)
        self._flush()
        self._notify(ErrorOccurred(message))
        self._notify(StateChanged(SessionState.STOPPED, reason=StopReason.ERROR))

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
    def _ask[R](
        agent: AgentConnection,
        command: object,
        reply_type: type[R],
        timeout: float = AgentConnection.DEFAULT_TIMEOUT,
    ) -> R:
        """Run a command in the target and read its answer as ``reply_type``."""
        try:
            return agent.request(command, reply_type, timeout)
        except AgentError as error:
            raise RpcError(str(error)) from error

    def _name_threads(self, threads: list[ThreadName]) -> None:
        for thread in threads:
            for thread_id in thread.ids():
                self._store.set_thread_name(thread_id, thread.name)

    def _notify(self, notification: object) -> None:
        self._rpc.notify(notification)

    def _start_pump(self) -> None:
        with self._lock:
            if not self._pump_started:
                self._pump_started = True
                threading.Thread(target=self._pump, name="vspyprof-pump", daemon=True).start()

    def _pump(self) -> None:
        """Stream what the store recorded to the extension until shutdown."""
        while not self._pump_stop.wait(self._FLUSH_INTERVAL):
            if self._rpc.closed:
                break
            self._flush()

    def _flush(self) -> None:
        self._rpc.notify(Delta(self._store.delta()))
