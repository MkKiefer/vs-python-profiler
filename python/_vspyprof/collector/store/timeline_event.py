"""Something worth showing on the timeline of a profile."""

from dataclasses import dataclass, field

from _vspyprof.agent_protocol.metrics import EventDetails
from _vspyprof.wire import JsonObject


@dataclass(frozen=True, slots=True)
class TimelineEvent:
    t: float
    """Session milliseconds."""
    kind: str
    """An ``EventKind`` value, or a kind only a newer agent knows."""
    message: str
    details: EventDetails = field(default_factory=EventDetails)

    def to_profile(self) -> JsonObject:
        """The event with its known details next to ``t``, ``kind`` and ``message``."""
        details = self.details
        known: JsonObject = {
            "thread": details.thread,
            "seconds": details.seconds,
            "handle": details.handle,
            "file": details.file,
            "line": details.line,
        }
        event: JsonObject = {key: value for key, value in known.items() if value is not None}
        event.update(t=self.t, kind=self.kind, message=self.message)
        return event
