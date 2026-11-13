"""Plain data records kept by the profile store."""

from dataclasses import dataclass, field

from _vscode_pyprof.wire import JsonObject


@dataclass(slots=True)
class TaskRecord:
    """One asyncio task as seen from outside the process (mutable: tasks change state)."""

    task_id: int
    name: str
    parent: int | None
    thread: int
    start: float
    stack: int
    state: str
    end: float | None = None

    def to_wire(self) -> JsonObject:
        return {
            "id": self.task_id,
            "name": self.name,
            "parent": self.parent,
            "thread": self.thread,
            "start": self.start,
            "end": self.end,
            "stack": self.stack,
            "state": self.state,
        }


@dataclass(frozen=True, slots=True)
class AllocationSite:
    """Live memory allocated from one call stack."""

    stack: int
    size: int
    count: int


@dataclass(frozen=True, slots=True)
class MemorySnapshot:
    """A tracemalloc snapshot grouped by call stack."""

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


@dataclass(slots=True)
class SampleColumns:
    """Columnar sample table: one entry per (timestamp, thread)."""

    t: list[float] = field(default_factory=list)
    tid: list[int] = field(default_factory=list)
    stack: list[int] = field(default_factory=list)
    status: list[int] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.t)

    def append(self, t: float, tid: int, stack: int, status: int) -> None:
        self.t.append(t)
        self.tid.append(tid)
        self.stack.append(stack)
        self.status.append(status)

    def to_wire(self, start: int = 0) -> JsonObject:
        return {
            "t": self.t[start:],
            "tid": self.tid[start:],
            "stack": self.stack[start:],
            "status": self.status[start:],
        }
