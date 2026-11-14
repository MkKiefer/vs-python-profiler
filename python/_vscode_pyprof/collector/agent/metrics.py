"""The periodic metrics message of an agent."""

from dataclasses import dataclass

from _vscode_pyprof.agent_protocol import EventKind
from _vscode_pyprof.collector.agent.thread_name import ThreadName
from _vscode_pyprof.wire import JsonObject, WireReader


@dataclass(frozen=True, slots=True)
class LoopMetrics:
    """One event loop since the previous metrics message."""

    lag_ms: float
    tasks: int | None


@dataclass(frozen=True, slots=True)
class AgentEvent:
    """Something the agent observed inside the program (a slow callback, a never-awaited coroutine, …)."""

    kind: str
    """An ``EventKind`` value, or a kind a newer agent knows."""
    message: str
    perf_counter: float | None
    """``time.perf_counter()`` in the target when it happened, if the agent recorded it."""
    extra: JsonObject

    @classmethod
    def from_wire(cls, raw: WireReader) -> AgentEvent:
        fields = raw.to_dict()
        t = fields.pop("t", None)
        return cls(
            kind=str(fields.pop("kind", EventKind.ASYNCIO)),
            message=str(fields.pop("message", "")),
            perf_counter=float(t) if isinstance(t, (int, float)) else None,
            extra=fields,
        )


@dataclass(frozen=True, slots=True)
class AgentMetrics:
    threads: list[ThreadName]
    traced: int | None
    """Bytes tracemalloc currently traces; ``None`` while it is not tracing."""
    traced_peak: int | None
    loops: list[LoopMetrics]
    events: list[AgentEvent]

    @classmethod
    def from_wire(cls, message: WireReader) -> AgentMetrics:
        tracing = message.has("traced")
        loops = [WireReader.of(loop) for loop in message.get_list("loops")]
        return cls(
            threads=ThreadName.list_from_wire(message.get_list("threads")),
            traced=message.get_int("traced") if tracing else None,
            traced_peak=message.get_int("tracedPeak") if tracing else None,
            loops=[
                LoopMetrics(loop.get_float("lagMs"), loop.get_int("tasks") if loop.has("tasks") else None)
                for loop in loops
            ],
            events=[
                AgentEvent.from_wire(WireReader.of(event))
                for event in message.get_list("events")
                if isinstance(event, dict)
            ],
        )
