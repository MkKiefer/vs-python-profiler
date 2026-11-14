"""Turns the agent's answer to a snapshot request into a stored snapshot."""

import itertools

from _vscode_pyprof.collector.frames.func_resolver import FuncResolver
from _vscode_pyprof.collector.store.memory_snapshot import AllocationSite, MemorySnapshot
from _vscode_pyprof.collector.store.session_clock import SessionClock
from _vscode_pyprof.collector.store.stack_table import FrameKey
from _vscode_pyprof.collector.store.store import Store
from _vscode_pyprof.wire import WireReader


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

    def build(self, reply: WireReader, label: str | None) -> MemorySnapshot:
        """``reply`` is the agent's snapshot result; ``label`` defaults to ``Snapshot <id>``."""
        sites = [site for entry in reply.get_list("top") if (site := self._site(entry)) is not None]
        snapshot_id = next(self._ids)
        return MemorySnapshot(
            snapshot_id=snapshot_id,
            label=label or f"Snapshot {snapshot_id}",
            t=round(self._clock.from_perf_counter(reply.get_float("t")), 2),
            total_size=reply.get_int("totalSize"),
            total_count=reply.get_int("totalCount"),
            other_size=reply.get_int("otherSize"),
            other_count=reply.get_int("otherCount"),
            traced=reply.get_int("traced"),
            peak=reply.get_int("peak"),
            take_ms=reply.get_float("takeMs") if reply.has("takeMs") else None,
            sites=tuple(sites),
        )

    def _site(self, entry: object) -> AllocationSite | None:
        """Read one ``[[[file, line], ...] oldest first, size, count]`` entry; ``None`` if it is unusable."""
        if not isinstance(entry, list) or len(entry) != 3:
            return None
        raw_frames, size, count = entry
        if not isinstance(raw_frames, list) or not isinstance(size, int) or not isinstance(count, int):
            return None
        frames: list[FrameKey] = []
        for raw_frame in raw_frames:
            if isinstance(raw_frame, list) and len(raw_frame) == 2:
                filename, line = str(raw_frame[0]), int(raw_frame[1])
                frames.append((filename, self._resolver.resolve(filename, line), line))
        stack = self._store.intern_traceback(frames)
        if stack == Store.NO_STACK:
            return None  # allocated by the launcher itself
        return AllocationSite(stack, size, count)
