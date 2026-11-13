"""Tachyon adapter: the only module that touches ``_remote_debugging``.

We drive ``_remote_debugging.RemoteUnwinder`` directly instead of shelling out
to ``python -m profiling.sampling`` so that we can

* sample in ``all`` mode once and keep per-sample thread status bits, letting
  the UI switch between wall / CPU / GIL views *after* recording,
* interleave async-aware stacks, task graphs, GC stats, RSS/CPU and child
  process discovery on one clock,
* stream live deltas instead of writing a file at the end.

``_remote_debugging`` is private API. Everything version specific is guarded
here so a change in a future CPython only needs a fix in this file.
"""

from __future__ import annotations

import os
import sys
import threading
import time

try:
    import _remote_debugging as rd
except ImportError:  # pragma: no cover - interpreter too old / unsupported
    rd = None

try:  # reuse Tachyon's own async stack linearisation when available
    from profiling.sampling.collector import iter_async_frames as _iter_async_frames
except Exception:  # pragma: no cover
    _iter_async_frames = None

from .procstats import ProcStats
from .store import Store

MODE_ALL = 3  # profiling.sampling.constants.PROFILING_MODE_ALL


class SamplerError(RuntimeError):
    pass


def check_support():
    if rd is None:
        raise SamplerError(
            "This interpreter has no _remote_debugging module; Python >= 3.15 is required."
        )


def resolve_python_pid(pid: int, timeout: float = 2.0) -> int:
    """On Windows a venv ``python.exe`` is a launcher; profile its child instead."""
    if os.name != "nt" or rd is None:
        return pid
    deadline = time.monotonic() + timeout
    while True:
        try:
            if rd.is_python_process(pid):
                kids = [c for c in rd.get_child_pids(pid, recursive=False) if rd.is_python_process(c)]
                if len(kids) == 1:
                    return kids[0]
                if not kids:
                    return pid
        except (OSError, RuntimeError):
            pass
        if time.monotonic() > deadline:
            return pid
        time.sleep(0.05)


def make_unwinder(pid: int, native: bool, gc: bool):
    check_support()
    attempts = [
        dict(all_threads=True, mode=MODE_ALL, native=native, gc=gc,
             skip_non_matching_threads=False, cache_frames=True),
        dict(all_threads=True, mode=MODE_ALL, native=native, gc=gc),
        dict(all_threads=True),
    ]
    last = None
    for kw in attempts:
        try:
            return rd.RemoteUnwinder(pid, **kw)
        except TypeError as e:  # keyword not supported by this build
            last = e
        except PermissionError as e:
            raise SamplerError(permission_hint(pid, e)) from e
        except RuntimeError as e:
            msg = str(e)
            if "ermission" in msg or "Operation not permitted" in msg:
                raise SamplerError(permission_hint(pid, e)) from e
            raise SamplerError(f"Cannot attach to process {pid}: {msg}") from e
        except ProcessLookupError as e:
            raise SamplerError(f"Process {pid} does not exist") from e
    raise SamplerError(f"Unsupported _remote_debugging API: {last}")


def permission_hint(pid: int, err: BaseException) -> str:
    base = f"Permission denied while attaching to PID {pid} ({err})."
    if sys.platform == "linux":
        scope = ""
        try:
            with open("/proc/sys/kernel/yama/ptrace_scope") as f:
                scope = f.read().strip()
        except OSError:
            pass
        hint = (
            " Linux restricts attaching to non-child processes"
            + (f" (kernel.yama.ptrace_scope={scope})" if scope else "")
            + ". Start the program with the profiler (Run with Profiler / `pyprof run`),"
            " or run `sudo sysctl kernel.yama.ptrace_scope=0`. In containers add `--cap-add=SYS_PTRACE`."
        )
    elif sys.platform == "darwin":
        hint = (
            " macOS only allows reading another process's memory as root."
            " Use 'Attach (elevated)' or start the program with the profiler."
        )
    else:
        hint = " The target probably runs elevated or as another user; run VS Code as Administrator."
    return base + hint


class Sampler(threading.Thread):
    def __init__(self, pid: int, store: Store, *, rate_hz: int = 1000, native=False, gc=True,
                 async_aware=True, blocking=False, on_exit=None, on_children=None):
        super().__init__(name="pyprof-sampler", daemon=True)
        self.pid = resolve_python_pid(pid)
        self.store = store
        self.interval = 1.0 / max(1, rate_hz)
        self.async_aware = async_aware
        self.blocking = blocking and hasattr(rd.RemoteUnwinder, "pause_threads")
        self.on_exit = on_exit
        self.on_children = on_children
        self._stop_ev = threading.Event()
        self.unwinder = make_unwinder(self.pid, native, gc)
        self._async_every = max(1, int(rate_hz // 200))
        self._known_children: set = set()
        self.exit_reason = None
        try:
            self._gc_monitor = rd.GCMonitor(self.pid) if hasattr(rd, "GCMonitor") else None
        except Exception:
            self._gc_monitor = None
        self._gc_seen: set = set()

    def stop(self):
        self._stop_ev.set()

    # ------------------------------------------------------------------ loop
    def run(self):
        store = self.store
        unwinder = self.unwinder
        interval = self.interval
        procstats = ProcStats(self.pid)
        next_t = time.perf_counter()
        n = 0
        last_stats = last_tasks = last_gc = last_kids = 0.0
        last_cpu = None
        rate_window = [0, time.perf_counter()]
        try:
            while not self._stop_ev.is_set():
                now = time.perf_counter()
                if now < next_t:
                    delay = next_t - now
                    if delay > 0.0002:
                        time.sleep(delay * 0.9)
                    continue
                next_t += interval
                if now - next_t > 0.5:  # we fell far behind (suspend, GC...), resync
                    next_t = now + interval
                t = (now - store.t0) * 1000.0
                try:
                    if self.blocking:
                        unwinder.pause_threads()
                        try:
                            trace = unwinder.get_stack_trace()
                        finally:
                            unwinder.resume_threads()
                    else:
                        trace = unwinder.get_stack_trace()
                    store.add_thread_sample(t, trace)
                    n += 1
                    if self.async_aware and _iter_async_frames and n % self._async_every == 0:
                        self._sample_async(t)
                except ProcessLookupError:
                    self.exit_reason = "exited"
                    break
                except (RuntimeError, UnicodeDecodeError, MemoryError, OSError):
                    # torn read of a stack that changed while we read it: discard
                    # (same as Tachyon's "error rate"; use blocking mode to avoid)
                    store.stats["errors"] += 1
                    if not _alive(self.pid):
                        self.exit_reason = "exited"
                        break

                # -- low frequency work ------------------------------------
                if now - last_tasks >= 0.2 and self.async_aware:
                    last_tasks = now
                    self._sample_tasks(t)
                if now - last_stats >= 0.5:
                    last_stats = now
                    r = procstats.read()
                    if r is not None:
                        rss, cpu = r
                        store.add_track("rss", t, rss)
                        if last_cpu is not None and now > last_cpu[0]:
                            pct = 100.0 * (cpu - last_cpu[1]) / (now - last_cpu[0])
                            store.add_track("cpu", t, round(max(0.0, pct), 1))
                        last_cpu = (now, cpu)
                    cnt, t_prev = rate_window
                    if now > t_prev:
                        store.stats["rateHz"] = round((n - cnt) / (now - t_prev), 1)
                    rate_window[:] = [n, now]
                if now - last_gc >= 1.0:
                    last_gc = now
                    self._sample_gc(t)
                if self.on_children and now - last_kids >= 2.0:
                    last_kids = now
                    self._check_children()
        finally:
            procstats.close()
            if self.exit_reason and self.on_exit:
                self.on_exit(self.exit_reason)

    # ----------------------------------------------------------- async/tasks
    def _sample_async(self, t):
        try:
            awaited = self.unwinder.get_async_stack_trace()
        except Exception:
            return
        if awaited:
            self.store.add_async_sample(t, list(_iter_async_frames(awaited)))

    def _sample_tasks(self, t):
        try:
            all_awaited = self.unwinder.get_all_awaited_by()
        except Exception:
            return
        if not any(info.awaited_by for info in all_awaited):
            if not self.store.tasks:
                return
        running = set()
        try:
            for info in self.unwinder.get_async_stack_trace():
                if info.awaited_by:
                    running.add(info.awaited_by[0].task_id)
        except Exception:
            pass
        self.store.update_tasks(t, all_awaited, running)

    # -------------------------------------------------------------------- gc
    def _sample_gc(self, t):
        try:
            if self._gc_monitor is not None:
                stats = self._gc_monitor.get_gc_stats()
            elif hasattr(rd, "get_gc_stats"):
                stats = rd.get_gc_stats(self.pid)
            else:
                return
        except Exception:
            return
        store = self.store
        now_ns = time.perf_counter_ns()
        for s in stats:
            key = (s.gen, s.ts_start, s.collections)
            if key in self._gc_seen:
                continue
            self._gc_seen.add(key)
            ts = store.ns_to_t(s.ts_start)
            # ts_start is CLOCK_MONOTONIC on Linux; if clocks differ, use arrival time
            if s.ts_start <= 0 or s.ts_start > now_ns + 60e9 or ts < -1000:
                ts = t
            if ts < 0:
                continue  # collections from before the session started
            dur = (s.ts_stop - s.ts_start) / 1e6 if s.ts_stop >= s.ts_start else 0.0
            store.add_gc(ts, dur, s.gen, s.collected, getattr(s, "heap_size", 0))
        if len(self._gc_seen) > 10000:
            self._gc_seen = set(list(self._gc_seen)[-2000:])

    # -------------------------------------------------------------- children
    def _check_children(self):
        try:
            kids = rd.get_child_pids(self.pid, recursive=True)
        except Exception:
            return
        new = []
        for k in kids:
            if k in self._known_children:
                continue
            self._known_children.add(k)
            try:
                if rd.is_python_process(k):
                    new.append(k)
            except Exception:
                pass
        if new:
            self.on_children(new)


def _alive(pid: int) -> bool:
    if os.name == "nt":
        try:
            rd.RemoteUnwinder(pid)
            return True
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
