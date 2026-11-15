"""JSON on the wire: dataclass messages read and written from their field types, and newline-delimited framing.

Every message (RPC params and results, agent messages and replies, options) is a
dataclass that derives from ``WireMessage`` (a JSON object) or ``WireRow`` (a
JSON array). ``from_wire`` validates a decoded JSON value once, at the boundary,
by the field types; ``to_wire`` is called once, where the message leaves the
process. Code in between passes the dataclasses around, never dicts.

What a field may be: ``bool``, ``int``, ``float``, ``str``, an ``Enum``,
another ``WireMessage`` / ``WireRow``, ``list[T]`` of those, ``X | None``,
``JsonObject`` (an object passed through unread) or ``object`` (any JSON value).
A field's JSON key is its name in camelCase unless ``wire()`` names another one.

Reading: keys that are missing or ``null`` take the field's default, ``None``
for an optional field without one, and are an error otherwise; unknown keys are
ignored. Writing: fields that are ``None`` are left out.

The module is imported into the profiled program, so it reads the field types
with ``types`` alone instead of ``typing``.
"""

import json
import types
from collections.abc import Callable, Mapping
from dataclasses import MISSING, Field, fields
from enum import Enum

# annotations only: loading ``typing`` into the profiled program is not worth a ClassVar
lazy from typing import ClassVar

type JsonObject = dict[str, object]

type _Decode = Callable[[object, str], object]
"""Turns a JSON value into a field value; the ``str`` names the value in error messages."""

_WIRE_NAME = "wire_name"
_AT_LEAST = "wire_at_least"


class WireError(ValueError):
    """A JSON message does not have the expected shape."""


def wire(name: str | None = None, *, at_least: int | None = None) -> Mapping[str, object]:
    """Field metadata: the JSON key if it is not the camelCase field name, and a lower bound.

    A number read below ``at_least`` is raised to it (settings and launch configs
    may hold any number). Use as ``field(metadata=wire("t"))``.
    """
    metadata: dict[str, object] = {}
    if name is not None:
        metadata[_WIRE_NAME] = name
    if at_least is not None:
        metadata[_AT_LEAST] = at_least
    return metadata


class _Codec:
    """Everything a message class needs to be read and written, worked out once per class."""

    __slots__ = ("_fields",)

    def __init__(self, cls: type) -> None:
        self._fields = tuple(_FieldCodec(item) for item in fields(cls))

    @classmethod
    def of(cls, message_class: type) -> _Codec:
        codec = _CODECS.get(message_class)
        if codec is None:
            codec = _CODECS[message_class] = cls(message_class)
        return codec

    def read_object(self, raw: Mapping[str, object], where: str) -> dict[str, object]:
        """The constructor arguments for a JSON object."""
        return {item.name: item.read(raw.get(item.key), where) for item in self._fields if item.init}

    def read_row(self, raw: list[object], where: str) -> list[object]:
        """The constructor arguments for a JSON array, in field order."""
        if len(raw) != len(self._fields):
            raise WireError(f"{where} must have {len(self._fields)} items, got {len(raw)}")
        return [item.read(value, where) for item, value in zip(self._fields, raw, strict=True)]

    def write_object(self, message: object) -> JsonObject:
        wire: JsonObject = {}
        for item in self._fields:
            value = getattr(message, item.name)
            if value is not None:
                wire[item.key] = _write(value)
        return wire

    def write_row(self, message: object) -> list[object]:
        return [_write(getattr(message, item.name)) for item in self._fields]


_CODECS: dict[type, _Codec] = {}
"""Filled on first use of each message class; two threads racing only build one codec twice."""


class _FieldCodec:
    __slots__ = ("_at_least", "_decode", "_default", "_factory", "init", "key", "name")

    def __init__(self, item: Field[object]) -> None:
        self.name = item.name
        self.key = str(item.metadata.get(_WIRE_NAME) or _camel_case(item.name))
        self.init = item.init
        self._decode = _decoder(item.type)
        self._default: object = item.default
        self._factory = item.default_factory
        if self._default is MISSING and self._factory is MISSING and _is_optional(item.type):
            self._default = None
        at_least = item.metadata.get(_AT_LEAST)
        self._at_least = at_least if isinstance(at_least, int) else None

    def read(self, value: object, where: str) -> object:
        where = f"{where}.{self.key}"
        if value is None:
            if self._default is not MISSING:
                return self._default
            if self._factory is not MISSING:
                return self._factory()
            raise WireError(f"{where} is missing")
        result = self._decode(value, where)
        if self._at_least is not None and isinstance(result, (int, float)) and result < self._at_least:
            return self._at_least
        return result


class WireMessage:
    """A dataclass that is sent as a JSON object.

    ``wire_type`` is set by messages that carry a ``"type"`` key, which tells
    them apart on a channel (see ``read_one_of``).
    """

    __slots__ = ()

    wire_type: ClassVar[str | None] = None

    @classmethod
    def from_wire[M: WireMessage](cls: type[M], raw: object, where: str = "$") -> M:
        """Read a decoded JSON object. Raises ``WireError`` if it has another shape."""
        if not isinstance(raw, Mapping):
            raise WireError(f"{where} must be an object, got {raw!r}")
        if cls.wire_type is not None and raw.get("type") != cls.wire_type:
            raise WireError(f"{where}.type must be {str(cls.wire_type)!r}, got {raw.get('type')!r}")
        return cls(**_Codec.of(cls).read_object(raw, where))

    def to_wire(self) -> JsonObject:
        wire = _Codec.of(type(self)).write_object(self)
        if self.wire_type is not None:
            wire["type"] = str(self.wire_type)
        return wire


class WireRow:
    """A dataclass that is sent as a JSON array of its fields, in order (compact for long lists)."""

    __slots__ = ()

    @classmethod
    def from_wire[R: WireRow](cls: type[R], raw: object, where: str = "$") -> R:
        """Read a decoded JSON array. Raises ``WireError`` if it has another shape."""
        if not isinstance(raw, list):
            raise WireError(f"{where} must be an array, got {raw!r}")
        return cls(*_Codec.of(cls).read_row(raw, where))

    def to_wire(self) -> list[object]:
        return _Codec.of(type(self)).write_row(self)


def read_one_of(raw: object, *classes: type[WireMessage]) -> WireMessage:
    """Read whichever of ``classes`` the ``"type"`` of ``raw`` names. Raises ``WireError`` for another type."""
    message_type = raw.get("type") if isinstance(raw, Mapping) else None
    for cls in classes:
        if cls.wire_type == message_type:
            return cls.from_wire(raw)
    raise WireError(f"unexpected message type {message_type!r}")


def _camel_case(name: str) -> str:
    first, *rest = name.split("_")
    return first + "".join(part.capitalize() for part in rest)


def _resolve(tp: object) -> object:
    """``tp`` with ``type`` aliases (such as ``JsonObject``) replaced by what they stand for."""
    while isinstance(value := getattr(tp, "__value__", None), (type, types.GenericAlias, types.UnionType)):
        tp = value
    return tp


def _is_optional(tp: object) -> bool:
    tp = _resolve(tp)
    return isinstance(tp, types.UnionType) and types.NoneType in tp.__args__


def _write(value: object) -> object:
    if isinstance(value, (WireMessage, WireRow)):
        return value.to_wire()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, list):
        return [_write(item) for item in value]
    return value


def _decoder(tp: object) -> _Decode:
    """How to read a field of type ``tp``. Raises ``TypeError`` for a type JSON cannot hold."""
    tp = _resolve(tp)
    if isinstance(tp, types.UnionType):
        arms = [_resolve(arm) for arm in tp.__args__ if arm is not types.NoneType]
        if len(arms) != 1:
            raise TypeError(f"only X | None unions can be read from JSON, not {tp!r}")
        return _decoder(arms[0])  # null is handled by the field
    if isinstance(tp, types.GenericAlias):
        return _generic_decoder(tp)
    if not isinstance(tp, type):
        raise TypeError(f"cannot read {tp!r} from JSON")
    simple = _SIMPLE_DECODERS.get(tp)
    if simple is not None:
        return simple
    if issubclass(tp, Enum):
        return _enum_decoder(tp)
    if issubclass(tp, (WireMessage, WireRow)):
        return tp.from_wire
    raise TypeError(f"cannot read {tp!r} from JSON")


def _generic_decoder(tp: types.GenericAlias) -> _Decode:
    origin, args = tp.__origin__, tp.__args__
    if origin is list:
        read_item = _decoder(args[0])

        def read_list(value: object, where: str) -> object:
            if not isinstance(value, list):
                raise WireError(f"{where} must be an array, got {value!r}")
            return [read_item(item, f"{where}[{index}]") for index, item in enumerate(value)]

        return read_list
    if origin is dict and args == (str, object):
        return _read_json_object
    raise TypeError(f"cannot read {tp!r} from JSON")


def _enum_decoder(enum_class: type[Enum]) -> _Decode:
    def read_enum(value: object, where: str) -> object:
        try:
            return enum_class(value)
        except ValueError:
            raise WireError(
                f"{where} must be one of {[member.value for member in enum_class]}, got {value!r}"
            ) from None

    return read_enum


def _read_bool(value: object, where: str) -> object:
    if not isinstance(value, bool):
        raise WireError(f"{where} must be a boolean, got {value!r}")
    return value


def _read_int(value: object, where: str) -> object:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float) and value.is_integer():  # JavaScript has no integers
        return int(value)
    raise WireError(f"{where} must be an integer, got {value!r}")


def _read_float(value: object, where: str) -> object:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    raise WireError(f"{where} must be a number, got {value!r}")


def _read_str(value: object, where: str) -> object:
    if not isinstance(value, str):
        raise WireError(f"{where} must be a string, got {value!r}")
    return value


def _read_json_object(value: object, where: str) -> object:
    if not isinstance(value, dict):
        raise WireError(f"{where} must be an object, got {value!r}")
    return value


def _read_any(value: object, _where: str) -> object:
    return value


_SIMPLE_DECODERS: dict[type, _Decode] = {
    bool: _read_bool,
    int: _read_int,
    float: _read_float,
    str: _read_str,
    object: _read_any,
}


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
