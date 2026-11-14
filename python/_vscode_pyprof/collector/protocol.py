"""Names of the RPC between the extension and the collector.

Mirror of ``CollectorRequests`` and ``CollectorNotification`` in
``src/shared/protocol.ts``; a name added on one side must be added on the other.
"""

from enum import StrEnum


class RpcMethod(StrEnum):
    """Requests the extension sends."""

    INITIALIZE = "initialize"
    ATTACH = "attach"
    STOP = "stop"
    STATUS = "status"
    TRACEMALLOC = "tracemalloc"
    SNAPSHOT = "snapshot"
    OBJECT_COUNTS = "objectCounts"
    ASYNCIO_DEBUG = "asyncioDebug"
    MARK = "mark"
    SAVE = "save"
    SHUTDOWN = "shutdown"


class RpcNotification(StrEnum):
    """Notifications the collector pushes without being asked."""

    DELTA = "delta"
    STATE = "state"
    AGENT = "agent"
    CHILDREN = "children"
    ERROR = "error"


class SessionState(StrEnum):
    """``state`` of a ``STATE`` notification and of the ``STATUS`` result."""

    IDLE = "idle"
    RUNNING = "running"
    STOPPED = "stopped"
    EXITED = "exited"


class StopReason(StrEnum):
    """Why profiling ended (``reason`` of a ``STATE`` notification); the extension may send its own."""

    USER = "user"
    SHUTDOWN = "shutdown"
    EXITED = "exited"
