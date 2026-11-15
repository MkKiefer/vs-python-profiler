import unittest

from _vspyprof.collector.store.column_snapshot import ColumnSnapshot
from _vspyprof.collector.store.sample_columns import SampleColumns


class TestSampleColumns(unittest.TestCase):
    def setUp(self) -> None:
        self.columns = SampleColumns()
        self.columns.append(1.0, 11, 0, 3)
        self.columns.append(2.0, 12, 1, 0)

    def test_len_returns_number_of_samples(self) -> None:
        self.assertEqual(len(self.columns), 2)

    def test_to_wire_returns_all_columns(self) -> None:
        self.assertDictEqual(
            self.columns.to_profile(new_only=False),
            {"t": [1.0, 2.0], "tid": [11, 12], "stack": [0, 1], "status": [3, 0]},
        )

    def test_to_wire_with_new_only_returns_only_samples_added_since_previous_call(self) -> None:
        self.columns.to_profile(new_only=True)
        self.columns.append(3.0, 13, 2, 1)

        self.assertDictEqual(
            self.columns.to_profile(new_only=True), {"t": [3.0], "tid": [13], "stack": [2], "status": [1]}
        )

    def test_to_wire_without_new_only_leaves_new_samples_unreported(self) -> None:
        self.columns.to_profile(new_only=False)

        self.assertEqual(self.columns.to_profile(new_only=True)["t"], [1.0, 2.0])

    def test_append_keeps_thread_ids_beyond_32_bits(self) -> None:
        self.columns.append(3.0, 0x7F12_3456_7890, 2, 1)

        self.assertEqual(self.columns.to_profile(new_only=False)["tid"], [11, 12, 0x7F12_3456_7890])

    def test_append_keeps_the_status_bits_the_dashboard_reads(self) -> None:
        self.columns.append(3.0, 13, 2, 0x103)

        self.assertEqual(self.columns.to_profile(new_only=False)["status"], [3, 0, 0x03])

    def test_snapshot_holds_the_samples_present_when_taken(self) -> None:
        snapshot = self.columns.snapshot()
        self.columns.append(3.0, 13, 2, 1)

        t = snapshot["t"]
        assert isinstance(t, ColumnSnapshot)
        self.assertEqual(list(t.chunks(10)), [[1.0, 2.0]])


if __name__ == "__main__":
    unittest.main()
