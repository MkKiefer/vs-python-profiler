"""Messages on the wire: dataclasses as newline-delimited JSON, told apart by their ``"type"``.

Every message is a plain dataclass. On the wire it is one JSON object per line:
its class name under ``"type"``, then its fields with camelCase keys. Nested
dataclasses are written the same way, so the reader can rebuild each of them::

    {"type": "Request", "id": 1, "body": {"type": "TakeSnapshot", "limit": 3000}}

Writing (``WireEncoder``): ``None`` is ``null``, a tuple is an array, an enum is
its value and a dict is written as it is (a payload that is already JSON, such as
a profile delta).

Reading (``WireDecoder``): the decoder is given the classes its end receives and
builds every object by its ``"type"`` with ``cls(**fields)``, so a missing key
takes the field's default; an object without ``"type"`` stays a dict. A type it
does not know, a missing required key or an unknown key is a ``WireError``.
Values are not checked against the field types: both ends are built from the same
classes (``src/shared/protocol.ts`` mirrors them for the extension).

The module is imported into the profiled program, so it uses ``json`` and ``dataclasses`` only.
"""

import json
from collections.abc import Iterable
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum

type JsonObject = dict[str, object]


class WireError(ValueError):
    """A line is not a message the decoder knows."""


@dataclass(frozen=True)
class Request:
    """Asks the other end to run ``body``; answered by the ``Response`` with the same ``id``."""

    id: int
    body: object
    """A command dataclass; its class tells the other end what to run."""


@dataclass(frozen=True)
class Response:
    """The answer to the ``Request`` with the same ``id``: its result, or the error it failed with."""

    id: int
    result: object = None
    error: str | None = None


class WireEncoder:
    """Writes dataclass messages as JSON lines."""

    def __init__(self) -> None:
        self._keys: dict[type, tuple[tuple[str, str], ...]] = {}
        """(field name, JSON key) of each class written so far."""

    def encode(self, message: object) -> bytes:
        """One message as a line, ready to be sent."""
        return (self.to_text(message) + "\n").encode()

    def to_text(self, message: object) -> str:
        """One message as JSON text without the newline. Values JSON cannot represent are written as their ``repr``."""
        return json.dumps(self.to_json(message), separators=(",", ":"), default=repr)

    def to_json(self, value: object) -> object:
        """``value`` as a JSON value: dataclasses become typed objects, recursively."""
        if is_dataclass(value) and not isinstance(value, type):
            wire: JsonObject = {"type": type(value).__name__}
            for name, key in self._keys_of(type(value)):
                wire[key] = self.to_json(getattr(value, name))
            return wire
        if isinstance(value, (list, tuple)):
            return [self.to_json(item) for item in value]
        if isinstance(value, Enum):
            return value.value
        return value

    def _keys_of(self, cls: type) -> tuple[tuple[str, str], ...]:
        keys = self._keys.get(cls)
        if keys is None:
            keys = self._keys[cls] = tuple((item.name, _Names.camel(item.name)) for item in fields(cls))
        return keys


class WireDecoder:
    """Reads the JSON lines of the dataclasses one end receives."""

    def __init__(self, models: Iterable[type]) -> None:
        """``models`` are every class that may arrive, nested ones included."""
        self._models: dict[str, type] = {}
        for model in models:
            if not is_dataclass(model):
                raise TypeError(f"{model.__name__} is not a dataclass")
            if model.__name__ in self._models:
                raise TypeError(f"two models are named {model.__name__!r}")
            self._models[model.__name__] = model

    def decode(self, line: str | bytes) -> object:
        """The message on one line. Raises ``WireError`` for anything else (``ValueError`` for broken JSON)."""
        return self.from_json(json.loads(line))

    def from_json(self, value: object, where: str = "$") -> object:
        """A decoded JSON value with its typed objects turned back into dataclasses; ``where`` names it in errors."""
        if isinstance(value, list):
            return [self.from_json(item, f"{where}[{index}]") for index, item in enumerate(value)]
        if not isinstance(value, dict) or "type" not in value:
            return value
        model = self._models.get(str(value["type"]))
        if model is None:
            raise WireError(f"{where} has unknown type {value['type']!r}")
        arguments = {
            _Names.snake(key): self.from_json(item, f"{where}.{key}") for key, item in value.items() if key != "type"
        }
        try:
            return model(**arguments)
        except TypeError as error:  # a missing or unknown field
            raise WireError(f"{where} is not a {model.__name__}: {error}") from None


class LineBuffer:
    """Splits a byte stream into lines (one message each)."""

    def __init__(self) -> None:
        self._buffer = b""

    def feed(self, chunk: bytes) -> None:
        self._buffer += chunk

    def next_line(self) -> bytes | None:
        """The next complete line that is not blank, or ``None`` until more bytes arrive."""
        while b"\n" in self._buffer:
            line, self._buffer = self._buffer.split(b"\n", 1)
            if line.strip():
                return line
        return None


class _Names:
    """Field names (snake_case) and JSON keys (camelCase)."""

    @staticmethod
    def camel(name: str) -> str:
        first, *rest = name.split("_")
        return first + "".join(part.capitalize() for part in rest)

    @staticmethod
    def snake(key: str) -> str:
        return "".join(f"_{char.lower()}" if char.isupper() else char for char in key)
