"""What the agent answers to the collector's commands (the ``result`` of a ``Response``)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class TracingStatus:
    """Answer to ``StartTracing`` and ``StopTracing``."""

    tracing: bool
    frames: int | None = None
    """Traceback depth tracemalloc records, while it is tracing."""


@dataclass(frozen=True)
class AsyncioDebugStatus:
    """Answer to ``SetAsyncioDebug``."""

    enabled: bool
    loops: int
    """Event loops the agent knows and switched."""


@dataclass(frozen=True)
class SourceLine:
    """One frame of a tracemalloc traceback."""

    filename: str
    line: int


@dataclass(frozen=True)
class Allocation:
    """Live memory allocated from one traceback."""

    traceback: list[SourceLine]
    """Oldest frame first, as tracemalloc reports it."""
    size: int
    count: int


@dataclass(frozen=True)
class HeapSnapshot:
    """Answer to ``TakeSnapshot``: the traced allocations grouped by traceback."""

    perf_counter: float
    """``time.perf_counter()`` in the target when the snapshot was taken."""
    total_size: int
    total_count: int
    other_size: int
    """Bytes of the allocations that are not listed in ``top``."""
    other_count: int
    traced: int
    peak: int
    take_ms: float | None
    """How long the program was paused for the snapshot."""
    top: list[Allocation]
    """The largest allocations."""


@dataclass(frozen=True)
class TypeCount:
    """How many live objects of one type exist."""

    type_name: str
    count: int


@dataclass(frozen=True)
class ObjectCounts:
    """Answer to ``CountObjects``: the most common types among the objects the GC tracks."""

    t: float
    """``time.perf_counter()`` from the agent; session milliseconds once the collector stored it."""
    counts: list[TypeCount]
    """Most common type first."""


@dataclass(frozen=True)
class Pong:
    """Answer to ``Ping``."""

    perf_counter: float
    pid: int
