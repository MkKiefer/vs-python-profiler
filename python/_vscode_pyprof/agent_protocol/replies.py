"""What the agent answers to the collector's commands."""

from dataclasses import dataclass

from _vscode_pyprof.wire import JsonObject, WireError, WireMessage, WireReader


@dataclass(frozen=True)
class TracingStatus(WireMessage):
    """Answer to ``TRACEMALLOC_START`` and ``TRACEMALLOC_STOP``."""

    tracing: bool
    frames: int | None = None
    """Traceback depth tracemalloc records, while it is tracing."""

    @classmethod
    def from_wire(cls, raw: WireReader) -> TracingStatus:
        return cls(raw.get_bool("tracing", False), raw.get_int("frames") if raw.has("frames") else None)

    def to_wire(self) -> JsonObject:
        wire: JsonObject = {"tracing": self.tracing}
        if self.frames is not None:
            wire["frames"] = self.frames
        return wire


@dataclass(frozen=True)
class AsyncioDebugStatus(WireMessage):
    """Answer to ``ASYNCIO_DEBUG``."""

    enabled: bool
    loops: int
    """Event loops the agent knows and switched."""

    @classmethod
    def from_wire(cls, raw: WireReader) -> AsyncioDebugStatus:
        return cls(raw.get_bool("enabled", False), raw.get_int("loops", 0))

    def to_wire(self) -> JsonObject:
        return {"enabled": self.enabled, "loops": self.loops}


@dataclass(frozen=True)
class SourceLine:
    """One frame of a tracemalloc traceback; sent as ``[file, line]``."""

    filename: str
    line: int


@dataclass(frozen=True)
class Allocation:
    """Live memory allocated from one traceback; sent as ``[[[file, line], ...], size, count]``."""

    traceback: list[SourceLine]
    """Oldest frame first, as tracemalloc reports it."""
    size: int
    count: int

    @classmethod
    def from_wire(cls, raw: object) -> Allocation:
        """Raises ``WireError`` if ``raw`` has another shape."""
        if not isinstance(raw, list) or len(raw) != 3:
            raise WireError(f"an allocation must be [traceback, size, count], got {raw!r}")
        raw_traceback, size, count = raw
        if not isinstance(raw_traceback, list) or not isinstance(size, int) or not isinstance(count, int):
            raise WireError(f"an allocation must be [traceback, size, count], got {raw!r}")
        traceback = [
            SourceLine(str(frame[0]), int(frame[1]))
            for frame in raw_traceback
            if isinstance(frame, list) and len(frame) == 2 and isinstance(frame[1], int)
        ]
        return cls(traceback, size, count)

    def to_wire(self) -> list[object]:
        return [[[frame.filename, frame.line] for frame in self.traceback], self.size, self.count]


@dataclass(frozen=True)
class HeapSnapshot(WireMessage):
    """Answer to ``SNAPSHOT``: the traced allocations grouped by traceback."""

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

    @classmethod
    def from_wire(cls, raw: WireReader) -> HeapSnapshot:
        return cls(
            perf_counter=raw.get_float("t"),
            total_size=raw.get_int("totalSize"),
            total_count=raw.get_int("totalCount"),
            other_size=raw.get_int("otherSize"),
            other_count=raw.get_int("otherCount"),
            traced=raw.get_int("traced"),
            peak=raw.get_int("peak"),
            take_ms=raw.get_float("takeMs") if raw.has("takeMs") else None,
            top=[Allocation.from_wire(entry) for entry in raw.get_list("top")],
        )

    def to_wire(self) -> JsonObject:
        return {
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


@dataclass(frozen=True)
class TypeCount:
    """How many live objects of one type exist; sent as ``[type name, count]``."""

    type_name: str
    count: int


@dataclass(frozen=True)
class ObjectCounts(WireMessage):
    """Answer to ``OBJECT_COUNTS``: the most common types among the objects the GC tracks."""

    t: float
    """``time.perf_counter()`` from the agent; session milliseconds once the collector stored it."""
    counts: list[TypeCount]
    """Most common type first."""

    @classmethod
    def from_wire(cls, raw: WireReader) -> ObjectCounts:
        counts = [
            TypeCount(str(entry[0]), entry[1])
            for entry in raw.get_list("counts")
            if isinstance(entry, list) and len(entry) == 2 and isinstance(entry[1], int)
        ]
        return cls(raw.get_float("t"), counts)

    def to_wire(self) -> JsonObject:
        return {"t": self.t, "counts": [[entry.type_name, entry.count] for entry in self.counts]}


@dataclass(frozen=True)
class Pong(WireMessage):
    """Answer to ``PING``."""

    perf_counter: float
    pid: int

    def to_wire(self) -> JsonObject:
        return {"t": self.perf_counter, "pid": self.pid}


@dataclass(frozen=True)
class Acknowledgement(WireMessage):
    """Answer to a command that has nothing to report."""

    def to_wire(self) -> JsonObject:
        return {"ok": True}
