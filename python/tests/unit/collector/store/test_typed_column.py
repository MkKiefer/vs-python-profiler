import unittest
from array import array

from _vspyprof.collector.store.typed_column import TypedColumn


class TestTypedColumn(unittest.TestCase):
    def setUp(self) -> None:
        self.column: TypedColumn[int] = TypedColumn(array("q"))
        for value in (5, 6, 7):
            self.column.append(value)

    def test_len_returns_number_of_values(self) -> None:
        self.assertEqual(len(self.column), 3)

    def test_values_returns_all_values_as_list(self) -> None:
        self.assertEqual(self.column.values(), [5, 6, 7])

    def test_values_with_stop_returns_the_first_values(self) -> None:
        self.assertEqual(self.column.values(2), [5, 6])

    def test_new_values_returns_values_appended_since_previous_call(self) -> None:
        self.column.new_values()
        self.column.append(8)

        self.assertEqual(self.column.new_values(), [8])

    def test_values_leaves_new_values_unreported(self) -> None:
        self.column.values()

        self.assertEqual(self.column.new_values(), [5, 6, 7])

    def test_chunks_splits_the_first_values_into_lists_of_size(self) -> None:
        self.column.append(8)

        self.assertEqual(list(self.column.chunks(4, 3)), [[5, 6, 7], [8]])

    def test_chunks_ignores_values_appended_after_stop(self) -> None:
        self.assertEqual(list(self.column.chunks(2, 10)), [[5, 6]])

    def test_append_value_out_of_range_raises_overflow_error(self) -> None:
        column: TypedColumn[int] = TypedColumn(array("B"))

        with self.assertRaises(OverflowError):
            column.append(256)


if __name__ == "__main__":
    unittest.main()
