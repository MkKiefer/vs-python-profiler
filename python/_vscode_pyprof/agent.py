"""In-process agent: runs as a daemon thread *inside* the profiled program.

Started either by the launcher (start mode) or via ``sys.remote_exec`` (attach
mode). It connects back to the collector over localhost TCP (works on every
OS) and provides what cannot be read from outside:

* tracemalloc control, snapshots grouped by traceback
* event-loop lag probes and asyncio debug events (slow callbacks, never
  awaited coroutines, destroyed pending tasks)
* thread names, object type counts

Everything here is stdlib-only and must be cheap when idle.
"""

import json
import os
import select
import socket
import sys
import threading
import time

_agent = None
_lock = threading.Lock()


def start(host, port, token, options=None):
    """Idempotently start the agent. Safe to call from ``sys.remote_exec``."""
    global _agent
    with _lock:
        if _agent is not None and _agent.is_alive():
            return _agent
        _agent = Agent(host, int(port), token, options or {})
        _agent.start()
        return _agent


class _AsyncioLogHandler:
    """Lazily created logging.Handler capturing asyncio debug warnings."""

    def __init__(self, agent):
        import logging

        class H(logging.Handler):
            def emit(self, record):
                try:
                    agent.on_asyncio_log(record)
                except Exception:
                    pass

        self.handler = H(level=logging.WARNING)
        self.logger = logging.getLogger("asyncio")

    def install(self):
        if self.handler not in self.logger.handlers:
            self.logger.addHandler(self.handler)

    def remove(self):
        try:
            self.logger.removeHandler(self.handler)
        except Exception:
            pass


class Agent(threading.Thread):
    METRICS_INTERVAL = 0.5
    PROBE_INTERVAL = 0.1

    def __init__(self, host, port, token, options):
        super().__init__(name="pyprof-agent", daemon=True)
        self.addr = (host, port)
        self.token = token
        self.options = options
        self.sock = None
        self._wlock = threading.Lock()
        self._halt = threading.Event()
        self._loops = {}  # id(loop) -> [loop, thread_name, pending_since, max_lag]
        self._last_loop_scan = 0.0
        self._asyncio_debug = False
        self._slow_ms = 100
        self._log_handler = None
        self._orig_showwarning = None
        self._events = []
        self._started_tracemalloc = False

    # ------------------------------------------------------------- transport
    def send(self, msg):
        data = (json.dumps(msg, separators=(",", ":"), default=repr) + "\n").encode("utf-8")
        with self._wlock:
            if self.sock is None:
                return
            try:
                self.sock.sendall(data)
            except OSError:
                self._halt.set()

    def run(self):
        try:
            self.sock = socket.create_connection(self.addr, timeout=10)
        except OSError as e:
            sys.stderr.write("[pyprof] agent could not connect to collector: %r\n" % (e,))
            return
        self.sock.settimeout(None)  # blocking sends; reads are polled with select()
        self.send({
            "type": "hello", "token": self.token, "pid": os.getpid(),
            "executable": sys.executable, "argv": sys.argv, "cwd": os.getcwd(),
            "version": sys.version.split()[0], "threads": self._threads(),
        })
        if self.options.get("tracemalloc"):
            self.cmd_tracemalloc_start({"frames": self.options.get("tracemallocFrames", 16)})
        if self.options.get("asyncioDebug"):
            self.cmd_asyncio_debug({"enabled": True, "slowMs": self.options.get("slowCallbackMs", 100)})
        buf = b""
        last_metrics = 0.0
        try:
            while not self._halt.is_set():
                readable, _, _ = select.select([self.sock], [], [], self.PROBE_INTERVAL)
                if readable:
                    chunk = self.sock.recv(65536)
                    if not chunk:
                        break
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        if line.strip():
                            self._dispatch(json.loads(line))
                now = time.perf_counter()
                self._probe_loops(now)
                if now - last_metrics >= self.METRICS_INTERVAL:
                    last_metrics = now
                    self._send_metrics()
        except (OSError, ValueError):
            pass
        finally:
            self._cleanup()

    def _dispatch(self, msg):
        method = msg.get("method", "")
        handler = getattr(self, "cmd_" + method, None)
        try:
            if handler is None:
                raise ValueError("unknown agent command %r" % method)
            result = handler(msg.get("params") or {})
            self.send({"type": "result", "id": msg.get("id"), "result": result})
        except Exception as e:
            self.send({"type": "result", "id": msg.get("id"), "error": "%s: %s" % (type(e).__name__, e)})

    def _cleanup(self):
        try:
            if self._started_tracemalloc:
                import tracemalloc

                tracemalloc.stop()
        except Exception:
            pass
        self._set_asyncio_debug(False)
        try:
            self.sock.close()
        except Exception:
            pass
        self.sock = None

    # --------------------------------------------------------------- metrics
    def _threads(self):
        return [[t.ident, getattr(t, "native_id", None), t.name] for t in threading.enumerate()
                if t is not self]

    def _send_metrics(self):
        m = {"type": "metrics", "threads": self._threads()}
        if "tracemalloc" in sys.modules:
            import tracemalloc

            if tracemalloc.is_tracing():
                cur, peak = tracemalloc.get_traced_memory()
                m["traced"] = cur
                m["tracedPeak"] = peak
                m["tracemallocOverhead"] = tracemalloc.get_tracemalloc_memory()
        lags = []
        now = time.perf_counter()
        for key, rec in list(self._loops.items()):
            loop, tname, pending, max_lag = rec
            lag = max_lag
            if pending is not None:
                lag = max(lag, (now - pending) * 1000.0)
            lags.append({"loop": key, "thread": tname, "lagMs": round(lag, 3),
                         "tasks": self._task_count(loop)})
            rec[3] = 0.0
        if lags:
            m["loops"] = lags
        if self._events:
            m["events"], self._events = self._events, []
        self.send(m)

    @staticmethod
    def _task_count(loop):
        try:
            import asyncio

            return len(asyncio.all_tasks(loop))
        except Exception:
            return None

    # ------------------------------------------------------- event loop lag
    def _probe_loops(self, now):
        if "asyncio" not in sys.modules:
            return
        if now - self._last_loop_scan > 2.0:
            self._last_loop_scan = now
            self._scan_loops()
        for key, rec in list(self._loops.items()):
            loop = rec[0]
            if loop.is_closed() or not loop.is_running():
                self._loops.pop(key, None)
                continue
            if rec[2] is not None:
                continue  # previous probe not yet executed: loop is blocked
            rec[2] = now
            try:
                loop.call_soon_threadsafe(self._probe_done, key, now)
            except RuntimeError:
                self._loops.pop(key, None)

    def _probe_done(self, key, sent):
        rec = self._loops.get(key)
        if rec is None:
            return
        lag = (time.perf_counter() - sent) * 1000.0
        if lag > rec[3]:
            rec[3] = lag
        rec[2] = None

    def _scan_loops(self):
        """Find running event loops by walking the frames of every thread."""
        import asyncio

        names = {t.ident: t.name for t in threading.enumerate()}
        for ident, frame in sys._current_frames().items():
            f = frame
            while f is not None:
                if f.f_code.co_name in ("run_forever", "_run_once"):
                    loop = f.f_locals.get("self")
                    if isinstance(loop, asyncio.AbstractEventLoop):
                        key = id(loop)
                        if key not in self._loops:
                            self._loops[key] = [loop, names.get(ident, str(ident)), None, 0.0]
                            if self._asyncio_debug:
                                self._apply_debug(loop, True)
                        break
                f = f.f_back

    # ---------------------------------------------------------- asyncio debug
    def cmd_asyncio_debug(self, p):
        self._slow_ms = float(p.get("slowMs", self._slow_ms))
        self._set_asyncio_debug(bool(p.get("enabled", True)))
        return {"enabled": self._asyncio_debug, "loops": len(self._loops)}

    def _set_asyncio_debug(self, enabled):
        if enabled == self._asyncio_debug:
            return
        self._asyncio_debug = enabled
        if "asyncio" in sys.modules:
            self._scan_loops()
        for rec in list(self._loops.values()):
            self._apply_debug(rec[0], enabled)
        import warnings

        if enabled:
            if self._log_handler is None:
                self._log_handler = _AsyncioLogHandler(self)
            self._log_handler.install()
            self._orig_showwarning = warnings.showwarning
            orig = self._orig_showwarning

            def showwarning(message, category, filename, lineno, file=None, line=None):
                try:
                    if issubclass(category, RuntimeWarning) and "never awaited" in str(message):
                        self._events.append({"t": time.perf_counter(), "kind": "never-awaited",
                                             "message": str(message), "file": filename, "line": lineno})
                except Exception:
                    pass
                return orig(message, category, filename, lineno, file, line)

            warnings.showwarning = showwarning
        else:
            if self._log_handler is not None:
                self._log_handler.remove()
            if self._orig_showwarning is not None:
                warnings.showwarning = self._orig_showwarning
                self._orig_showwarning = None

    def _apply_debug(self, loop, enabled):
        def apply():
            loop.set_debug(enabled)
            loop.slow_callback_duration = self._slow_ms / 1000.0
        try:
            loop.call_soon_threadsafe(apply)
        except RuntimeError:
            pass

    def on_asyncio_log(self, record):
        msg = record.getMessage()
        kind = "asyncio"
        extra = {}
        if msg.startswith("Executing") and "took" in msg:
            kind = "slow-callback"
            try:
                extra["seconds"] = float(record.args[-1])
                extra["handle"] = str(record.args[0])[:500]
            except Exception:
                pass
        elif "was destroyed but it is pending" in msg:
            kind = "task-destroyed-pending"
        elif "exception was never retrieved" in msg:
            kind = "exception-never-retrieved"
        ev = {"t": time.perf_counter(), "kind": kind, "message": msg[:2000],
              "thread": threading.current_thread().name}
        ev.update(extra)
        self._events.append(ev)

    # ------------------------------------------------------------ tracemalloc
    def cmd_tracemalloc_start(self, p):
        import tracemalloc

        if not tracemalloc.is_tracing():
            tracemalloc.start(int(p.get("frames", 16)))
            self._started_tracemalloc = True
        return {"tracing": True, "frames": tracemalloc.get_traceback_limit()}

    def cmd_tracemalloc_stop(self, p):
        import tracemalloc

        tracemalloc.stop()
        self._started_tracemalloc = False
        return {"tracing": False}

    def cmd_snapshot(self, p):
        import tracemalloc

        if not tracemalloc.is_tracing():
            raise RuntimeError("tracemalloc is not running; start memory tracing first")
        t = time.perf_counter()
        # A snapshot is stop-the-world anyway; hold the GIL longer so a busy
        # program does not stretch a 1s snapshot into 10s of contention.
        old_switch = sys.getswitchinterval()
        sys.setswitchinterval(1.0)
        try:
            return self._snapshot(p, t)
        finally:
            sys.setswitchinterval(old_switch)

    def _snapshot(self, p, t):
        import tracemalloc

        snap = tracemalloc.take_snapshot()
        # Filter after grouping: Snapshot.filter_traces() runs fnmatch per trace
        # in Python and dominates snapshot time on large heaps.
        agent_file = os.path.abspath(__file__)
        if agent_file.endswith((".pyc", ".pyo")):
            agent_file = agent_file[:-1]
        tm_file = tracemalloc.__file__

        def ours(tb):  # allocated by tracemalloc itself or anywhere inside this agent
            if len(tb) and tb[-1].filename == tm_file:
                return True
            return any(fr.filename == agent_file for fr in tb)

        stats = [s for s in snap.statistics("traceback") if not ours(s.traceback)]
        limit = int(p.get("limit", 3000))
        total_size = sum(s.size for s in stats)
        total_count = sum(s.count for s in stats)
        top = []
        for s in stats[:limit]:
            top.append([[[fr.filename, fr.lineno] for fr in s.traceback], s.size, s.count])
        rest = stats[limit:]
        cur, peak = tracemalloc.get_traced_memory()
        return {
            "t": t, "totalSize": total_size, "totalCount": total_count,
            "otherSize": sum(s.size for s in rest), "otherCount": sum(s.count for s in rest),
            "traced": cur, "peak": peak, "top": top,
            "takeMs": round((time.perf_counter() - t) * 1000, 1),
        }

    # ---------------------------------------------------------- object counts
    def cmd_object_counts(self, p):
        import gc
        from collections import Counter

        c = Counter()
        for o in gc.get_objects():
            tp = type(o)
            c[tp.__module__ + "." + tp.__qualname__ if tp.__module__ != "builtins" else tp.__qualname__] += 1
        return {"t": time.perf_counter(), "counts": c.most_common(int(p.get("limit", 60)))}

    def cmd_ping(self, p):
        return {"t": time.perf_counter(), "pid": os.getpid()}

    def cmd_shutdown(self, p):
        self._halt.set()
        return {"ok": True}
