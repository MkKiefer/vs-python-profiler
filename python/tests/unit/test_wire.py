import json
import unittest
from dataclasses import dataclass, field
from enum import StrEnum

from _vspyprof.wire import LineBuffer, Request, Response, WireDecoder, WireEncoder, WireError


class _Color(StrEnum):
    RED = "red"


@dataclass(frozen=True)
class _Point:
    x: int
    y: int


@dataclass(frozen=True)
class _Shape:
    line_width: float
    points: list[_Point]
    label: str | None = None
    color: str = "blue"
    tags: list[str] = field(default_factory=list)


class TestWireEncoder(unittest.TestCase):
    def setUp(self) -> None:
        self.encoder = WireEncoder()

    def test_encode_writes_one_line_with_type_and_camel_case_keys(self) -> None:
        line = self.encoder.encode(_Point(1, 2))

        self.assertEqual(line, b'{"type":"_Point","x":1,"y":2}\n')

    def test_to_json_writes_nested_dataclasses_typed(self) -> None:
        shape = _Shape(line_width=1.5, points=[_Point(1, 2)])

        self.assertEqual(
            self.encoder.to_json(shape),
            {
                "type": "_Shape",
                "lineWidth": 1.5,
                "points": [{"type": "_Point", "x": 1, "y": 2}],
                "label": None,
                "color": "blue",
                "tags": [],
            },
        )

    def test_to_json_writes_tuples_as_arrays_and_enums_as_values(self) -> None:
        self.assertEqual(self.encoder.to_json((_Color.RED, 1)), ["red", 1])

    def test_to_json_writes_dicts_as_they_are(self) -> None:
        payload = {"samples": {"t": [1, 2]}}

        self.assertIs(self.encoder.to_json(payload), payload)

    def test_to_text_writes_values_json_cannot_hold_as_their_repr(self) -> None:
        self.assertEqual(
            self.encoder.to_text(Response(1, result={"value": {1}})),
            json.dumps({"type": "Response", "id": 1, "result": {"value": "{1}"}, "error": None}, separators=(",", ":")),
        )


class TestWireDecoder(unittest.TestCase):
    def setUp(self) -> None:
        self.decoder = WireDecoder([_Shape, _Point, Request])

    def test_decode_round_trips_encode(self) -> None:
        shape = _Shape(line_width=2.0, points=[_Point(1, 2), _Point(3, 4)], label="a", tags=["x"])

        self.assertEqual(self.decoder.decode(WireEncoder().encode(shape)), shape)

    def test_decode_with_missing_keys_uses_the_dataclass_defaults(self) -> None:
        shape = self.decoder.decode('{"type": "_Shape", "lineWidth": 1, "points": []}')

        self.assertEqual(shape, _Shape(line_width=1, points=[], label=None, color="blue", tags=[]))

    def test_decode_reads_typed_objects_anywhere_in_the_value(self) -> None:
        request = self.decoder.decode('{"type": "Request", "id": 4, "body": {"type": "_Point", "x": 1, "y": 2}}')

        self.assertEqual(request, Request(4, _Point(1, 2)))

    def test_decode_keeps_objects_without_type_as_dicts(self) -> None:
        request = self.decoder.decode('{"type": "Request", "id": 4, "body": {"any": {"type": 1}}}')

        self.assertEqual(request, Request(4, {"any": {"type": 1}}))

    def test_decode_of_untyped_value_returns_it(self) -> None:
        self.assertEqual(self.decoder.decode("[1, 2]"), [1, 2])

    def test_decode_with_unknown_type_raises_wire_error_naming_its_path(self) -> None:
        with self.assertRaisesRegex(WireError, r"\$\.points\[0\] has unknown type 'Circle'"):
            self.decoder.decode('{"type": "_Shape", "lineWidth": 1, "points": [{"type": "Circle"}]}')

    def test_decode_with_missing_required_key_raises_wire_error(self) -> None:
        with self.assertRaisesRegex(WireError, r"\$ is not a _Point: .*'y'"):
            self.decoder.decode('{"type": "_Point", "x": 1}')

    def test_decode_with_unknown_key_raises_wire_error(self) -> None:
        with self.assertRaisesRegex(WireError, r"\$ is not a _Point: .*'z'"):
            self.decoder.decode('{"type": "_Point", "x": 1, "y": 2, "z": 3}')

    def test_decode_of_broken_json_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            self.decoder.decode("{not json")

    def test_constructor_with_two_models_of_one_name_raises_type_error(self) -> None:
        with self.assertRaisesRegex(TypeError, "two models are named '_Point'"):
            WireDecoder([_Point, _Point])

    def test_constructor_with_class_that_is_not_a_dataclass_raises_type_error(self) -> None:
        with self.assertRaisesRegex(TypeError, "_Color is not a dataclass"):
            WireDecoder([_Color])


class TestLineBuffer(unittest.TestCase):
    def setUp(self) -> None:
        self.lines = LineBuffer()

    def test_next_line_before_any_data_returns_none(self) -> None:
        self.assertIsNone(self.lines.next_line())

    def test_next_line_with_incomplete_line_returns_none(self) -> None:
        self.lines.feed(b'{"id": 1')

        self.assertIsNone(self.lines.next_line())

    def test_next_line_with_line_split_over_chunks_returns_it(self) -> None:
        self.lines.feed(b'{"id": ')
        self.lines.feed(b"7}\n")

        self.assertEqual(self.lines.next_line(), b'{"id": 7}')

    def test_next_line_returns_lines_in_order(self) -> None:
        self.lines.feed(b"a\nb\n")

        self.assertEqual((self.lines.next_line(), self.lines.next_line(), self.lines.next_line()), (b"a", b"b", None))

    def test_next_line_skips_blank_lines(self) -> None:
        self.lines.feed(b"\n  \nc\n")

        self.assertEqual(self.lines.next_line(), b"c")


if __name__ == "__main__":
    unittest.main()
