"""What the agent switches on when it starts."""

import json
from dataclasses import dataclass

# annotations only: loading ``typing`` into the profiled program is not worth a Self
lazy from typing import Self

from _vscode_pyprof.wire import JsonObject, WireMessage, WireReader


@dataclass(frozen=True)
class AgentOptions(WireMessage):
    """The part of the session options the agent applies itself.

    The wire names are those of ``CollectorOptions`` in ``src/shared/protocol.ts``,
    so the extension can hand its whole options object to a launched program.
    """

    tracemalloc: bool = False
    tracemalloc_frames: int = 16
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

    def to_wire(self) -> JsonObject:
        return {
            "tracemalloc": self.tracemalloc,
            "tracemallocFrames": self.tracemalloc_frames,
            "asyncioDebug": self.asyncio_debug,
            "slowCallbackMs": self.slow_callback_ms,
        }

    @classmethod
    def from_wire(cls, raw: object, where: str = "$") -> Self:
        """Missing or ``null`` keys keep their default; fewer than one traceback frame is raised to one."""
        message = WireReader.for_object(raw, where)
        defaults = cls()
        return cls(
            tracemalloc=message.get_or("tracemalloc", bool, defaults.tracemalloc),
            tracemalloc_frames=max(1, message.get_or("tracemallocFrames", int, defaults.tracemalloc_frames)),
            asyncio_debug=message.get_or("asyncioDebug", bool, defaults.asyncio_debug),
            slow_callback_ms=message.get_or("slowCallbackMs", float, defaults.slow_callback_ms),
        )
