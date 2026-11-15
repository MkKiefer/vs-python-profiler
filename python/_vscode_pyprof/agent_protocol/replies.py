"""What the agent answers to the collector's commands."""

from dataclasses import dataclass, field

from _vscode_pyprof.wire import WireMessage, WireRow, wire


@dataclass(frozen=True)
class TracingStatus(WireMessage):
    """Answer to ``StartTracing`` and ``StopTracing``."""

    tracing: bool
    frames: int | None = None
    """Traceback depth tracemalloc records, while it is tracing."""


@dataclass(frozen=True)
class AsyncioDebugStatus(WireMessage):
    """Answer to ``SetAsyncioDebug``."""

    enabled: bool
    loops: int
    """Event loops the agent knows and switched."""


@dataclass(frozen=True)
class SourceLine(WireRow):
    """One frame of a tracemalloc traceback; sent as ``[file, line]``."""

    filename: str
    line: int


@dataclass(frozen=True)
class Allocation(WireRow):
    """Live memory allocated from one traceback; sent as ``[[[file, line], ...], size, count]``."""

    traceback: list[SourceLine]
    """Oldest frame first, as tracemalloc reports it."""
    size: int
    count: int


@dataclass(frozen=True)
class HeapSnapshot(WireMessage):
    """Answer to ``TakeSnapshot``: the traced allocations grouped by traceback."""

    perf_counter: float = field(metadata=wire("t"))
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
class TypeCount(WireRow):
    """How many live objects of one type exist; sent as ``[type name, count]``."""

    type_name: str
    count: int


@dataclass(frozen=True)
class ObjectCounts(WireMessage):
    """Answer to ``CountObjects``: the most common types among the objects the GC tracks."""

    t: float
    """``time.perf_counter()`` from the agent; session milliseconds once the collector stored it."""
    counts: list[TypeCount]
    """Most common type first."""


@dataclass(frozen=True)
class Pong(WireMessage):
    """Answer to ``Ping``."""

    perf_counter: float = field(metadata=wire("t"))
    pid: int


@dataclass(frozen=True)
class Acknowledgement(WireMessage):
    """Answer to a command that has nothing to report."""

    ok: bool = field(default=True, init=False)
