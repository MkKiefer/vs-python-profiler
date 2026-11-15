"""What the collector tells the extension without being asked.

Mirror of ``CollectorNotification`` in ``src/shared/protocol.ts``. The ``delta``
notification is not here: its payload is ``Store.delta()``.
"""

from dataclasses import dataclass, field
from typing import ClassVar

from _vscode_pyprof.collector.protocol import RpcNotification, SessionState
from _vscode_pyprof.wire import WireMessage


class Notification(WireMessage):
    """A message with a fixed notification name."""

    __slots__ = ()

    method: ClassVar[RpcNotification]


@dataclass(frozen=True, slots=True)
class StateChanged(Notification):
    method = RpcNotification.STATE

    state: SessionState
    pid: int | None = None
    """The sampled process, when sampling starts."""
    reason: str | None = None
    """A ``StopReason`` value or the extension's own reason, when sampling ends."""


@dataclass(frozen=True, slots=True)
class AgentConnected(Notification):
    method = RpcNotification.AGENT

    pid: int
    argv: list[str]
    cwd: str | None
    connected: bool = field(default=True, init=False)


@dataclass(frozen=True, slots=True)
class AgentDisconnected(Notification):
    method = RpcNotification.AGENT

    connected: bool = field(default=False, init=False)


@dataclass(frozen=True, slots=True)
class ChildrenFound(Notification):
    """Python child processes of the target that were not known before."""

    method = RpcNotification.CHILDREN

    pids: list[int]


@dataclass(frozen=True, slots=True)
class ErrorOccurred(Notification):
    """A failure outside any request, e.g. sampling could not start for a launched program."""

    method = RpcNotification.ERROR

    message: str
