"""What the extension sends with its requests.

Mirror of the ``params`` types of ``CollectorRequests`` in ``src/shared/protocol.ts``;
the defaults apply when the extension leaves a key out.
"""

from dataclasses import dataclass, field

from _vscode_pyprof.collector.options import CollectorOptions
from _vscode_pyprof.collector.protocol import StopReason
from _vscode_pyprof.wire import WireMessage


@dataclass(frozen=True, slots=True)
class NoParams(WireMessage):
    """For requests that take no parameters."""


@dataclass(frozen=True, slots=True)
class InitializeParams(WireMessage):
    options: CollectorOptions = field(default_factory=CollectorOptions)
    label: str | None = None
    """What the profile is named after, e.g. the launched script."""


@dataclass(frozen=True, slots=True)
class AttachParams(WireMessage):
    pid: int
    inject: bool = True
    """Inject the in-process agent; sampling works without it."""


@dataclass(frozen=True, slots=True)
class StopParams(WireMessage):
    reason: str = StopReason.USER
    """A ``StopReason`` value or the extension's own reason."""


@dataclass(frozen=True, slots=True)
class TracemallocParams(WireMessage):
    enabled: bool = True
    frames: int | None = None
    """Traceback depth; ``None`` uses the session's ``tracemalloc_frames``."""


@dataclass(frozen=True, slots=True)
class SnapshotParams(WireMessage):
    label: str | None = None
    limit: int = 3000
    """How many of the largest allocations to list."""


@dataclass(frozen=True, slots=True)
class ObjectCountsParams(WireMessage):
    limit: int = 60
    """How many of the most common types to list."""


@dataclass(frozen=True, slots=True)
class AsyncioDebugParams(WireMessage):
    enabled: bool = True
    slow_ms: float | None = None
    """Slow-callback threshold; ``None`` uses the session's ``slow_callback_ms``."""


@dataclass(frozen=True, slots=True)
class MarkParams(WireMessage):
    name: str = "marker"


@dataclass(frozen=True, slots=True)
class SaveParams(WireMessage):
    path: str
