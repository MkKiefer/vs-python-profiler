"""The first message of an agent."""

from dataclasses import dataclass

from _vscode_pyprof.agent_protocol.names import AgentMessageType
from _vscode_pyprof.wire import WireMessage, WireRow


@dataclass(frozen=True)
class ThreadName(WireRow):
    """The name of one thread of the target; sent as ``[ident, native_id, name]``."""

    ident: int | None
    native_id: int | None
    name: str

    def ids(self) -> list[int]:
        """Every id samples may carry for this thread (which one depends on the platform)."""
        return [thread_id for thread_id in (self.native_id, self.ident) if thread_id is not None]


@dataclass(frozen=True)
class AgentHello(WireMessage):
    """What the agent tells the collector about its process when it connects."""

    wire_type = AgentMessageType.HELLO

    token: str
    """The one-time token of the ``AgentAddress``; proves the agent was started by this session."""
    pid: int
    executable: str | None
    argv: list[str]
    cwd: str | None
    version: str | None
    """Python version of the target, ``major.minor.micro``."""
    threads: list[ThreadName]
