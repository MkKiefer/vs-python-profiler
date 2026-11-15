"""What the agent answers to the collector's commands."""

from dataclasses import dataclass

# annotations only: loading ``typing`` into the profiled program is not worth a Self
lazy from typing import Self

from _vscode_pyprof.wire import JsonObject, WireMessage, WireReader


@dataclass(frozen=True)
class TracingStatus(WireMessage):
    """Answer to ``StartTracing`` and ``StopTracing``."""

    tracing: bool
    frames: int | None = None
    """Traceback depth tracemalloc records, while it is tracing."""

    def to_wire(self) -> JsonObject:
        return self._omit_none({"tracing": self.tracing, "frames": self.frames})

    @classmethod
    def from_wire(cls, raw: object, where: str = "$") -> Self:
        message = WireReader.for_object(raw, where)
        return cls(tracing=message.get("tracing", bool), frames=message.get_or("frames", int, None))


@dataclass(frozen=True)
class AsyncioDebugStatus(WireMessage):
    """Answer to ``SetAsyncioDebug``."""

    enabled: bool
    loops: int
    """Event loops the agent knows and switched."""

    def to_wire(self) -> JsonObject:
        return {"enabled": self.enabled, "loops": self.loops}

    @classmethod
    def from_wire(cls, raw: object, where: str = "$") -> Self:
        message = WireReader.for_object(raw, where)
        return cls(enabled=message.get("enabled", bool), loops=message.get("loops", int))


@dataclass(frozen=True)
class SourceLine(WireMessage):
    """One frame of a tracemalloc traceback; sent as ``[file, line]``."""

    filename: str
    line: int

    def to_wire(self) -> list[object]:
        return [self.filename, self.line]

    @classmethod
    def from_wire(cls, raw: object, where: str = "$") -> Self:
        row = WireReader.for_row(raw, where, ("filename", "line"))
        return cls(filename=row.get("filename", str), line=row.get("line", int))


@dataclass(frozen=True)
class Allocation(WireMessage):
    """Live memory allocated from one traceback; sent as ``[[[file, line], ...], size, count]``."""

    traceback: list[SourceLine]
    """Oldest frame first, as tracemalloc reports it."""
    size: int
    count: int

    def to_wire(self) -> list[object]:
        return [[frame.to_wire() for frame in self.traceback], self.size, self.count]

    @classmethod
    def from_wire(cls, raw: object, where: str = "$") -> Self:
        row = WireReader.for_row(raw, where, ("traceback", "size", "count"))
        return cls(
            traceback=row.list_of("traceback", SourceLine), size=row.get("size", int), count=row.get("count", int)
        )


@dataclass(frozen=True)
class HeapSnapshot(WireMessage):
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

    def to_wire(self) -> JsonObject:
        return self._omit_none(
            {
                "t": self.perf_counter,
                "totalSize": self.total_size,
                "totalCount": self.total_count,
                "otherSize": self.other_size,
                "otherCount": self.other_count,
                "traced": self.traced,
                "peak": self.peak,
                "takeMs": self.take_ms,
                "top": [allocation.to_wire() for allocation in self.top],
            }
        )

    @classmethod
    def from_wire(cls, raw: object, where: str = "$") -> Self:
        message = WireReader.for_object(raw, where)
        return cls(
            perf_counter=message.get("t", float),
            total_size=message.get("totalSize", int),
            total_count=message.get("totalCount", int),
            other_size=message.get("otherSize", int),
            other_count=message.get("otherCount", int),
            traced=message.get("traced", int),
            peak=message.get("peak", int),
            take_ms=message.get_or("takeMs", float, None),
            top=message.list_of("top", Allocation),
        )


@dataclass(frozen=True)
class TypeCount(WireMessage):
    """How many live objects of one type exist; sent as ``[type name, count]``."""

    type_name: str
    count: int

    def to_wire(self) -> list[object]:
        return [self.type_name, self.count]

    @classmethod
    def from_wire(cls, raw: object, where: str = "$") -> Self:
        row = WireReader.for_row(raw, where, ("typeName", "count"))
        return cls(type_name=row.get("typeName", str), count=row.get("count", int))


@dataclass(frozen=True)
class ObjectCounts(WireMessage):
    """Answer to ``CountObjects``: the most common types among the objects the GC tracks."""

    t: float
    """``time.perf_counter()`` from the agent; session milliseconds once the collector stored it."""
    counts: list[TypeCount]
    """Most common type first."""

    def to_wire(self) -> JsonObject:
        return {"t": self.t, "counts": [count.to_wire() for count in self.counts]}

    @classmethod
    def from_wire(cls, raw: object, where: str = "$") -> Self:
        message = WireReader.for_object(raw, where)
        return cls(t=message.get("t", float), counts=message.list_of("counts", TypeCount))


@dataclass(frozen=True)
class Pong(WireMessage):
    """Answer to ``Ping``."""

    perf_counter: float
    pid: int

    def to_wire(self) -> JsonObject:
        return {"t": self.perf_counter, "pid": self.pid}

    @classmethod
    def from_wire(cls, raw: object, where: str = "$") -> Self:
        message = WireReader.for_object(raw, where)
        return cls(perf_counter=message.get("t", float), pid=message.get("pid", int))


@dataclass(frozen=True)
class Acknowledgement(WireMessage):
    """Answer to a command that has nothing to report; sent as ``{"ok": true}``."""

    def to_wire(self) -> JsonObject:
        return {"ok": True}

    @classmethod
    def from_wire(cls, raw: object, where: str = "$") -> Self:
        WireReader.for_object(raw, where)
        return cls()
