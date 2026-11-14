"""In-process agent: runs as a daemon thread *inside* the profiled program.

Started either by the launcher (start mode) or via ``sys.remote_exec`` (attach
mode). It connects back to the collector over localhost TCP (works on every
OS) and provides what cannot be read from outside:

* tracemalloc control, snapshots grouped by traceback
* event-loop lag probes and asyncio debug events (slow callbacks, never
  awaited coroutines, destroyed pending tasks)
* thread names, object type counts

Everything here is stdlib-only and must be cheap when idle. Because this code
runs in the *user's* process, modules the program may not use itself
(``asyncio``, ``tracemalloc``, ``logging``, ``warnings``, ``gc``) are ``lazy``
imports (PEP 810): they load on first use of the matching feature, so they
neither slow the program down nor change what the profile shows, and the
``"asyncio" in sys.modules`` checks still tell whether the *program* uses asyncio.
(In attach mode, a lazy-imports filter the program installed may load them
eagerly; that costs a few imports, never wrong data.)
"""

import json
import os
import select
import socket
import sys
import threading
import time
from collections import deque
from collections.abc import Callable
from types import FrameType
from typing import TextIO
lazy import asyncio
lazy import gc
lazy import logging
lazy import tracemalloc
lazy import warnings
lazy from collections import Counter

from _vscode_pyprof.wire import JsonObject, WireReader


class _LoopProbe:
    """Lag measurement state of one running event loop."""

    __slots__ = ("loop", "max_lag_ms", "pending_since", "thread_name")

    def __init__(self, loop: asyncio.AbstractEventLoop, thread_name: str) -> None:
        self.loop = loop
        self.thread_name = thread_name
        self.pending_since: float | None = None  # a probe was scheduled and has not run yet
        self.max_lag_ms = 0.0


class _AsyncioDebugCapture:
    """Collects asyncio debug output (log records and never-awaited warnings) as events."""

    def __init__(self, emit: Callable[[JsonObject], None]) -> None:
        self._emit = emit
        self._handler: logging.Handler | None = None
        self._original_showwarning: Callable[..., None] | None = None

    def install(self) -> None:
        if self._handler is None:
            capture = self

            class Handler(logging.Handler):
                def emit(self, record: logging.LogRecord) -> None:
                    try:
                        capture._on_log_record(record)
                    except Exception:  # never let profiling break the program's logging
                        return

            self._handler = Handler(level=logging.WARNING)
        logger = logging.getLogger("asyncio")
        if self._handler not in logger.handlers:
            logger.addHandler(self._handler)
        if self._original_showwarning is None:
            self._original_showwarning = warnings.showwarning
            warnings.showwarning = self._showwarning

    def remove(self) -> None:
        if self._handler is not None:
            logging.getLogger("asyncio").removeHandler(self._handler)
        if self._original_showwarning is not None:
            warnings.showwarning = self._original_showwarning
            self._original_showwarning = None

    def _showwarning(
        self,
        message: Warning | str,
        category: type[Warning],
        filename: str,
        lineno: int,
        file: TextIO | None = None,
        line: str | None = None,
    ) -> None:
        try:
            text = str(message)
            if issubclass(category, RuntimeWarning) and "never awaited" in text:
                self._emit(
                    {
                        "t": time.perf_counter(),
                        "kind": "never-awaited",
                        "message": text,
                        "file": filename,
                        "line": lineno,
                    }
                )
        except Exception:  # never let profiling break the program's warnings
            pass
        if self._original_showwarning is not None:
            self._original_showwarning(message, category, filename, lineno, file, line)

    def _on_log_record(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        event: JsonObject = {
            "t": time.perf_counter(),
            "kind": "asyncio",
            "message": message[:2000],
            "thread": threading.current_thread().name,
        }
        if message.startswith("Executing") and "took" in message:
            event["kind"] = "slow-callback"
            args = record.args
            if isinstance(args, tuple) and len(args) >= 2 and isinstance(args[-1], (int, float)):
                event["seconds"] = float(args[-1])
                event["handle"] = str(args[0])[:500]
        elif "was destroyed but it is pending" in message:
            event["kind"] = "task-destroyed-pending"
        elif "exception was never retrieved" in message:
            event["kind"] = "exception-never-retrieved"
        self._emit(event)


class Agent(threading.Thread):
    _METRICS_INTERVAL = 0.5
    _PROBE_INTERVAL = 0.1
    _LOOP_SCAN_INTERVAL = 2.0
    _CONNECT_TIMEOUT = 10.0
    _SOURCE_FILE = os.path.abspath(__file__)

    def __init__(self, host: str, port: int, token: str, options: WireReader) -> None:
        super().__init__(name="pyprof-agent", daemon=True)
        self._address = (host, port)
        self._token = token
        self._options = options
        self._socket: socket.socket | None = None
        self._write_lock = threading.Lock()
        self._halt = threading.Event()
        self._loops: dict[int, _LoopProbe] = {}
        self._last_loop_scan = 0.0
        self._asyncio_debug = False
        self._slow_callback_ms = 100.0
        self._events: deque[JsonObject] = deque()  # appended from any thread
        self._debug_capture = _AsyncioDebugCapture(self._events.append)
        self._started_tracemalloc = False
        self._commands: dict[str, Callable[[WireReader], JsonObject]] = {
            "tracemalloc_start": self._cmd_tracemalloc_start,
            "tracemalloc_stop": self._cmd_tracemalloc_stop,
            "snapshot": self._cmd_snapshot,
            "object_counts": self._cmd_object_counts,
            "asyncio_debug": self._cmd_asyncio_debug,
            "ping": self._cmd_ping,
            "shutdown": self._cmd_shutdown,
        }

    @property
    def connected(self) -> bool:
        return self._socket is not None

    # ------------------------------------------------------------- transport
    def run(self) -> None:
        try:
            self._socket = socket.create_connection(self._address, timeout=self._CONNECT_TIMEOUT)
        except OSError as error:
            sys.stderr.write(f"[pyprof] agent could not connect to collector: {error!r}\n")
            return
        self._socket.settimeout(None)  # blocking sends; reads are polled with select()
        self._send(
            {
                "type": "hello",
                "token": self._token,
                "pid": os.getpid(),
                "executable": sys.executable,
                "argv": sys.argv,
                "cwd": os.getcwd(),
                "version": sys.version.split()[0],
                "threads": self._thread_names(),
            }
        )
        try:
            self._apply_start_options()
            self._serve(self._socket)
        except OSError, ValueError:
            pass  # collector went away or sent garbage: stop quietly, never disturb the program
        finally:
            self._cleanup()

    def _apply_start_options(self) -> None:
        if self._options.get_bool("tracemalloc", False):
            self._cmd_tracemalloc_start(WireReader({"frames": self._options.get_int("tracemallocFrames", 16)}))
        if self._options.get_bool("asyncioDebug", False):
            self._slow_callback_ms = self._options.get_float("slowCallbackMs", self._slow_callback_ms)
            self._set_asyncio_debug(True)

    def _serve(self, sock: socket.socket) -> None:
        buffer = b""
        last_metrics = 0.0
        while not self._halt.is_set():
            readable, _, _ = select.select([sock], [], [], self._PROBE_INTERVAL)
            if readable:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if line.strip():
                        self._dispatch(WireReader.of(json.loads(line)))
            now = time.perf_counter()
            self._probe_loops(now)
            if now - last_metrics >= self._METRICS_INTERVAL:
                last_metrics = now
                self._send_metrics(now)

    def _dispatch(self, request: WireReader) -> None:
        method = request.get_optional_str("method") or ""
        reply: JsonObject = {"type": "result", "id": request.get_raw("id")}
        try:
            command = self._commands.get(method)
            if command is None:
                raise ValueError(f"unknown agent command {method!r}")
            reply["result"] = command(request.get_object("params"))
        except Exception as error:  # report every failure to the collector instead of dying
            reply["error"] = f"{type(error).__name__}: {error}"
        self._send(reply)

    def _send(self, message: JsonObject) -> None:
        data = (json.dumps(message, separators=(",", ":"), default=repr) + "\n").encode("utf-8")
        with self._write_lock:
            if self._socket is None:
                return
            try:
                self._socket.sendall(data)
            except OSError:
                self._halt.set()

    def _cleanup(self) -> None:
        """Undo everything the agent changed in the program."""
        if self._started_tracemalloc:
            tracemalloc.stop()
            self._started_tracemalloc = False
        self._set_asyncio_debug(False)
        with self._write_lock:
            sock, self._socket = self._socket, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    # --------------------------------------------------------------- metrics
    def _thread_names(self) -> list[list[object]]:
        return [[t.ident, t.native_id, t.name] for t in threading.enumerate() if t is not self]

    def _send_metrics(self, now: float) -> None:
        metrics: JsonObject = {"type": "metrics", "threads": self._thread_names()}
        # `in sys.modules` first: never load tracemalloc into a program that does not use it
        if "tracemalloc" in sys.modules and tracemalloc.is_tracing():
            current, peak = tracemalloc.get_traced_memory()
            metrics["traced"] = current
            metrics["tracedPeak"] = peak
        loops: list[JsonObject] = []
        for key, probe in list(self._loops.items()):
            lag = probe.max_lag_ms
            if probe.pending_since is not None:  # still waiting: the loop is blocked right now
                lag = max(lag, (now - probe.pending_since) * 1000.0)
            loops.append(
                {
                    "loop": key,
                    "thread": probe.thread_name,
                    "lagMs": round(lag, 3),
                    "tasks": self._task_count(probe.loop),
                }
            )
            probe.max_lag_ms = 0.0
        if loops:
            metrics["loops"] = loops
        events: list[JsonObject] = []
        while self._events:
            events.append(self._events.popleft())
        if events:
            metrics["events"] = events
        self._send(metrics)

    @staticmethod
    def _task_count(loop: asyncio.AbstractEventLoop) -> int | None:
        try:
            return len(asyncio.all_tasks(loop))
        except RuntimeError:  # task set changed while iterating
            return None

    # ------------------------------------------------------- event loop lag
    def _probe_loops(self, now: float) -> None:
        if "asyncio" not in sys.modules:
            return  # the program does not use asyncio (yet)
        if now - self._last_loop_scan > self._LOOP_SCAN_INTERVAL:
            self._last_loop_scan = now
            self._scan_loops()
        for key, probe in list(self._loops.items()):
            if probe.loop.is_closed() or not probe.loop.is_running():
                self._loops.pop(key, None)
                continue
            if probe.pending_since is not None:
                continue  # previous probe not yet executed: loop is blocked
            probe.pending_since = now
            try:
                probe.loop.call_soon_threadsafe(self._probe_done, key, now)
            except RuntimeError:
                self._loops.pop(key, None)

    def _probe_done(self, key: int, sent: float) -> None:
        """Runs on the event loop: the time since ``sent`` is how long a callback had to wait."""
        probe = self._loops.get(key)
        if probe is None:
            return
        probe.max_lag_ms = max(probe.max_lag_ms, (time.perf_counter() - sent) * 1000.0)
        probe.pending_since = None

    def _scan_loops(self) -> None:
        """Find running event loops by walking the frames of every thread."""
        names = {t.ident: t.name for t in threading.enumerate()}
        for ident, top_frame in sys._current_frames().items():
            frame: FrameType | None = top_frame
            while frame is not None:
                if frame.f_code.co_name in ("run_forever", "_run_once"):
                    loop = frame.f_locals.get("self")
                    if isinstance(loop, asyncio.AbstractEventLoop):
                        if id(loop) not in self._loops:
                            self._loops[id(loop)] = _LoopProbe(loop, names.get(ident, str(ident)))
                            if self._asyncio_debug:
                                self._apply_debug(loop, True)
                        break
                frame = frame.f_back

    # ---------------------------------------------------------- asyncio debug
    def _cmd_asyncio_debug(self, params: WireReader) -> JsonObject:
        self._slow_callback_ms = params.get_float("slowMs", self._slow_callback_ms)
        self._set_asyncio_debug(params.get_bool("enabled", True))
        return {"enabled": self._asyncio_debug, "loops": len(self._loops)}

    def _set_asyncio_debug(self, enabled: bool) -> None:
        if enabled == self._asyncio_debug:
            return
        self._asyncio_debug = enabled
        if "asyncio" in sys.modules:
            self._scan_loops()
        for probe in list(self._loops.values()):
            self._apply_debug(probe.loop, enabled)
        if enabled:
            self._debug_capture.install()
        else:
            self._debug_capture.remove()

    def _apply_debug(self, loop: asyncio.AbstractEventLoop, enabled: bool) -> None:
        slow_callback_seconds = self._slow_callback_ms / 1000.0

        def apply() -> None:
            loop.set_debug(enabled)
            loop.slow_callback_duration = slow_callback_seconds

        try:
            loop.call_soon_threadsafe(apply)
        except RuntimeError:
            pass  # loop closed in the meantime

    # ------------------------------------------------------------ tracemalloc
    def _cmd_tracemalloc_start(self, params: WireReader) -> JsonObject:
        if not tracemalloc.is_tracing():
            tracemalloc.start(params.get_int("frames", 16))
            self._started_tracemalloc = True
        return {"tracing": True, "frames": tracemalloc.get_traceback_limit()}

    def _cmd_tracemalloc_stop(self, _params: WireReader) -> JsonObject:
        tracemalloc.stop()
        self._started_tracemalloc = False
        return {"tracing": False}

    def _cmd_snapshot(self, params: WireReader) -> JsonObject:
        if not tracemalloc.is_tracing():
            raise RuntimeError("tracemalloc is not running; start memory tracing first")
        # A snapshot is stop-the-world anyway; hold the GIL longer so a busy
        # program does not stretch a 1s snapshot into 10s of contention.
        switch_interval = sys.getswitchinterval()
        sys.setswitchinterval(1.0)
        try:
            return self._snapshot(tracemalloc.take_snapshot, params.get_int("limit", 3000))
        finally:
            sys.setswitchinterval(switch_interval)

    def _snapshot(self, take_snapshot: Callable[[], tracemalloc.Snapshot], limit: int) -> JsonObject:
        started = time.perf_counter()
        # Filter after grouping: Snapshot.filter_traces() runs fnmatch per trace
        # in Python and dominates snapshot time on large heaps.
        statistics = [s for s in take_snapshot().statistics("traceback") if not self._is_own_allocation(s.traceback)]
        top, rest = statistics[:limit], statistics[limit:]
        current, peak = tracemalloc.get_traced_memory()
        return {
            "t": started,
            "totalSize": sum(s.size for s in statistics),
            "totalCount": sum(s.count for s in statistics),
            "otherSize": sum(s.size for s in rest),
            "otherCount": sum(s.count for s in rest),
            "traced": current,
            "peak": peak,
            # frames oldest first, as tracemalloc reports them
            "top": [[[[frame.filename, frame.lineno] for frame in s.traceback], s.size, s.count] for s in top],
            "takeMs": round((time.perf_counter() - started) * 1000, 1),
        }

    @staticmethod
    def _is_own_allocation(traceback: tracemalloc.Traceback) -> bool:
        """Allocated by tracemalloc itself or anywhere inside this agent."""
        if len(traceback) and traceback[-1].filename == tracemalloc.__file__:
            return True
        return any(frame.filename == Agent._SOURCE_FILE for frame in traceback)

    # ---------------------------------------------------------- object counts
    def _cmd_object_counts(self, params: WireReader) -> JsonObject:
        counts: Counter[str] = Counter()
        for obj in gc.get_objects():
            cls = type(obj)
            counts[cls.__qualname__ if cls.__module__ == "builtins" else f"{cls.__module__}.{cls.__qualname__}"] += 1
        return {"t": time.perf_counter(), "counts": counts.most_common(params.get_int("limit", 60))}

    def _cmd_ping(self, _params: WireReader) -> JsonObject:
        return {"t": time.perf_counter(), "pid": os.getpid()}

    def _cmd_shutdown(self, _params: WireReader) -> JsonObject:
        self._halt.set()
        return {"ok": True}


class AgentRegistry:
    """The one agent of this process."""

    _lock = threading.Lock()
    _agent: Agent | None = None

    @classmethod
    def start(cls, host: str, port: int, token: str, options: dict[str, object] | None) -> Agent:
        with cls._lock:
            if cls._agent is None or not cls._agent.is_alive():
                cls._agent = Agent(host, port, token, WireReader(options or {}))
                cls._agent.start()
            return cls._agent


def start(host: str, port: int, token: str, options: dict[str, object] | None = None) -> Agent:
    """Idempotently start the agent. Entry point for the launcher and ``sys.remote_exec``."""
    return AgentRegistry.start(host, port, token, options)
