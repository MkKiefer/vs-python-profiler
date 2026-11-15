"""Which messages travel in which direction between the collector and the agent.

Each end builds its ``WireDecoder`` from the tuple it receives.
"""

from _vscode_pyprof.agent_protocol.commands import (
    CountObjects,
    Ping,
    SetAsyncioDebug,
    Shutdown,
    StartTracing,
    StopTracing,
    TakeSnapshot,
)
from _vscode_pyprof.agent_protocol.hello import AgentHello, ThreadName
from _vscode_pyprof.agent_protocol.metrics import AgentEvent, AgentMetrics, EventDetails, LoopMetrics, TracedMemory
from _vscode_pyprof.agent_protocol.options import AgentOptions
from _vscode_pyprof.agent_protocol.replies import (
    Allocation,
    AsyncioDebugStatus,
    HeapSnapshot,
    ObjectCounts,
    Pong,
    SourceLine,
    TracingStatus,
    TypeCount,
)
from _vscode_pyprof.wire import Request, Response

TO_AGENT: tuple[type, ...] = (
    Request,
    StartTracing,
    StopTracing,
    TakeSnapshot,
    CountObjects,
    SetAsyncioDebug,
    Ping,
    Shutdown,
    AgentOptions,
)
"""The commands, and the options the agent starts with."""

FROM_AGENT: tuple[type, ...] = (
    AgentHello,
    ThreadName,
    AgentMetrics,
    TracedMemory,
    LoopMetrics,
    AgentEvent,
    EventDetails,
    Response,
    TracingStatus,
    AsyncioDebugStatus,
    HeapSnapshot,
    Allocation,
    SourceLine,
    ObjectCounts,
    TypeCount,
    Pong,
)
"""The hello, the metrics and the replies to the commands."""
