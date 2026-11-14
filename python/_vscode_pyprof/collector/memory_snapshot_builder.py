"""Turns the agent's heap snapshot into a snapshot of the profile."""

import itertools

from _vscode_pyprof.agent_protocol.replies import Allocation, HeapSnapshot
from _vscode_pyprof.collector.frames.func_resolver import FuncResolver
from _vscode_pyprof.collector.store.memory_snapshot import AllocationSite, MemorySnapshot
from _vscode_pyprof.collector.store.session_clock import SessionClock
from _vscode_pyprof.collector.store.stack_table import SourceFrame
from _vscode_pyprof.collector.store.store import Store


class MemorySnapshotBuilder:
    """Builds ``MemorySnapshot``s whose call stacks live in the store's stack table.

    The agent reports tracebacks as ``(file, line)`` pairs; the function names
    are resolved here, in the collector, to keep the work out of the program.
    """

    def __init__(self, store: Store, clock: SessionClock, resolver: FuncResolver) -> None:
        self._store = store
        self._clock = clock
        self._resolver = resolver
        self._ids = itertools.count(1)

    def build(self, heap: HeapSnapshot, label: str | None) -> MemorySnapshot:
        """``label`` defaults to ``Snapshot <id>``."""
        sites = [site for allocation in heap.top if (site := self._site(allocation)) is not None]
        snapshot_id = next(self._ids)
        return MemorySnapshot(
            snapshot_id=snapshot_id,
            label=label or f"Snapshot {snapshot_id}",
            t=round(self._clock.from_perf_counter(heap.perf_counter), 2),
            total_size=heap.total_size,
            total_count=heap.total_count,
            other_size=heap.other_size,
            other_count=heap.other_count,
            traced=heap.traced,
            peak=heap.peak,
            take_ms=heap.take_ms,
            sites=tuple(sites),
        )

    def _site(self, allocation: Allocation) -> AllocationSite | None:
        """The allocation with its traceback as a stack of the profile; ``None`` if no frame is left."""
        frames = [
            SourceFrame(frame.filename, self._resolver.resolve(frame.filename, frame.line), frame.line)
            for frame in allocation.traceback
        ]
        stack = self._store.intern_traceback(frames)
        if stack == Store.NO_STACK:
            return None  # allocated by the launcher itself
        return AllocationSite(stack, allocation.size, allocation.count)
