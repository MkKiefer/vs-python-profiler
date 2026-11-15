import unittest
from dataclasses import dataclass, field
from enum import StrEnum

from _vscode_pyprof.wire import JsonLines, JsonObject, WireError, WireMessage, WireRow, read_one_of, wire


class _Color(StrEnum):
    RED = "red"
    BLUE = "blue"


@dataclass(frozen=True)
class _Point(WireRow):
    x: int
    y: int


@dataclass(frozen=True)
class _Sample(WireMessage):
    wire_type = "sample"

    rate_hz: int = field(metadata=wire(at_least=1))
    label: str | None
    points: list[_Point]
    color: _Color = _Color.RED
    perf_counter: float = field(default=0.0, metadata=wire("t"))
    extra: JsonObject = field(default_factory=dict)


@dataclass(frozen=True)
class _Other(WireMessage):
    wire_type = "other"

    ok: bool = field(default=True, init=False)


class TestWireMessageFromWire(unittest.TestCase):
    def read(self, **values: object) -> _Sample:
        return _Sample.from_wire({"type": "sample", "rateHz": 100, "points": []} | values)

    def test_from_wire_reads_camel_case_keys(self) -> None:
        self.assertEqual(self.read(rateHz=250).rate_hz, 250)

    def test_from_wire_reads_the_key_named_in_wire_metadata(self) -> None:
        self.assertEqual(self.read(t=2.5).perf_counter, 2.5)

    def test_from_wire_with_missing_key_uses_default(self) -> None:
        self.assertEqual((self.read().color, self.read().perf_counter), (_Color.RED, 0.0))

    def test_from_wire_with_null_uses_default(self) -> None:
        self.assertEqual(self.read(color=None).color, _Color.RED)

    def test_from_wire_with_missing_optional_field_reads_none(self) -> None:
        self.assertIsNone(self.read().label)

    def test_from_wire_with_missing_required_field_raises_wire_error(self) -> None:
        with self.assertRaisesRegex(WireError, r"\$\.points is missing"):
            _Sample.from_wire({"type": "sample", "rateHz": 100})

    def test_from_wire_with_number_below_at_least_raises_it(self) -> None:
        self.assertEqual(self.read(rateHz=0).rate_hz, 1)

    def test_from_wire_with_integral_float_for_int_reads_int(self) -> None:
        self.assertEqual(self.read(rateHz=250.0).rate_hz, 250)

    def test_from_wire_with_fractional_float_for_int_raises_wire_error(self) -> None:
        with self.assertRaisesRegex(WireError, r"\$\.rateHz must be an integer"):
            self.read(rateHz=2.5)

    def test_from_wire_with_boolean_for_int_raises_wire_error(self) -> None:
        with self.assertRaises(WireError):
            self.read(rateHz=True)

    def test_from_wire_with_integer_for_float_reads_float(self) -> None:
        self.assertEqual(self.read(t=3).perf_counter, 3.0)

    def test_from_wire_reads_enum_values(self) -> None:
        self.assertIs(self.read(color="blue").color, _Color.BLUE)

    def test_from_wire_with_unknown_enum_value_raises_wire_error(self) -> None:
        with self.assertRaisesRegex(WireError, r"\$\.color must be one of \['red', 'blue'\]"):
            self.read(color="green")

    def test_from_wire_reads_lists_of_rows(self) -> None:
        self.assertEqual(self.read(points=[[1, 2], [3, 4]]).points, [_Point(1, 2), _Point(3, 4)])

    def test_from_wire_with_bad_list_item_names_its_index(self) -> None:
        with self.assertRaisesRegex(WireError, r"\$\.points\[1\] must have 2 items"):
            self.read(points=[[1, 2], [3]])

    def test_from_wire_passes_json_objects_through(self) -> None:
        self.assertEqual(self.read(extra={"any": [1]}).extra, {"any": [1]})

    def test_from_wire_ignores_unknown_keys(self) -> None:
        self.assertEqual(self.read(unknown=1), self.read())

    def test_from_wire_of_non_object_raises_wire_error(self) -> None:
        with self.assertRaisesRegex(WireError, r"\$ must be an object"):
            _Sample.from_wire([1, 2])

    def test_from_wire_with_another_type_raises_wire_error(self) -> None:
        with self.assertRaisesRegex(WireError, r"\$\.type must be 'sample', got 'other'"):
            self.read(type="other")

    def test_from_wire_leaves_fields_without_init_at_their_default(self) -> None:
        self.assertEqual(_Other.from_wire({"type": "other", "ok": False}), _Other())


class TestWireMessageToWire(unittest.TestCase):
    def test_to_wire_writes_camel_case_keys_rows_enums_and_type(self) -> None:
        sample = _Sample(rate_hz=5, label="a", points=[_Point(1, 2)], color=_Color.BLUE, perf_counter=1.5)

        self.assertEqual(
            sample.to_wire(),
            {"type": "sample", "rateHz": 5, "label": "a", "points": [[1, 2]], "color": "blue", "t": 1.5, "extra": {}},
        )

    def test_to_wire_leaves_none_out(self) -> None:
        self.assertNotIn("label", _Sample(rate_hz=5, label=None, points=[]).to_wire())

    def test_to_wire_round_trips_through_from_wire(self) -> None:
        sample = _Sample(rate_hz=5, label=None, points=[_Point(1, 2)], extra={"k": "v"})

        self.assertEqual(_Sample.from_wire(sample.to_wire()), sample)

    def test_to_wire_writes_fields_without_init(self) -> None:
        self.assertEqual(_Other().to_wire(), {"ok": True, "type": "other"})


class TestReadOneOf(unittest.TestCase):
    def test_read_one_of_reads_the_class_its_type_names(self) -> None:
        self.assertEqual(read_one_of({"type": "other"}, _Sample, _Other), _Other())

    def test_read_one_of_with_unknown_type_raises_wire_error(self) -> None:
        with self.assertRaisesRegex(WireError, "unexpected message type 'third'"):
            read_one_of({"type": "third"}, _Sample, _Other)


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
