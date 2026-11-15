"""Typed reads of raw JSON output in assertions (``Store.delta()``, RPC responses, saved profiles).

Production code reads JSON into ``WireMessage`` dataclasses; tests of code
whose output is plain JSON use this instead of casts.
"""

from collections.abc import Mapping


class JsonView:
    def __init__(self, data: Mapping[str, object]) -> None:
        self._data = data

    @classmethod
    def of(cls, value: object) -> JsonView:
        if not isinstance(value, Mapping):
            raise AssertionError(f"expected a JSON object, got {value!r}")
        return cls(value)

    def to_dict(self) -> dict[str, object]:
        return dict(self._data)

    def has(self, key: str) -> bool:
        return self._data.get(key) is not None

    def get_raw(self, key: str) -> object:
        return self._data.get(key)

    def get_int(self, key: str) -> int:
        value = self._data.get(key)
        if not isinstance(value, int) or isinstance(value, bool):
            raise AssertionError(f"{key!r} is not an integer: {value!r}")
        return value

    def get_float(self, key: str) -> float:
        value = self._data.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise AssertionError(f"{key!r} is not a number: {value!r}")
        return float(value)

    def get_bool(self, key: str) -> bool:
        value = self._data.get(key)
        if not isinstance(value, bool):
            raise AssertionError(f"{key!r} is not a boolean: {value!r}")
        return value

    def get_str(self, key: str) -> str:
        value = self._data.get(key)
        if not isinstance(value, str):
            raise AssertionError(f"{key!r} is not a string: {value!r}")
        return value

    def get_object(self, key: str) -> JsonView:
        return JsonView.of(self._data.get(key))

    def get_list(self, key: str) -> list[object]:
        value = self._data.get(key)
        if not isinstance(value, list):
            raise AssertionError(f"{key!r} is not an array: {value!r}")
        return value
