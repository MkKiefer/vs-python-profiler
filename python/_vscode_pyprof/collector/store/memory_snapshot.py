"""A tracemalloc snapshot as the profile stores it."""

from dataclasses import dataclass

from _vscode_pyprof.wire import JsonObject


@dataclass(frozen=True, slots=True)
class AllocationSite:
    """Live memory allocated from one call stack."""

    stack: int
    size: int
    count: int


@dataclass(frozen=True, slots=True)
class MemorySnapshot:
    """A tracemalloc snapshot grouped by call stack.

    ``sites`` holds the largest call stacks; ``other_size``/``other_count`` sum
    up the ones the agent left out.
    """

    snapshot_id: int
    label: str
    t: float
    total_size: int
    total_count: int
    other_size: int
    other_count: int
    traced: int
    peak: int
    take_ms: float | None
    sites: tuple[AllocationSite, ...]

    def to_wire(self) -> JsonObject:
        return {
            "id": self.snapshot_id,
            "label": self.label,
            "t": self.t,
            "totalSize": self.total_size,
            "totalCount": self.total_count,
            "otherSize": self.other_size,
            "otherCount": self.other_count,
            "traced": self.traced,
            "peak": self.peak,
            "takeMs": self.take_ms,
            "entries": [[site.stack, site.size, site.count] for site in self.sites],
        }
