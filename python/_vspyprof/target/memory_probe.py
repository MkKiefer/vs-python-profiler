"""Reads what the profiled program holds in memory."""

import os
import sys
import time
lazy import gc
lazy import tracemalloc
lazy from collections import Counter

from _vspyprof.agent_protocol.metrics import TracedMemory
from _vspyprof.agent_protocol.replies import (
    Allocation,
    HeapSnapshot,
    ObjectCounts,
    SourceLine,
    TracingStatus,
    TypeCount,
)


class MemoryProbe:
    """tracemalloc control and snapshots, and live object counts by type.

    ``tracemalloc`` and ``gc`` load on first use, never into a program that
    does not ask for memory profiling.
    """

    # The agent's code is the whole profiler package (target/, but also wire.py and agent_protocol/,
    # whose frames may be all that is left of a traceback cut at the frame limit) except the launcher:
    # launcher frames sit at the root of every traceback of a program started with the profiler.
    _TARGET_DIR = os.path.dirname(os.path.abspath(__file__))
    _AGENT_CODE_PREFIX = os.path.join(os.path.dirname(_TARGET_DIR), "")
    _LAUNCHER_FILE = os.path.join(_TARGET_DIR, "launcher.py")

    def __init__(self) -> None:
        self._started_tracing = False

    def start_tracing(self, frames: int) -> TracingStatus:
        """Start tracemalloc recording ``frames`` frames per allocation, unless the program already traces."""
        if not tracemalloc.is_tracing():
            tracemalloc.start(frames)
            self._started_tracing = True
        return TracingStatus(tracing=True, frames=tracemalloc.get_traceback_limit())

    def stop_tracing(self) -> TracingStatus:
        tracemalloc.stop()
        self._started_tracing = False
        return TracingStatus(tracing=False)

    def release(self) -> None:
        """Stop tracing if this probe started it; tracing the program started itself is left alone."""
        if self._started_tracing:
            self.stop_tracing()

    def traced_memory(self) -> TracedMemory | None:
        """What tracemalloc traces right now; ``None`` while it is not tracing."""
        # `in sys.modules` first: never load tracemalloc into a program that does not use it
        if "tracemalloc" in sys.modules and tracemalloc.is_tracing():
            current, peak = tracemalloc.get_traced_memory()
            return TracedMemory(current, peak)
        return None

    def snapshot(self, limit: int) -> HeapSnapshot:
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

    def object_counts(self, limit: int) -> ObjectCounts:
        """The ``limit`` most common types among the objects the garbage collector tracks."""
        counts: Counter[str] = Counter()
        for obj in gc.get_objects():
            cls = type(obj)
            counts[cls.__qualname__ if cls.__module__ == "builtins" else f"{cls.__module__}.{cls.__qualname__}"] += 1
        most_common = [TypeCount(type_name, count) for type_name, count in counts.most_common(limit)]
        return ObjectCounts(time.perf_counter(), most_common)

    def _snapshot(self, limit: int) -> HeapSnapshot:
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
        return HeapSnapshot(
            perf_counter=started,
            total_size=sum(statistic.size for statistic in statistics),
            total_count=sum(statistic.count for statistic in statistics),
            other_size=sum(statistic.size for statistic in rest),
            other_count=sum(statistic.count for statistic in rest),
            traced=current,
            peak=peak,
            take_ms=round((time.perf_counter() - started) * 1000, 1),
            top=[self._allocation(statistic) for statistic in top],
        )

    @staticmethod
    def _allocation(statistic: tracemalloc.Statistic) -> Allocation:
        # frames oldest first, as tracemalloc reports them
        traceback = [SourceLine(frame.filename, frame.lineno) for frame in statistic.traceback]
        return Allocation(traceback, statistic.size, statistic.count)

    @classmethod
    def _is_own_allocation(cls, traceback: tracemalloc.Traceback) -> bool:
        """Allocated by tracemalloc itself or anywhere inside the agent."""
        if len(traceback) and traceback[-1].filename == tracemalloc.__file__:
            return True
        return any(
            frame.filename.startswith(cls._AGENT_CODE_PREFIX) and frame.filename != cls._LAUNCHER_FILE
            for frame in traceback
        )
