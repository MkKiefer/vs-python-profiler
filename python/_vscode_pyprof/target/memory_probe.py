"""Reads what the profiled program holds in memory."""

import os
import sys
import time
lazy import gc
lazy import tracemalloc
lazy from collections import Counter

from _vscode_pyprof.wire import JsonObject


class MemoryProbe:
    """tracemalloc control and snapshots, and live object counts by type.

    ``tracemalloc`` and ``gc`` load on first use, never into a program that
    does not ask for memory profiling.
    """

    # The agent's code is everything in this package except the launcher: launcher frames
    # sit at the root of every traceback of a program started with the profiler.
    _AGENT_CODE_PREFIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "")
    _LAUNCHER_FILE = os.path.join(_AGENT_CODE_PREFIX, "launcher.py")

    def __init__(self) -> None:
        self._started_tracing = False

    def start_tracing(self, frames: int) -> JsonObject:
        if not tracemalloc.is_tracing():
            tracemalloc.start(frames)
            self._started_tracing = True
        return {"tracing": True, "frames": tracemalloc.get_traceback_limit()}

    def stop_tracing(self) -> JsonObject:
        tracemalloc.stop()
        self._started_tracing = False
        return {"tracing": False}

    def release(self) -> None:
        """Stop tracing if this probe started it; tracing the program started itself is left alone."""
        if self._started_tracing:
            self.stop_tracing()

    def traced_memory(self) -> tuple[int, int] | None:
        """``(current, peak)`` bytes while tracing, otherwise ``None``."""
        # `in sys.modules` first: never load tracemalloc into a program that does not use it
        if "tracemalloc" in sys.modules and tracemalloc.is_tracing():
            return tracemalloc.get_traced_memory()
        return None

    def snapshot(self, limit: int) -> JsonObject:
        """Live allocations grouped by traceback, the ``limit`` largest in detail."""
        if not tracemalloc.is_tracing():
            raise RuntimeError("tracemalloc is not running; start memory tracing first")
        # A snapshot is stop-the-world anyway; hold the GIL longer so a busy
        # program does not stretch a 1s snapshot into 10s of contention.
        switch_interval = sys.getswitchinterval()
        sys.setswitchinterval(1.0)
        try:
            return self._snapshot(limit)
        finally:
            sys.setswitchinterval(switch_interval)

    def object_counts(self, limit: int) -> JsonObject:
        """The ``limit`` most common types among the objects the garbage collector tracks."""
        counts: Counter[str] = Counter()
        for obj in gc.get_objects():
            cls = type(obj)
            counts[cls.__qualname__ if cls.__module__ == "builtins" else f"{cls.__module__}.{cls.__qualname__}"] += 1
        return {"t": time.perf_counter(), "counts": counts.most_common(limit)}

    def _snapshot(self, limit: int) -> JsonObject:
        started = time.perf_counter()
        # Filter after grouping: Snapshot.filter_traces() runs fnmatch per trace
        # in Python and dominates snapshot time on large heaps.
        statistics = [
            statistic
            for statistic in tracemalloc.take_snapshot().statistics("traceback")
            if not self._is_own_allocation(statistic.traceback)
        ]
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

    @classmethod
    def _is_own_allocation(cls, traceback: tracemalloc.Traceback) -> bool:
        """Allocated by tracemalloc itself or anywhere inside the agent."""
        if len(traceback) and traceback[-1].filename == tracemalloc.__file__:
            return True
        return any(
            frame.filename.startswith(cls._AGENT_CODE_PREFIX) and frame.filename != cls._LAUNCHER_FILE
            for frame in traceback
        )
