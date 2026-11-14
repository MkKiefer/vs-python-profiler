"""JSON on the wire: typed access to decoded objects and newline-delimited framing.

Every JSON message (RPC params, agent messages, agent replies) is validated once
at the boundary through a ``WireReader`` instead of being passed around as an
untyped dict. ``JsonLines`` is the framing every channel shares: one JSON object
per line.
"""

import json
from collections.abc import Callable, Mapping

type JsonObject = dict[str, object]


class WireError(ValueError):
    """A JSON message does not have the expected shape."""


class WireReader:
    def __init__(self, data: Mapping[str, object]) -> None:
        self._data = data

    @classmethod
    def of(cls, value: object) -> WireReader:
        """Wrap ``value`` if it is a JSON object, otherwise read as empty."""
        if isinstance(value, Mapping):
            return cls({str(k): v for k, v in value.items()})
        return cls({})

    def to_dict(self) -> JsonObject:
        return dict(self._data)

    def has(self, key: str) -> bool:
        return self._data.get(key) is not None

    def get_raw(self, key: str) -> object:
        return self._data.get(key)

    def get_int(self, key: str, default: int | None = None) -> int:
        value = self._data.get(key)
        if isinstance(value, bool):
            raise WireError(f"{key!r} must be a number, got a boolean")
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str) and value.strip().lstrip("-").isdigit():
            return int(value)
        if value is None and default is not None:
            return default
        raise WireError(f"{key!r} must be a number, got {value!r}")

    def get_float(self, key: str, default: float | None = None) -> float:
        value = self._data.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        if value is None and default is not None:
            return default
        raise WireError(f"{key!r} must be a number, got {value!r}")

    def get_bool(self, key: str, default: bool) -> bool:
        value = self._data.get(key)
        return default if value is None else bool(value)

    def get_str(self, key: str, default: str | None = None) -> str:
        value = self._data.get(key)
        if isinstance(value, str):
            return value
        if value is None and default is not None:
            return default
        raise WireError(f"{key!r} must be a string, got {value!r}")

    def get_optional_str(self, key: str) -> str | None:
        value = self._data.get(key)
        return value if isinstance(value, str) else None

    def get_object(self, key: str) -> WireReader:
        return WireReader.of(self._data.get(key))

    def get_list(self, key: str) -> list[object]:
        value = self._data.get(key)
        return list(value) if isinstance(value, list) else []

    def get_str_list(self, key: str) -> list[str]:
        return [str(item) for item in self.get_list(key)]


class JsonLines:
    """Decodes a byte stream of newline-delimited JSON messages."""

    def __init__(self) -> None:
        self._buffer = b""

    @staticmethod
    def encode(message: JsonObject, fallback: Callable[[object], object] | None = None) -> bytes:
        """One message as a line; ``fallback`` converts values JSON cannot represent."""
        return (json.dumps(message, separators=(",", ":"), default=fallback) + "\n").encode("utf-8")

    def feed(self, chunk: bytes) -> None:
        self._buffer += chunk

    def next_message(self) -> WireReader | None:
        """The next complete message, or ``None`` until more bytes arrive.

        Blank lines are skipped. Raises ``ValueError`` for a line that is not JSON.
        """
        while b"\n" in self._buffer:
            line, self._buffer = self._buffer.split(b"\n", 1)
            if line.strip():
                return WireReader.of(json.loads(line))
        return None
