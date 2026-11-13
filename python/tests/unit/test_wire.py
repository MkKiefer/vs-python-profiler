import unittest

from _vscode_pyprof.wire import WireError, WireReader


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


if __name__ == "__main__":
    unittest.main()
