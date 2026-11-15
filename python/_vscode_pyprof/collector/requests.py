"""What the extension asks the collector to do, each as the ``body`` of a ``wire.Request``.

Mirror of ``CollectorRequests`` in ``src/shared/protocol.ts``; the class name is
the request's ``"type"``, the defaults apply when the extension leaves a key out.
The result each one is answered with is named in its docstring.
"""

from dataclasses import dataclass, field

from _vscode_pyprof.collector.options import CollectorOptions
from _vscode_pyprof.collector.protocol import StopReason


@dataclass(frozen=True, slots=True)
class Initialize:
    """Start the session; answered with an ``InitializeResult``."""

    options: CollectorOptions = field(default_factory=CollectorOptions)
    label: str | None = None
    """What the profile is named after, e.g. the launched script."""


@dataclass(frozen=True, slots=True)
class Attach:
    """Start sampling a running process; answered with an ``AttachResult``."""

    pid: int
    inject: bool = True
    """Inject the in-process agent; sampling works without it."""


@dataclass(frozen=True, slots=True)
class Stop:
    """Stop sampling; answered with ``None``."""

    reason: str = StopReason.USER
    """A ``StopReason`` value or the extension's own reason."""


@dataclass(frozen=True, slots=True)
class GetStatus:
    """Answered with a ``StatusResult``."""


@dataclass(frozen=True, slots=True)
class SetTracemalloc:
    """Switch tracemalloc in the target; answered with a ``TracingStatus``."""

    enabled: bool = True
    frames: int | None = None
    """Traceback depth; ``None`` uses the session's ``tracemalloc_frames``."""


@dataclass(frozen=True, slots=True)
class TakeSnapshot:
    """Take a memory snapshot and store it in the profile; answered with a ``SnapshotResult``."""

    label: str | None = None
    limit: int = 3000
    """How many of the largest allocations to list."""


@dataclass(frozen=True, slots=True)
class CountObjects:
    """Count the target's objects by type and store the counts; answered with ``ObjectCounts``."""

    limit: int = 60
    """How many of the most common types to list."""


@dataclass(frozen=True, slots=True)
class SetAsyncioDebug:
    """Switch asyncio debug mode in the target; answered with an ``AsyncioDebugStatus``."""

    enabled: bool = True
    slow_ms: float | None = None
    """Slow-callback threshold; ``None`` uses the session's ``slow_callback_ms``."""


@dataclass(frozen=True, slots=True)
class Mark:
    """Drop a marker on the timeline; answered with ``None``."""

    name: str = "marker"


@dataclass(frozen=True, slots=True)
class Save:
    """Write the profile to a ``.pyprof`` file; answered with a ``SaveResult``."""

    path: str


@dataclass(frozen=True, slots=True)
class Shutdown:
    """End the session; answered with ``None``, then the collector exits."""
