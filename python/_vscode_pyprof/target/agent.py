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

from _vscode_pyprof.agent_protocol.address import AgentAddress
from _vscode_pyprof.agent_protocol.commands import (
    CountObjects,
    Ping,
    SetAsyncioDebug,
    Shutdown,
    StartTracing,
    StopTracing,
    TakeSnapshot,
)
from _vscode_pyprof.agent_protocol.hello import AgentHello, ThreadName
from _vscode_pyprof.agent_protocol.messages import TO_AGENT
from _vscode_pyprof.agent_protocol.metrics import AgentEvent, AgentMetrics
from _vscode_pyprof.agent_protocol.options import AgentOptions
from _vscode_pyprof.agent_protocol.replies import AsyncioDebugStatus, Pong
from _vscode_pyprof.target.asyncio_debug import AsyncioDebugCapture
from _vscode_pyprof.target.loop_monitor import LoopMonitor
from _vscode_pyprof.target.memory_probe import MemoryProbe
from _vscode_pyprof.wire import LineBuffer, Request, Response, WireDecoder, WireEncoder, WireError


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
        encoder: WireEncoder,
        decoder: WireDecoder,
    ) -> None:
        """``events`` is filled from any thread; the agent drains it into its metrics."""
        super().__init__(name="pyprof-agent", daemon=True)
        self._address = address
        self._options = options
        self._loops = loops
        self._memory = memory
        self._events = events
        self._encoder = encoder
        self._decoder = decoder
        self._socket: socket.socket | None = None
        self._write_lock = threading.Lock()
        self._halt = threading.Event()

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
        lines = LineBuffer()
        last_metrics = 0.0
        while not self._halt.is_set():
            readable, _, _ = select.select([sock], [], [], self._PROBE_INTERVAL)
            if readable:
                chunk = sock.recv(self._RECEIVE_SIZE)
                if not chunk:
                    break
                lines.feed(chunk)
                while (line := lines.next_line()) is not None:
                    self._answer(line)
            now = time.perf_counter()
            self._loops.probe(now)
            if now - last_metrics >= self._METRICS_INTERVAL:
                last_metrics = now
                self._send_metrics(now)

    def _answer(self, line: bytes) -> None:
        """Run one command. Raises ``ValueError`` for a line that is not a request (the collector is broken)."""
        request = self._decoder.decode(line)
        if not isinstance(request, Request):
            raise WireError(f"expected a Request, got {type(request).__name__}")
        try:
            response = Response(request.id, result=self._run(request.body))
        except Exception as error:  # report every failure to the collector instead of dying
            response = Response(request.id, error=f"{type(error).__name__}: {error}")
        self._send(response)

    def _run(self, command: object) -> object:
        """What one command answers; see ``agent_protocol.commands``."""
        match command:
            case StartTracing(frames=frames):
                return self._memory.start_tracing(frames)
            case StopTracing():
                return self._memory.stop_tracing()
            case TakeSnapshot(limit=limit):
                return self._memory.snapshot(limit)
            case CountObjects(limit=limit):
                return self._memory.object_counts(limit)
            case SetAsyncioDebug(enabled=enabled, slow_ms=slow_ms):
                self._loops.set_debug(enabled, slow_ms)
                return AsyncioDebugStatus(self._loops.debug, self._loops.loop_count)
            case Ping():
                return Pong(time.perf_counter(), os.getpid())
            case Shutdown():
                self._halt.set()
                return None
        raise ValueError(f"unknown agent command {type(command).__name__}")

    def _send(self, message: AgentHello | AgentMetrics | Response) -> None:
        data = self._encoder.encode(message)
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


class AgentRegistry:
    """The one agent of this process, and the place where it is assembled."""

    _lock = threading.Lock()
    _agent: Agent | None = None

    @classmethod
    def start(cls, address: str, options_json: str | None) -> Agent:
        with cls._lock:
            if cls._agent is None or not cls._agent.is_alive():
                cls._agent = cls._create(AgentAddress.parse(address), options_json)
                cls._agent.start()
            return cls._agent

    @classmethod
    def _create(cls, address: AgentAddress, options_json: str | None) -> Agent:
        decoder = WireDecoder(TO_AGENT)
        events: deque[AgentEvent] = deque()
        loops = LoopMonitor(AsyncioDebugCapture(events.append))
        options = cls.read_options(decoder, options_json)
        return Agent(address, options, loops, MemoryProbe(), events, WireEncoder(), decoder)

    @staticmethod
    def read_options(decoder: WireDecoder, options_json: str | None) -> AgentOptions:
        """The options the collector wrote; text that is missing or unusable gives the defaults."""
        try:
            options = decoder.decode(options_json) if options_json else None
        except ValueError:  # not JSON, or not a message
            options = None
        return options if isinstance(options, AgentOptions) else AgentOptions()


def start(address: str, options_json: str | None = None) -> Agent:
    """Idempotently start the agent.

    Entry point for the launcher and for the script ``sys.remote_exec`` runs.
    Both arguments are text because they cross a process boundary (environment
    variable, injected script): ``address`` is an ``AgentAddress``
    (``host:port:token``), ``options_json`` an ``AgentOptions`` message as one JSON line.
    Raises ``ValueError`` for a malformed address.
    """
    return AgentRegistry.start(address, options_json)
