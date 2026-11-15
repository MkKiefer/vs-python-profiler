"""What the agent switches on when it starts."""

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentOptions:
    """The part of the session options the agent applies itself.

    The collector writes it as one JSON line (``InitializeResult.agent_options``);
    the extension hands that text to a launched program, the collector to an
    attached one, and the agent reads it back on start.
    """

    tracemalloc: bool = False
    tracemalloc_frames: int = 16
    asyncio_debug: bool = False
    slow_callback_ms: float = 100.0
