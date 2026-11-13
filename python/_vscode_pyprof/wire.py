"""Typed access to decoded JSON objects.

Every JSON message (RPC params, agent messages, hub replies) is validated once
at the boundary through a ``WireReader`` instead of being passed around as an
untyped dict.
"""

from collections.abc import Mapping

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
