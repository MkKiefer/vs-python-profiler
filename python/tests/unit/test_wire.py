import unittest

from _vscode_pyprof.wire import JsonLines, WireError, WireReader


class TestWireReader(unittest.TestCase):
    def test_of_with_json_object_wraps_its_keys(self) -> None:
        reader = WireReader.of({"pid": 7})

        self.assertEqual(reader.get_int("pid"), 7)

    def test_of_with_non_object_reads_as_empty(self) -> None:
        reader = WireReader.of([1, 2, 3])

        self.assertEqual(reader.to_dict(), {})

    def test_has_with_null_value_returns_false(self) -> None:
        reader = WireReader({"label": None})

        self.assertFalse(reader.has("label"))

    def test_get_int_with_integral_float_returns_int(self) -> None:
        reader = WireReader({"rateHz": 250.0})

        self.assertEqual(reader.get_int("rateHz"), 250)

    def test_get_int_with_numeric_string_returns_int(self) -> None:
        reader = WireReader({"pid": "4321"})

        self.assertEqual(reader.get_int("pid"), 4321)

    def test_get_int_with_missing_key_returns_default(self) -> None:
        reader = WireReader({})

        self.assertEqual(reader.get_int("limit", 60), 60)

    def test_get_int_with_missing_key_and_no_default_raises_wire_error(self) -> None:
        reader = WireReader({})

        with self.assertRaises(WireError) as ctx:
            reader.get_int("pid")

        self.assertIn("pid", str(ctx.exception))

    def test_get_int_with_boolean_raises_wire_error(self) -> None:
        reader = WireReader({"pid": True})

        with self.assertRaises(WireError):
            reader.get_int("pid")

    def test_get_float_with_integer_returns_float(self) -> None:
        reader = WireReader({"slowMs": 50})

        self.assertEqual(reader.get_float("slowMs"), 50.0)

    def test_get_float_with_string_raises_wire_error(self) -> None:
        reader = WireReader({"slowMs": "fast"})

        with self.assertRaises(WireError):
            reader.get_float("slowMs", 100.0)

    def test_get_bool_with_null_returns_default(self) -> None:
        reader = WireReader({"inject": None})

        self.assertTrue(reader.get_bool("inject", True))

    def test_get_bool_with_false_overrides_true_default(self) -> None:
        reader = WireReader({"inject": False})

        self.assertFalse(reader.get_bool("inject", True))

    def test_get_str_with_non_string_raises_wire_error(self) -> None:
        reader = WireReader({"path": 12})

        with self.assertRaises(WireError):
            reader.get_str("path")

    def test_get_optional_str_with_non_string_returns_none(self) -> None:
        reader = WireReader({"label": 12})

        self.assertIsNone(reader.get_optional_str("label"))

    def test_get_object_with_nested_object_returns_reader(self) -> None:
        reader = WireReader({"options": {"rateHz": 100}})

        self.assertEqual(reader.get_object("options").get_int("rateHz"), 100)

    def test_get_object_with_missing_key_returns_empty_reader(self) -> None:
        reader = WireReader({})

        self.assertEqual(reader.get_object("options").to_dict(), {})

    def test_get_list_with_non_list_returns_empty_list(self) -> None:
        reader = WireReader({"threads": "nope"})

        self.assertEqual(reader.get_list("threads"), [])

    def test_get_str_list_converts_items_to_strings(self) -> None:
        reader = WireReader({"argv": ["app.py", 8000]})

        self.assertListEqual(reader.get_str_list("argv"), ["app.py", "8000"])


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

        message = self.lines.next_message()

        assert message is not None
        self.assertEqual(message.get_int("id"), 7)

    def test_next_message_with_several_lines_returns_them_in_order(self) -> None:
        self.lines.feed(b'{"id": 1}\n{"id": 2}\n')

        first = self.lines.next_message()
        second = self.lines.next_message()

        assert first is not None and second is not None
        self.assertEqual((first.get_int("id"), second.get_int("id"), self.lines.next_message()), (1, 2, None))

    def test_next_message_skips_blank_lines(self) -> None:
        self.lines.feed(b'\n  \n{"id": 3}\n')

        message = self.lines.next_message()

        assert message is not None
        self.assertEqual(message.get_int("id"), 3)

    def test_next_message_with_invalid_json_raises_value_error(self) -> None:
        self.lines.feed(b"not json\n")

        with self.assertRaises(ValueError):
            self.lines.next_message()

    def test_next_message_with_non_object_reads_as_empty_message(self) -> None:
        self.lines.feed(b"[1, 2]\n")

        message = self.lines.next_message()

        assert message is not None
        self.assertEqual(message.to_dict(), {})


if __name__ == "__main__":
    unittest.main()
