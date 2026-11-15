"""What an agent connection reports to its owner."""

from abc import ABC, abstractmethod

from _vscode_pyprof.agent_protocol.metrics import AgentMetrics

# annotations only: importing it eagerly would be circular (the connection calls its listener)
lazy from _vscode_pyprof.collector.agent.connection import AgentConnection


class AgentListener(ABC):
    """Receives the life-cycle of agent connections."""

    @abstractmethod
    def on_agent_hello(self, connection: AgentConnection) -> None: ...

    @abstractmethod
    def on_agent_metrics(self, connection: AgentConnection, metrics: AgentMetrics) -> None: ...

    @abstractmethod
    def on_agent_close(self, connection: AgentConnection) -> None: ...
