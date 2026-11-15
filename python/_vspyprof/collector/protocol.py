"""Values with a fixed set of names in the messages between the extension and the collector.

Mirror of the matching string unions in ``src/shared/protocol.ts``.
"""

from enum import StrEnum


class SessionState(StrEnum):
    """``state`` of a ``StateChanged`` notification and of the ``GetStatus`` result."""

    IDLE = "idle"
    RUNNING = "running"
    STOPPED = "stopped"
    EXITED = "exited"


class StopReason(StrEnum):
    """Why profiling ended (``reason`` of a ``StateChanged`` notification); the extension may send its own."""

    USER = "user"
    SHUTDOWN = "shutdown"
    EXITED = "exited"
    ERROR = "error"
