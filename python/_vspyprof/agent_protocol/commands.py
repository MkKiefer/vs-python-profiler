"""The commands the collector sends to the agent, each as the ``body`` of a ``wire.Request``.

The agent runs a command by its class and answers with a ``wire.Response`` whose
``result`` is the reply named in the command's docstring (``None`` if there is none).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class StartTracing:
    """Answered with a ``TracingStatus``."""

    frames: int
    """Traceback depth tracemalloc records."""


@dataclass(frozen=True)
class StopTracing:
    """Answered with a ``TracingStatus``."""


@dataclass(frozen=True)
class TakeSnapshot:
    """Answered with a ``HeapSnapshot``."""

    limit: int
    """How many of the largest allocations to list."""


@dataclass(frozen=True)
class CountObjects:
    """Answered with ``ObjectCounts``."""

    limit: int
    """How many of the most common types to list."""


@dataclass(frozen=True)
class SetAsyncioDebug:
    """Answered with an ``AsyncioDebugStatus``."""

    enabled: bool
    slow_ms: float | None = None
    """Slow-callback threshold; ``None`` keeps the current one."""


@dataclass(frozen=True)
class Ping:
    """Answered with a ``Pong``."""


@dataclass(frozen=True)
class Shutdown:
    """Answered with ``None``; the agent then stops."""
