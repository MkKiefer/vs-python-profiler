"""What the agent switches on when it starts."""

import json
from dataclasses import dataclass, field

from _vscode_pyprof.wire import WireMessage, wire


@dataclass(frozen=True)
class AgentOptions(WireMessage):
    """The part of the session options the agent applies itself.

    The wire names are those of ``CollectorOptions`` in ``src/shared/protocol.ts``,
    so the extension can hand its whole options object to a launched program.
    """

    tracemalloc: bool = False
    tracemalloc_frames: int = field(default=16, metadata=wire(at_least=1))
    asyncio_debug: bool = False
    slow_callback_ms: float = 100.0

    @classmethod
    def from_json(cls, text: str | None) -> AgentOptions:
        """Read options from JSON text; text that is missing or unusable gives the defaults."""
        if not text:
            return cls()
        try:
            return cls.from_wire(json.loads(text))
        except ValueError:  # not JSON, or a value of the wrong type
            return cls()

    def to_json(self) -> str:
        return json.dumps(self.to_wire())
