import unittest
from dataclasses import dataclass
from enum import StrEnum
from typing import Self

from _vscode_pyprof.wire import JsonLines, JsonObject, WireError, WireMessage, WireParser, WireReader


class _Color(StrEnum):
    RED = "red"
    BLUE = "blue"


@dataclass(frozen=True)
class _Point(WireMessage):
    """Sent as ``[x, y]``."""

    x: int
    y: int

    def to_wire(self) -> list[object]:
        return [self.x, self.y]

    @classmethod
    def from_wire(cls, raw: object, where: str = "$") -> Self:
        row = WireReader.for_row(raw, where, ("x", "y"))
        return cls(x=row.get("x", int), y=row.get("y", int))


@dataclass(frozen=True)
class _Sample(WireMessage):
    count: int
    label: str | None
    points: list[_Point]
    ratio: float = 0.5
    color: _Color = _Color.RED
    extra: JsonObject | None = None

    def to_wire(self) -> JsonObject:
        return self._omit_none(
            {
                "type": "sample",
                "count": self.count,
                "label": self.label,
                "points": [point.to_wire() for point in self.points],
                "ratio": self.ratio,
                "color": self.color,
                "extra": self.extra,
            }
        )

    @classmethod
    def from_wire(cls, raw: object, where: str = "$") -> Self:
        message = WireReader.for_object(raw, where)
        message.require_type("sample")
        return cls(
            count=message.get("count", int),
            label=message.get_or("label", str, None),
            points=message.list_of("points", _Point),
            ratio=message.get_or("ratio", float, 0.5),
            color=message.get_or("color", _Color, _Color.RED),
            extra=message.json_object_or("extra", None),
        )


@dataclass(frozen=True)
class _Other(WireMessage):
    def to_wire(self) -> JsonObject:
        return {"type": "other"}

    @classmethod
    def from_wire(cls, raw: object, where: str = "$") -> Self:
        WireReader.for_object(raw, where).require_type("other")
        return cls()


class TestWireReader(unittest.TestCase):
    def read(self, **values: object) -> _Sample:
        return _Sample.from_wire({"type": "sample", "count": 1, "points": []} | values)

    def test_get_or_with_missing_key_returns_default(self) -> None:
        self.assertEqual((self.read().ratio, self.read().color), (0.5, _Color.RED))

    def test_get_or_with_null_returns_default(self) -> None:
        self.assertEqual(self.read(color=None).color, _Color.RED)

    def test_get_or_with_missing_optional_value_returns_none(self) -> None:
        self.assertIsNone(self.read().label)

    def test_get_with_missing_key_raises_wire_error_naming_its_path(self) -> None:
        with self.assertRaisesRegex(WireError, r"\$\.count is missing"):
            _Sample.from_wire({"type": "sample", "points": []})

    def test_get_with_null_raises_wire_error(self) -> None:
        with self.assertRaisesRegex(WireError, r"\$\.count is missing"):
            self.read(count=None)

    def test_get_with_integral_float_for_int_returns_int(self) -> None:
        count = self.read(count=250.0).count

        self.assertEqual((count, type(count)), (250, int))

    def test_get_with_fractional_float_for_int_raises_wire_error(self) -> None:
        with self.assertRaisesRegex(WireError, r"\$\.count must be an integer, got 2\.5"):
            self.read(count=2.5)

    def test_get_with_boolean_for_int_raises_wire_error(self) -> None:
        with self.assertRaisesRegex(WireError, r"\$\.count must be an integer, got True"):
            self.read(count=True)

    def test_get_with_integer_for_float_returns_float(self) -> None:
        ratio = self.read(ratio=3).ratio

        self.assertEqual((ratio, type(ratio)), (3.0, float))

    def test_get_with_string_for_float_raises_wire_error(self) -> None:
        with self.assertRaisesRegex(WireError, r"\$\.ratio must be a number"):
            self.read(ratio="3")

    def test_get_with_number_for_string_raises_wire_error(self) -> None:
        with self.assertRaisesRegex(WireError, r"\$\.label must be a string"):
            self.read(label=3)

    def test_get_reads_enum_values(self) -> None:
        self.assertIs(self.read(color="blue").color, _Color.BLUE)

    def test_get_with_unknown_enum_value_raises_wire_error(self) -> None:
        with self.assertRaisesRegex(WireError, r"\$\.color must be one of \['red', 'blue'\]"):
            self.read(color="green")

    def test_list_of_reads_messages_by_their_from_wire(self) -> None:
        self.assertEqual(self.read(points=[[1, 2], [3, 4]]).points, [_Point(1, 2), _Point(3, 4)])

    def test_list_of_with_bad_item_names_its_index(self) -> None:
        with self.assertRaisesRegex(WireError, r"\$\.points\[1\] must have 2 items, got 1"):
            self.read(points=[[1, 2], [3]])

    def test_list_of_with_bad_row_item_names_it(self) -> None:
        with self.assertRaisesRegex(WireError, r"\$\.points\[0\]\.y must be an integer"):
            self.read(points=[[1, "two"]])

    def test_list_of_with_non_array_raises_wire_error(self) -> None:
        with self.assertRaisesRegex(WireError, r"\$\.points must be an array"):
            self.read(points={})

    def test_json_object_or_passes_objects_through(self) -> None:
        self.assertEqual(self.read(extra={"any": [1]}).extra, {"any": [1]})

    def test_json_object_or_with_empty_object_returns_it(self) -> None:
        self.assertEqual(self.read(extra={}).extra, {})

    def test_json_object_or_with_non_object_raises_wire_error(self) -> None:
        with self.assertRaisesRegex(WireError, r"\$\.extra must be an object"):
            self.read(extra=[1])

    def test_from_wire_ignores_unknown_keys(self) -> None:
        self.assertEqual(self.read(unknown=1), self.read())

    def test_for_object_with_non_object_raises_wire_error(self) -> None:
        with self.assertRaisesRegex(WireError, r"\$ must be an object"):
            _Sample.from_wire([1, 2])

    def test_for_row_with_non_array_raises_wire_error(self) -> None:
        with self.assertRaisesRegex(WireError, r"\$ must be an array"):
            _Point.from_wire({"x": 1, "y": 2})

    def test_require_type_with_another_type_raises_wire_error(self) -> None:
        with self.assertRaisesRegex(WireError, r"\$\.type must be 'sample', got 'other'"):
            self.read(type="other")


class TestWireWritable(unittest.TestCase):
    def test_omit_none_leaves_unset_optional_fields_out(self) -> None:
        self.assertEqual(
            _Sample(count=5, label=None, points=[]).to_wire(),
            {"type": "sample", "count": 5, "points": [], "ratio": 0.5, "color": "red"},
        )

    def test_to_wire_round_trips_through_from_wire(self) -> None:
        sample = _Sample(count=5, label="a", points=[_Point(1, 2)], ratio=0.25, color=_Color.BLUE, extra={"k": "v"})

        self.assertEqual(_Sample.from_wire(sample.to_wire()), sample)


class TestWireParser(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = WireParser({"sample": _Sample.from_wire, "other": _Other.from_wire})

    def test_parse_reads_the_class_its_type_names(self) -> None:
        self.assertEqual(self.parser.parse({"type": "other"}), _Other())

    def test_parse_with_unknown_type_raises_wire_error(self) -> None:
        with self.assertRaisesRegex(WireError, "unexpected message type 'third'"):
            self.parser.parse({"type": "third"})

    def test_parse_of_non_object_raises_wire_error(self) -> None:
        with self.assertRaisesRegex(WireError, "unexpected message type None"):
            self.parser.parse([1])

    def test_parse_with_bad_message_of_known_type_raises_wire_error(self) -> None:
        with self.assertRaisesRegex(WireError, r"\$\.count is missing"):
            self.parser.parse({"type": "sample", "points": []})


class TestJsonLines(unittest.TestCase):
    def setUp(self) -> None:
        self.lines = JsonLines()

    def test_encode_returns_compact_json_ending_with_newline(self) -> None:
        self.assertEqual(JsonLines.encode({"id": 1, "method": "ping"}), b'{"id":1,"method":"ping"}\n')

    def test_encode_with_fallback_converts_unsupported_values(self) -> None:
        self.assertEqual(JsonLines.encode({"value": {1}}, fallback=lambda _: "a set"), b'{"value":"a set"}\n')

    def test_encode_without_fallback_raises_type_error_for_unsupported_values(self) -> None:
        with self.assertRaises(TypeError):
            JsonLines.encode({"value": {1}})

    def test_next_message_before_any_data_returns_none(self) -> None:
        self.assertIsNone(self.lines.next_message())

    def test_next_message_with_incomplete_line_returns_none(self) -> None:
        self.lines.feed(b'{"id": 1')

        self.assertIsNone(self.lines.next_message())

    def test_next_message_with_line_split_over_chunks_returns_message(self) -> None:
        self.lines.feed(b'{"id": ')
        self.lines.feed(b"7}\n")

        self.assertEqual(self.lines.next_message(), {"id": 7})

    def test_next_message_with_several_lines_returns_them_in_order(self) -> None:
        self.lines.feed(b'{"id": 1}\n{"id": 2}\n')

        messages = (self.lines.next_message(), self.lines.next_message(), self.lines.next_message())

        self.assertEqual(messages, ({"id": 1}, {"id": 2}, None))

    def test_next_message_skips_blank_lines(self) -> None:
        self.lines.feed(b'\n  \n{"id": 3}\n')

        self.assertEqual(self.lines.next_message(), {"id": 3})

    def test_next_message_with_invalid_json_raises_value_error(self) -> None:
        self.lines.feed(b"not json\n")

        with self.assertRaises(ValueError):
            self.lines.next_message()

    def test_next_message_with_non_object_raises_wire_error(self) -> None:
        self.lines.feed(b"[1, 2]\n")

        with self.assertRaises(WireError):
            self.lines.next_message()


if __name__ == "__main__":
    unittest.main()
