"""Something worth showing on the timeline of a profile."""

from dataclasses import dataclass, field

from _vscode_pyprof.agent_protocol.metrics import EventDetails
from _vscode_pyprof.wire import JsonObject, WireMessage


@dataclass(frozen=True, slots=True)
class TimelineEvent(WireMessage):
    t: float
    """Session milliseconds."""
    kind: str
    """An ``EventKind`` value, or a kind only a newer agent knows."""
    message: str
    details: EventDetails = field(default_factory=EventDetails)

    def to_wire(self) -> JsonObject:
        wire = self.details.to_wire()
        wire.update(t=self.t, kind=self.kind, message=self.message)
        return wire
