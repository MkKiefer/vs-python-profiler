import unittest

from _vscode_pyprof.collector.store.sample_columns import SampleColumns


class TestSampleColumns(unittest.TestCase):
    def setUp(self) -> None:
        self.columns = SampleColumns()
        self.columns.append(1.0, 11, 0, 3)
        self.columns.append(2.0, 12, 1, 0)

    def test_len_returns_number_of_samples(self) -> None:
        self.assertEqual(len(self.columns), 2)

    def test_to_wire_returns_all_columns(self) -> None:
        self.assertDictEqual(
            self.columns.to_wire(new_only=False), {"t": [1.0, 2.0], "tid": [11, 12], "stack": [0, 1], "status": [3, 0]}
        )

    def test_to_wire_with_new_only_returns_only_samples_added_since_previous_call(self) -> None:
        self.columns.to_wire(new_only=True)
        self.columns.append(3.0, 13, 2, 1)

        self.assertDictEqual(
            self.columns.to_wire(new_only=True), {"t": [3.0], "tid": [13], "stack": [2], "status": [1]}
        )

    def test_to_wire_without_new_only_leaves_new_samples_unreported(self) -> None:
        self.columns.to_wire(new_only=False)

        self.assertEqual(self.columns.to_wire(new_only=True)["t"], [1.0, 2.0])


if __name__ == "__main__":
    unittest.main()
