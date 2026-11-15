"""The periodic metrics message of an agent."""

from dataclasses import dataclass, field

# annotations only: loading ``typing`` into the profiled program is not worth a Self
lazy from typing import Self

from _vscode_pyprof.agent_protocol.hello import ThreadName
from _vscode_pyprof.agent_protocol.names import AgentMessageType
from _vscode_pyprof.wire import JsonObject, WireMessage, WireReader


@dataclass(frozen=True)
class TracedMemory(WireMessage):
    """What tracemalloc currently traces, in bytes."""

    current: int
    peak: int

    def to_wire(self) -> JsonObject:
        return {"current": self.current, "peak": self.peak}

    @classmethod
    def from_wire(cls, raw: object, where: str = "$") -> Self:
        message = WireReader.for_object(raw, where)
        return cls(current=message.get("current", int), peak=message.get("peak", int))


@dataclass(frozen=True)
class LoopMetrics(WireMessage):
    """One event loop since the previous metrics message."""

    loop_id: int
    thread: str
    """Name of the thread that runs the loop."""
    lag_ms: float
    """The longest a callback had to wait before the loop ran it."""
    tasks: int | None
    """Tasks alive on the loop; ``None`` if they could not be counted this time."""

    def to_wire(self) -> JsonObject:
        return self._omit_none({"loop": self.loop_id, "thread": self.thread, "lagMs": self.lag_ms, "tasks": self.tasks})

    @classmethod
    def from_wire(cls, raw: object, where: str = "$") -> Self:
        message = WireReader.for_object(raw, where)
        return cls(
            loop_id=message.get("loop", int),
            thread=message.get("thread", str),
            lag_ms=message.get("lagMs", float),
            tasks=message.get_or("tasks", int, None),
        )


@dataclass(frozen=True)
class EventDetails(WireMessage):
    """What is known about an event beyond its kind and message; every field is optional."""

    thread: str | None = None
    """Name of the thread the event happened on."""
    seconds: float | None = None
    """How long a slow callback ran."""
    handle: str | None = None
    """The slow callback, as asyncio describes it."""
    file: str | None = None
    """Where a never-awaited coroutine was created."""
    line: int | None = None

    def to_wire(self) -> JsonObject:
        return self._omit_none(
            {
                "thread": self.thread,
                "seconds": self.seconds,
                "handle": self.handle,
                "file": self.file,
                "line": self.line,
            }
        )

    @classmethod
    def from_wire(cls, raw: object, where: str = "$") -> Self:
        message = WireReader.for_object(raw, where)
        return cls(
            thread=message.get_or("thread", str, None),
            seconds=message.get_or("seconds", float, None),
            handle=message.get_or("handle", str, None),
            file=message.get_or("file", str, None),
            line=message.get_or("line", int, None),
        )


@dataclass(frozen=True)
class AgentEvent(WireMessage):
    """Something the agent observed inside the program (a slow callback, a never-awaited coroutine, …)."""

    kind: str
    """An ``EventKind`` value, or a kind only a newer agent knows."""
    message: str
    perf_counter: float | None = None
    """``time.perf_counter()`` in the target when it happened, if the agent recorded it."""
    details: EventDetails = field(default_factory=EventDetails)

    def to_wire(self) -> JsonObject:
        return self._omit_none(
            {"kind": self.kind, "message": self.message, "t": self.perf_counter, "details": self.details.to_wire()}
        )

    @classmethod
    def from_wire(cls, raw: object, where: str = "$") -> Self:
        message = WireReader.for_object(raw, where)
        return cls(
            kind=message.get("kind", str),
            message=message.get("message", str),
            perf_counter=message.get_or("t", float, None),
            details=message.get_or("details", EventDetails, EventDetails()),
        )


@dataclass(frozen=True)
class AgentMetrics(WireMessage):
    """What changed in the program since the previous metrics message."""

    threads: list[ThreadName]
    traced: TracedMemory | None = None
    """``None`` while tracemalloc is not tracing."""
    loops: list[LoopMetrics] = field(default_factory=list)
    events: list[AgentEvent] = field(default_factory=list)

    def to_wire(self) -> JsonObject:
        return self._omit_none(
            {
                "type": AgentMessageType.METRICS,
                "threads": [thread.to_wire() for thread in self.threads],
                "traced": self.traced.to_wire() if self.traced is not None else None,
                "loops": [loop.to_wire() for loop in self.loops],
                "events": [event.to_wire() for event in self.events],
            }
        )

    @classmethod
    def from_wire(cls, raw: object, where: str = "$") -> Self:
        message = WireReader.for_object(raw, where)
        message.require_type(AgentMessageType.METRICS)
        return cls(
            threads=message.list_of("threads", ThreadName),
            traced=message.get_or("traced", TracedMemory, None),
            loops=message.list_or("loops", LoopMetrics, []),
            events=message.list_or("events", AgentEvent, []),
        )
