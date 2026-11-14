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

from _vscode_pyprof.agent_protocol import AgentAddress, AgentCommand, AgentMessageType
from _vscode_pyprof.target.asyncio_debug import AsyncioDebugCapture
from _vscode_pyprof.target.loop_monitor import LoopMonitor
from _vscode_pyprof.target.memory_probe import MemoryProbe
from _vscode_pyprof.wire import JsonLines, JsonObject, WireReader


class Agent(threading.Thread):
    """Serves the collector's commands and reports metrics until the collector goes away."""

    _METRICS_INTERVAL = 0.5
    _PROBE_INTERVAL = 0.1
    _CONNECT_TIMEOUT = 10.0
    _RECEIVE_SIZE = 65536
    _DEFAULT_TRACEBACK_FRAMES = 16
    _DEFAULT_SNAPSHOT_LIMIT = 3000
    _DEFAULT_OBJECT_COUNT_LIMIT = 60

    def __init__(
        self,
        address: AgentAddress,
        options: WireReader,
        loops: LoopMonitor,
        memory: MemoryProbe,
        events: deque[JsonObject],
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
        self._commands: dict[str, Callable[[WireReader], JsonObject]] = {
            AgentCommand.TRACEMALLOC_START: self._start_tracing,
            AgentCommand.TRACEMALLOC_STOP: self._stop_tracing,
            AgentCommand.SNAPSHOT: self._snapshot,
            AgentCommand.OBJECT_COUNTS: self._object_counts,
            AgentCommand.ASYNCIO_DEBUG: self._set_asyncio_debug,
            AgentCommand.PING: self._ping,
            AgentCommand.SHUTDOWN: self._shutdown,
        }

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
        self._send(
            {
                "type": AgentMessageType.HELLO,
                "token": self._address.token,
                "pid": os.getpid(),
                "executable": sys.executable,
                "argv": sys.argv,
                "cwd": os.getcwd(),
                "version": sys.version.split()[0],
                "threads": self._thread_names(),
            }
        )

    def _apply_start_options(self) -> None:
        if self._options.get_bool("tracemalloc", False):
            self._memory.start_tracing(self._options.get_int("tracemallocFrames", self._DEFAULT_TRACEBACK_FRAMES))
        if self._options.get_bool("asyncioDebug", False):
            slow_callback_ms = (
                self._options.get_float("slowCallbackMs") if self._options.has("slowCallbackMs") else None
            )
            self._loops.set_debug(True, slow_callback_ms)

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

    def _dispatch(self, request: WireReader) -> None:
        method = request.get_optional_str("method") or ""
        reply: JsonObject = {"type": AgentMessageType.RESULT, "id": request.get_raw("id")}
        try:
            command = self._commands.get(method)
            if command is None:
                raise ValueError(f"unknown agent command {method!r}")
            reply["result"] = command(request.get_object("params"))
        except Exception as error:  # report every failure to the collector instead of dying
            reply["error"] = f"{type(error).__name__}: {error}"
        self._send(reply)

    def _send(self, message: JsonObject) -> None:
        data = JsonLines.encode(message, fallback=repr)
        with self._write_lock:
            if self._socket is None:
                return
            try:
                self._socket.sendall(data)
            except OSError:
                self._halt.set()

    def _send_metrics(self, now: float) -> None:
        metrics: JsonObject = {"type": AgentMessageType.METRICS, "threads": self._thread_names()}
        traced = self._memory.traced_memory()
        if traced is not None:
            metrics["traced"], metrics["tracedPeak"] = traced
        loops = self._loops.take_metrics(now)
        if loops:
            metrics["loops"] = loops
        events: list[JsonObject] = []
        while self._events:
            events.append(self._events.popleft())
        if events:
            metrics["events"] = events
        self._send(metrics)

    def _thread_names(self) -> list[list[int | str | None]]:
        return [[t.ident, t.native_id, t.name] for t in threading.enumerate() if t is not self]

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
    def _start_tracing(self, params: WireReader) -> JsonObject:
        return self._memory.start_tracing(params.get_int("frames", self._DEFAULT_TRACEBACK_FRAMES))

    def _stop_tracing(self, _params: WireReader) -> JsonObject:
        return self._memory.stop_tracing()

    def _snapshot(self, params: WireReader) -> JsonObject:
        return self._memory.snapshot(params.get_int("limit", self._DEFAULT_SNAPSHOT_LIMIT))

    def _object_counts(self, params: WireReader) -> JsonObject:
        return self._memory.object_counts(params.get_int("limit", self._DEFAULT_OBJECT_COUNT_LIMIT))

    def _set_asyncio_debug(self, params: WireReader) -> JsonObject:
        slow_callback_ms = params.get_float("slowMs") if params.has("slowMs") else None
        self._loops.set_debug(params.get_bool("enabled", True), slow_callback_ms)
        return {"enabled": self._loops.debug, "loops": self._loops.loop_count}

    def _ping(self, _params: WireReader) -> JsonObject:
        return {"t": time.perf_counter(), "pid": os.getpid()}

    def _shutdown(self, _params: WireReader) -> JsonObject:
        self._halt.set()
        return {"ok": True}


class AgentRegistry:
    """The one agent of this process, and the place where it is assembled."""

    _lock = threading.Lock()
    _agent: Agent | None = None

    @classmethod
    def start(cls, address: str, options: dict[str, object] | None) -> Agent:
        with cls._lock:
            if cls._agent is None or not cls._agent.is_alive():
                cls._agent = cls._create(AgentAddress.parse(address), WireReader(options or {}))
                cls._agent.start()
            return cls._agent

    @staticmethod
    def _create(address: AgentAddress, options: WireReader) -> Agent:
        events: deque[JsonObject] = deque()
        loops = LoopMonitor(AsyncioDebugCapture(events.append))
        return Agent(address, options, loops, MemoryProbe(), events)


def start(address: str, options: dict[str, object] | None = None) -> Agent:
    """Idempotently start the agent; ``address`` is ``host:port:token``.

    Entry point for the launcher and for the script ``sys.remote_exec`` runs.
    """
    return AgentRegistry.start(address, options)
