"""What the collector tells the extension without being asked.

Mirror of ``CollectorNotification`` in ``src/shared/protocol.ts``; the class name is the ``"type"``.
"""

from dataclasses import dataclass

from _vspyprof.collector.protocol import SessionState
from _vspyprof.wire import JsonObject


@dataclass(frozen=True, slots=True)
class Delta:
    """What the profile recorded since the previous delta (``Store.delta()``)."""

    data: JsonObject


@dataclass(frozen=True, slots=True)
class StateChanged:
    state: SessionState
    pid: int | None = None
    """The sampled process, when sampling starts."""
    reason: str | None = None
    """A ``StopReason`` value or the extension's own reason, when sampling ends."""


@dataclass(frozen=True, slots=True)
class AgentConnected:
    pid: int
    argv: list[str]
    cwd: str | None


@dataclass(frozen=True, slots=True)
class AgentDisconnected:
    pass


@dataclass(frozen=True, slots=True)
class ChildrenFound:
    """Python child processes of the target that were not known before."""

    pids: list[int]


@dataclass(frozen=True, slots=True)
class ErrorOccurred:
    """A failure outside any request, e.g. sampling could not start for a launched program."""

    message: str
