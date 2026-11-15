"""JSON on the wire: messages that read and write themselves, and newline-delimited framing.

Every message is a dataclass of its own that spells out its JSON in two methods:
``to_wire()`` builds the JSON value, ``from_wire()`` reads it back through a
``WireReader``, which checks each value's JSON type and names its path in errors
(``$.params.limit must be an integer``). Both run once, at the edge of the
process; code in between passes the dataclasses around, never dicts.

A field that may be absent is optional in the dataclass (``X | None = None``, or
another default): ``from_wire`` reads it with ``get_or`` and ``to_wire`` leaves
``None`` out (``_omit_none``). Unknown keys are ignored.

``WireParser`` reads a message whose ``"type"`` names its class.

The module is imported into the profiled program: no ``typing`` at runtime.
"""

import json
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from enum import Enum

# annotations only: loading ``typing`` into the profiled program is not worth a Self
lazy from typing import NoReturn, Self

type JsonObject = dict[str, object]


class WireError(ValueError):
    """A JSON message does not have the expected shape."""


class WireWritable(ABC):
    """A message this process sends."""

    __slots__ = ()

    @abstractmethod
    def to_wire(self) -> object:
        """The message as a JSON value, ready to be encoded."""

    @staticmethod
    def _omit_none(fields: JsonObject) -> JsonObject:
        """``fields`` without the ones that are ``None`` (optional fields that are not set)."""
        return {key: value for key, value in fields.items() if value is not None}


class WireReadable(ABC):
    """A message this process receives."""

    __slots__ = ()

    @classmethod
    @abstractmethod
    def from_wire(cls, raw: object, where: str = "$") -> Self:
        """Read a decoded JSON value. Raises ``WireError`` if it has another shape; ``where`` is its path."""


class WireMessage(WireWritable, WireReadable):
    """A message both ends of a connection share: one side writes it, the other reads it."""

    __slots__ = ()


class WireReader:
    """Reads the values of one JSON object, or of an array whose items are named, checking their JSON types.

    A ``kind`` is ``bool``, ``int``, ``float``, ``str``, an ``Enum`` or a
    ``WireReadable``. A JSON number is an ``int`` if it is integral (JavaScript
    has no integers); an ``int`` is accepted for ``float``; ``bool`` is never a number.
    """

    __slots__ = ("_raw", "_where")

    def __init__(self, raw: JsonObject, where: str) -> None:
        self._raw = raw
        self._where = where

    @classmethod
    def for_object(cls, raw: object, where: str) -> WireReader:
        if not isinstance(raw, dict):
            raise WireError(f"{where} must be an object, got {raw!r}")
        return cls(raw, where)

    @classmethod
    def for_row(cls, raw: object, where: str, names: tuple[str, ...]) -> WireReader:
        """A reader for a compact message sent as an array: its items are read by these ``names``."""
        if not isinstance(raw, list):
            raise WireError(f"{where} must be an array, got {raw!r}")
        if len(raw) != len(names):
            raise WireError(f"{where} must have {len(names)} items, got {len(raw)}")
        return cls(dict(zip(names, raw, strict=True)), where)

    def require_type(self, wire_type: str) -> None:
        """Raise ``WireError`` unless the object's ``"type"`` is ``wire_type``."""
        actual = self._raw.get("type")
        if actual != wire_type:
            raise WireError(f"{self._path('type')} must be {str(wire_type)!r}, got {actual!r}")

    def get[T](self, key: str, kind: type[T]) -> T:
        """A value that must be there (not missing, not ``null``)."""
        return self._read(self._present(key), kind, self._path(key))

    def get_or[T, D](self, key: str, kind: type[T], default: D) -> T | D:
        """A value that may be missing or ``null``; then ``default``."""
        value = self._raw.get(key)
        return default if value is None else self._read(value, kind, self._path(key))

    def list_of[T](self, key: str, kind: type[T]) -> list[T]:
        """An array that must be there."""
        return self._read_list(self._present(key), kind, self._path(key))

    def list_or[T](self, key: str, kind: type[T], default: list[T]) -> list[T]:
        """An array that may be missing or ``null``; then ``default``."""
        value = self._raw.get(key)
        return default if value is None else self._read_list(value, kind, self._path(key))

    def json_object(self, key: str) -> JsonObject:
        """An object passed on unread (its reader is chosen later, e.g. by a method name)."""
        value = self.json_object_or(key, None)
        return self._missing(key) if value is None else value

    def json_object_or[D](self, key: str, default: D) -> JsonObject | D:
        value = self._raw.get(key)
        if value is None:
            return default
        if not isinstance(value, dict):
            raise WireError(f"{self._path(key)} must be an object, got {value!r}")
        return value

    def value(self, key: str) -> object:
        """Any JSON value, unchecked; ``None`` if it is missing."""
        return self._raw.get(key)

    def _present(self, key: str) -> object:
        value = self._raw.get(key)
        return self._missing(key) if value is None else value

    def _missing(self, key: str) -> NoReturn:
        raise WireError(f"{self._path(key)} is missing")

    def _path(self, key: str) -> str:
        return f"{self._where}.{key}"

    def _read_list[T](self, value: object, kind: type[T], where: str) -> list[T]:
        if not isinstance(value, list):
            raise WireError(f"{where} must be an array, got {value!r}")
        return [self._read(item, kind, f"{where}[{index}]") for index, item in enumerate(value)]

    @staticmethod
    def _read[T](value: object, kind: type[T], where: str) -> T:
        if issubclass(kind, WireReadable):
            value = kind.from_wire(value, where)
        elif issubclass(kind, Enum):
            try:
                value = kind(value)
            except ValueError:
                raise WireError(f"{where} must be one of {[member.value for member in kind]}, got {value!r}") from None
        elif isinstance(value, bool) and kind is not bool:
            pass  # ``True`` is an ``int`` in Python, never a number in JSON
        elif kind is float and isinstance(value, int):
            value = float(value)
        elif kind is int and isinstance(value, float) and value.is_integer():
            value = int(value)
        if isinstance(value, kind) and not (isinstance(value, bool) and kind is not bool):
            return value
        raise WireError(f"{where} must be {WireReader._KIND_NAMES.get(kind, kind.__name__)}, got {value!r}")

    _KIND_NAMES: Mapping[object, str] = {bool: "a boolean", int: "an integer", float: "a number", str: "a string"}


class WireParser:
    """Reads messages that name their class in a ``"type"`` key."""

    def __init__(self, factories: Mapping[str, Callable[[object], WireReadable]]) -> None:
        """``factories`` maps each ``"type"`` value to what reads it, usually a ``from_wire``."""
        self._factories = dict(factories)

    def parse(self, raw: object) -> WireReadable:
        """Raises ``WireError`` for a message of another type, or of another shape than its type."""
        message_type = raw.get("type") if isinstance(raw, dict) else None
        factory = self._factories.get(message_type) if isinstance(message_type, str) else None
        if factory is None:
            raise WireError(f"unexpected message type {message_type!r}")
        return factory(raw)


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

    def next_message(self) -> JsonObject | None:
        """The next complete message, or ``None`` until more bytes arrive.

        Blank lines are skipped. Raises ``ValueError`` for a line that is not a JSON object.
        """
        while b"\n" in self._buffer:
            line, self._buffer = self._buffer.split(b"\n", 1)
            if line.strip():
                message = json.loads(line)
                if not isinstance(message, dict):
                    raise WireError(f"a message must be a JSON object, got {message!r}")
                return message
        return None
