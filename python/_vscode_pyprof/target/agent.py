"""In-process agent: runs as a daemon thread *inside* the profiled program.

Started either by the launcher (start mode) or via ``sys.remote_exec`` (attach
mode). It connects back to the collector over localhost TCP (works on every
OS) and provides what cannot be read from outside:

* tracemalloc control, snapshots grouped by traceback (``MemoryProbe``)
* event-loop lag probes and asyncio debug events - slow callbacks, never
  awaited coroutines, destroyed pending tasks (``LoopMonitor``)
* thread names, object type counts

Everything in ``_vscode_pyprof.target`` is stdlib-only and must be cheap when
idle. Because this code runs in the *user's* process, modules the program may
not use itself (``asyncio``, ``tracemalloc``, ``logging``, ``warnings``,
``gc``) are ``lazy`` imports (PEP 810): they load on first use of the matching
feature, so they neither slow the program down nor change what the profile
shows, and the ``"asyncio" in sys.modules`` checks still tell whether the
*program* uses asyncio. (In attach mode, a lazy-imports filter the program
installed may load them eagerly; that costs a few imports, never wrong data.)
"""

import os
import select
import socket
import sys
import threading
import time
from collections import deque
from collections.abc import Callable

from _vscode_pyprof.agent_protocol.address import AgentAddress
from _vscode_pyprof.agent_protocol.commands import (
    AgentRequest,
    CommandCall,
    CommandResult,
    CountObjects,
    Ping,
    SetAsyncioDebug,
    Shutdown,
    StartTracing,
    StopTracing,
    TakeSnapshot,
)
from _vscode_pyprof.agent_protocol.hello import AgentHello, ThreadName
from _vscode_pyprof.agent_protocol.metrics import AgentEvent, AgentMetrics
from _vscode_pyprof.agent_protocol.options import AgentOptions
from _vscode_pyprof.agent_protocol.replies import Acknowledgement, AsyncioDebugStatus, Pong
from _vscode_pyprof.target.asyncio_debug import AsyncioDebugCapture
from _vscode_pyprof.target.loop_monitor import LoopMonitor
from _vscode_pyprof.target.memory_probe import MemoryProbe
from _vscode_pyprof.wire import JsonLines, JsonObject, WireWritable


class Agent(threading.Thread):
    """Serves the collector's commands and reports metrics until the collector goes away."""

    _METRICS_INTERVAL = 0.5
    _PROBE_INTERVAL = 0.1
    _CONNECT_TIMEOUT = 10.0
    _RECEIVE_SIZE = 65536

    def __init__(
        self,
        address: AgentAddress,
        options: AgentOptions,
        loops: LoopMonitor,
        memory: MemoryProbe,
        events: deque[AgentEvent],
    ) -> None:
        """``events`` is filled from any thread; the agent drains it into its metrics."""
        super().__init__(name="pyprof-agent", daemon=True)
        self._address = address
        self._options = options
        self._loops = loops
        self._memory = memory
        self._events = events
        self._socket: socket.socket | None = None
        self._write_lock = threading.Lock()
        self._halt = threading.Event()
        self._commands: dict[str, Callable[[JsonObject], WireWritable]] = {}
        self._register(StartTracing, self._start_tracing)
        self._register(StopTracing, self._stop_tracing)
        self._register(TakeSnapshot, self._snapshot)
        self._register(CountObjects, self._object_counts)
        self._register(SetAsyncioDebug, self._set_asyncio_debug)
        self._register(Ping, self._ping)
        self._register(Shutdown, self._shutdown)

    @property
    def connected(self) -> bool:
        return self._socket is not None

    def run(self) -> None:
        try:
            self._socket = socket.create_connection(
                (self._address.host, self._address.port), timeout=self._CONNECT_TIMEOUT
            )
        except OSError as error:
            sys.stderr.write(f"[pyprof] agent could not connect to collector: {error!r}\n")
            return
        self._socket.settimeout(None)  # blocking sends; reads are polled with select()
        self._send_hello()
        try:
            self._apply_start_options()
            self._serve(self._socket)
        except OSError, ValueError:
            pass  # collector went away or sent garbage: stop quietly, never disturb the program
        finally:
            self._cleanup()

    def _send_hello(self) -> None:
        hello = AgentHello(
            token=self._address.token,
            pid=os.getpid(),
            executable=sys.executable,
            argv=list(sys.argv),
            cwd=os.getcwd(),
            version=sys.version.split()[0],
            threads=self._thread_names(),
        )
        self._send(hello)

    def _apply_start_options(self) -> None:
        if self._options.tracemalloc:
            self._memory.start_tracing(self._options.tracemalloc_frames)
        if self._options.asyncio_debug:
            self._loops.set_debug(True, self._options.slow_callback_ms)

    def _serve(self, sock: socket.socket) -> None:
        lines = JsonLines()
        last_metrics = 0.0
        while not self._halt.is_set():
            readable, _, _ = select.select([sock], [], [], self._PROBE_INTERVAL)
            if readable:
                chunk = sock.recv(self._RECEIVE_SIZE)
                if not chunk:
                    break
                lines.feed(chunk)
                while (request := lines.next_message()) is not None:
                    self._dispatch(request)
            now = time.perf_counter()
            self._loops.probe(now)
            if now - last_metrics >= self._METRICS_INTERVAL:
                last_metrics = now
                self._send_metrics(now)

    def _register[R: AgentRequest](self, request_type: type[R], handler: Callable[[R], WireWritable]) -> None:
        self._commands[request_type.command] = lambda params: handler(request_type.from_wire(params, "params"))

    def _dispatch(self, raw: JsonObject) -> None:
        """Run one command. Raises ``WireError`` for a message that is not a command (the collector is broken)."""
        call = CommandCall.from_wire(raw)
        try:
            command = self._commands.get(call.method)
            if command is None:
                raise ValueError(f"unknown agent command {call.method!r}")
            reply = CommandResult(call.id, result=command(call.params).to_wire())
        except Exception as error:  # report every failure to the collector instead of dying
            reply = CommandResult(call.id, error=f"{type(error).__name__}: {error}")
        self._send(reply)

    def _send(self, message: AgentHello | AgentMetrics | CommandResult) -> None:
        data = JsonLines.encode(message.to_wire(), fallback=repr)
        with self._write_lock:
            if self._socket is None:
                return
            try:
                self._socket.sendall(data)
            except OSError:
                self._halt.set()

    def _send_metrics(self, now: float) -> None:
        events: list[AgentEvent] = []
        while self._events:
            events.append(self._events.popleft())
        metrics = AgentMetrics(
            threads=self._thread_names(),
            traced=self._memory.traced_memory(),
            loops=self._loops.take_metrics(now),
            events=events,
        )
        self._send(metrics)

    def _thread_names(self) -> list[ThreadName]:
        """Every thread of the program except the agent's own."""
        return [
            ThreadName(thread.ident, thread.native_id, thread.name)
            for thread in threading.enumerate()
            if thread is not self
        ]

    def _cleanup(self) -> None:
        """Undo everything the agent changed in the program."""
        self._memory.release()
        self._loops.set_debug(False)
        with self._write_lock:
            sock, self._socket = self._socket, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    # ---- commands: one per ``AgentCommand``, each returns the result sent back to the collector
    def _start_tracing(self, request: StartTracing) -> WireWritable:
        return self._memory.start_tracing(request.frames)

    def _stop_tracing(self, _request: StopTracing) -> WireWritable:
        return self._memory.stop_tracing()

    def _snapshot(self, request: TakeSnapshot) -> WireWritable:
        return self._memory.snapshot(request.limit)

    def _object_counts(self, request: CountObjects) -> WireWritable:
        return self._memory.object_counts(request.limit)

    def _set_asyncio_debug(self, request: SetAsyncioDebug) -> WireWritable:
        self._loops.set_debug(request.enabled, request.slow_ms)
        return AsyncioDebugStatus(self._loops.debug, self._loops.loop_count)

    def _ping(self, _request: Ping) -> WireWritable:
        return Pong(time.perf_counter(), os.getpid())

    def _shutdown(self, _request: Shutdown) -> WireWritable:
        self._halt.set()
        return Acknowledgement()


class AgentRegistry:
    """The one agent of this process, and the place where it is assembled."""

    _lock = threading.Lock()
    _agent: Agent | None = None

    @classmethod
    def start(cls, address: str, options_json: str | None) -> Agent:
        with cls._lock:
            if cls._agent is None or not cls._agent.is_alive():
                cls._agent = cls._create(AgentAddress.parse(address), AgentOptions.from_json(options_json))
                cls._agent.start()
            return cls._agent

    @staticmethod
    def _create(address: AgentAddress, options: AgentOptions) -> Agent:
        events: deque[AgentEvent] = deque()
        loops = LoopMonitor(AsyncioDebugCapture(events.append))
        return Agent(address, options, loops, MemoryProbe(), events)


def start(address: str, options_json: str | None = None) -> Agent:
    """Idempotently start the agent.

    Entry point for the launcher and for the script ``sys.remote_exec`` runs.
    Both arguments are text because they cross a process boundary (environment
    variable, injected script): ``address`` is an ``AgentAddress``
    (``host:port:token``), ``options_json`` an ``AgentOptions`` object as JSON.
    Raises ``ValueError`` for a malformed address.
    """
    return AgentRegistry.start(address, options_json)
