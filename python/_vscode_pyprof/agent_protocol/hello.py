"""The first message of an agent."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ThreadName:
    """The name of one thread of the target."""

    ident: int | None
    native_id: int | None
    name: str

    def ids(self) -> list[int]:
        """Every id samples may carry for this thread (which one depends on the platform)."""
        return [thread_id for thread_id in (self.native_id, self.ident) if thread_id is not None]


@dataclass(frozen=True)
class AgentHello:
    """What the agent tells the collector about its process when it connects."""

    token: str
    """The one-time token of the ``AgentAddress``; proves the agent was started by this session."""
    pid: int
    executable: str | None
    argv: list[str]
    cwd: str | None
    version: str | None
    """Python version of the target, ``major.minor.micro``."""
    threads: list[ThreadName]
