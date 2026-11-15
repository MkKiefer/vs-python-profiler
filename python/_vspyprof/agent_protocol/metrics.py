"""The periodic metrics message of an agent."""

from dataclasses import dataclass, field

from _vspyprof.agent_protocol.hello import ThreadName


@dataclass(frozen=True)
class TracedMemory:
    """What tracemalloc currently traces, in bytes."""

    current: int
    peak: int


@dataclass(frozen=True)
class LoopMetrics:
    """One event loop since the previous metrics message."""

    loop_id: int
    thread: str
    """Name of the thread that runs the loop."""
    lag_ms: float
    """The longest a callback had to wait before the loop ran it."""
    tasks: int | None
    """Tasks alive on the loop; ``None`` if they could not be counted this time."""


@dataclass(frozen=True)
class EventDetails:
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


@dataclass(frozen=True)
class AgentEvent:
    """Something the agent observed inside the program (a slow callback, a never-awaited coroutine, …)."""

    kind: str
    """An ``EventKind`` value, or a kind only a newer agent knows."""
    message: str
    perf_counter: float | None = None
    """``time.perf_counter()`` in the target when it happened, if the agent recorded it."""
    details: EventDetails = field(default_factory=EventDetails)


@dataclass(frozen=True)
class AgentMetrics:
    """What changed in the program since the previous metrics message."""

    threads: list[ThreadName]
    traced: TracedMemory | None = None
    """``None`` while tracemalloc is not tracing."""
    loops: list[LoopMetrics] = field(default_factory=list)
    events: list[AgentEvent] = field(default_factory=list)
