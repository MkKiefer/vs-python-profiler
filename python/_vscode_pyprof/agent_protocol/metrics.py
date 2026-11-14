"""The periodic metrics message of an agent."""

from dataclasses import dataclass, field

from _vscode_pyprof.agent_protocol.hello import ThreadName
from _vscode_pyprof.agent_protocol.names import AgentMessageType, EventKind
from _vscode_pyprof.wire import JsonObject, WireMessage, WireReader


@dataclass(frozen=True)
class TracedMemory:
    """What tracemalloc currently traces, in bytes."""

    current: int
    peak: int


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

    @classmethod
    def from_wire(cls, raw: WireReader) -> LoopMetrics:
        return cls(
            loop_id=raw.get_int("loop", 0),
            thread=raw.get_str("thread", ""),
            lag_ms=raw.get_float("lagMs"),
            tasks=raw.get_int("tasks") if raw.has("tasks") else None,
        )

    def to_wire(self) -> JsonObject:
        return {"loop": self.loop_id, "thread": self.thread, "lagMs": self.lag_ms, "tasks": self.tasks}


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

    @classmethod
    def from_wire(cls, raw: WireReader) -> EventDetails:
        return cls(
            thread=raw.get_optional_str("thread"),
            seconds=raw.get_float("seconds") if raw.has("seconds") else None,
            handle=raw.get_optional_str("handle"),
            file=raw.get_optional_str("file"),
            line=raw.get_int("line") if raw.has("line") else None,
        )

    def to_wire(self) -> JsonObject:
        """Only the fields that are known."""
        fields: JsonObject = {
            "thread": self.thread,
            "seconds": self.seconds,
            "handle": self.handle,
            "file": self.file,
            "line": self.line,
        }
        return {name: value for name, value in fields.items() if value is not None}


@dataclass(frozen=True)
class AgentEvent(WireMessage):
    """Something the agent observed inside the program (a slow callback, a never-awaited coroutine, …)."""

    kind: str
    """An ``EventKind`` value, or a kind only a newer agent knows."""
    message: str
    perf_counter: float | None = None
    """``time.perf_counter()`` in the target when it happened, if the agent recorded it."""
    details: EventDetails = field(default_factory=EventDetails)

    @classmethod
    def from_wire(cls, raw: WireReader) -> AgentEvent:
        return cls(
            kind=raw.get_str("kind", EventKind.ASYNCIO),
            message=raw.get_str("message", ""),
            perf_counter=raw.get_float("t") if raw.has("t") else None,
            details=EventDetails.from_wire(raw),
        )

    def to_wire(self) -> JsonObject:
        wire = self.details.to_wire()
        wire.update(kind=self.kind, message=self.message)
        if self.perf_counter is not None:
            wire["t"] = self.perf_counter
        return wire


@dataclass(frozen=True)
class AgentMetrics(WireMessage):
    """What changed in the program since the previous metrics message."""

    threads: list[ThreadName]
    traced: TracedMemory | None = None
    """``None`` while tracemalloc is not tracing."""
    loops: list[LoopMetrics] = field(default_factory=list)
    events: list[AgentEvent] = field(default_factory=list)

    @classmethod
    def from_wire(cls, message: WireReader) -> AgentMetrics:
        traced = (
            TracedMemory(message.get_int("traced"), message.get_int("tracedPeak")) if message.has("traced") else None
        )
        return cls(
            threads=ThreadName.list_from_wire(message.get_list("threads")),
            traced=traced,
            loops=[LoopMetrics.from_wire(WireReader.of(loop)) for loop in message.get_list("loops")],
            events=[
                AgentEvent.from_wire(WireReader.of(event))
                for event in message.get_list("events")
                if isinstance(event, dict)
            ],
        )

    def to_wire(self) -> JsonObject:
        wire: JsonObject = {
            "type": AgentMessageType.METRICS,
            "threads": [thread.to_wire() for thread in self.threads],
            "loops": [loop.to_wire() for loop in self.loops],
            "events": [event.to_wire() for event in self.events],
        }
        if self.traced is not None:
            wire["traced"] = self.traced.current
            wire["tracedPeak"] = self.traced.peak
        return wire
