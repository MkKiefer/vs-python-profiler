"""What the extension sends with its requests.

Mirror of the ``params`` types of ``CollectorRequests`` in ``src/shared/protocol.ts``;
the defaults apply when the extension leaves a key out.
"""

from dataclasses import dataclass, field
from typing import Self

from _vscode_pyprof.collector.options import CollectorOptions
from _vscode_pyprof.collector.protocol import StopReason
from _vscode_pyprof.wire import WireReadable, WireReader


@dataclass(frozen=True, slots=True)
class NoParams(WireReadable):
    """For requests that take no parameters."""

    @classmethod
    def from_wire(cls, raw: object, where: str = "$") -> Self:
        WireReader.for_object(raw, where)
        return cls()


@dataclass(frozen=True, slots=True)
class InitializeParams(WireReadable):
    options: CollectorOptions = field(default_factory=CollectorOptions)
    label: str | None = None
    """What the profile is named after, e.g. the launched script."""

    @classmethod
    def from_wire(cls, raw: object, where: str = "$") -> Self:
        message = WireReader.for_object(raw, where)
        return cls(
            options=message.get_or("options", CollectorOptions, CollectorOptions()),
            label=message.get_or("label", str, None),
        )


@dataclass(frozen=True, slots=True)
class AttachParams(WireReadable):
    pid: int
    inject: bool = True
    """Inject the in-process agent; sampling works without it."""

    @classmethod
    def from_wire(cls, raw: object, where: str = "$") -> Self:
        message = WireReader.for_object(raw, where)
        return cls(pid=message.get("pid", int), inject=message.get_or("inject", bool, True))


@dataclass(frozen=True, slots=True)
class StopParams(WireReadable):
    reason: str = StopReason.USER
    """A ``StopReason`` value or the extension's own reason."""

    @classmethod
    def from_wire(cls, raw: object, where: str = "$") -> Self:
        return cls(reason=WireReader.for_object(raw, where).get_or("reason", str, StopReason.USER))


@dataclass(frozen=True, slots=True)
class TracemallocParams(WireReadable):
    enabled: bool = True
    frames: int | None = None
    """Traceback depth; ``None`` uses the session's ``tracemalloc_frames``."""

    @classmethod
    def from_wire(cls, raw: object, where: str = "$") -> Self:
        message = WireReader.for_object(raw, where)
        return cls(enabled=message.get_or("enabled", bool, True), frames=message.get_or("frames", int, None))


@dataclass(frozen=True, slots=True)
class SnapshotParams(WireReadable):
    label: str | None = None
    limit: int = 3000
    """How many of the largest allocations to list."""

    @classmethod
    def from_wire(cls, raw: object, where: str = "$") -> Self:
        message = WireReader.for_object(raw, where)
        return cls(label=message.get_or("label", str, None), limit=message.get_or("limit", int, 3000))


@dataclass(frozen=True, slots=True)
class ObjectCountsParams(WireReadable):
    limit: int = 60
    """How many of the most common types to list."""

    @classmethod
    def from_wire(cls, raw: object, where: str = "$") -> Self:
        return cls(limit=WireReader.for_object(raw, where).get_or("limit", int, 60))


@dataclass(frozen=True, slots=True)
class AsyncioDebugParams(WireReadable):
    enabled: bool = True
    slow_ms: float | None = None
    """Slow-callback threshold; ``None`` uses the session's ``slow_callback_ms``."""

    @classmethod
    def from_wire(cls, raw: object, where: str = "$") -> Self:
        message = WireReader.for_object(raw, where)
        return cls(enabled=message.get_or("enabled", bool, True), slow_ms=message.get_or("slowMs", float, None))


@dataclass(frozen=True, slots=True)
class MarkParams(WireReadable):
    name: str = "marker"

    @classmethod
    def from_wire(cls, raw: object, where: str = "$") -> Self:
        return cls(name=WireReader.for_object(raw, where).get_or("name", str, "marker"))


@dataclass(frozen=True, slots=True)
class SaveParams(WireReadable):
    path: str

    @classmethod
    def from_wire(cls, raw: object, where: str = "$") -> Self:
        return cls(path=WireReader.for_object(raw, where).get("path", str))
