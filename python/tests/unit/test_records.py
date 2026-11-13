import unittest

from _vscode_pyprof.records import AllocationSite, MemorySnapshot, SampleColumns, TaskRecord


class TestTaskRecord(unittest.TestCase):
    def test_to_wire_uses_model_field_names(self) -> None:
        record = TaskRecord(task_id=5, name="worker", parent=None, thread=1, start=10.0, stack=3, state="waiting")

        self.assertDictEqual(
            record.to_wire(),
            {
                "id": 5,
                "name": "worker",
                "parent": None,
                "thread": 1,
                "start": 10.0,
                "end": None,
                "stack": 3,
                "state": "waiting",
            },
        )


class TestMemorySnapshot(unittest.TestCase):
    def test_to_wire_flattens_sites_into_entries(self) -> None:
        snapshot = MemorySnapshot(
            snapshot_id=1,
            label="A",
            t=12.5,
            total_size=300,
            total_count=3,
            other_size=0,
            other_count=0,
            traced=400,
            peak=500,
            take_ms=1.5,
            sites=(AllocationSite(stack=4, size=200, count=2), AllocationSite(stack=7, size=100, count=1)),
        )

        wire = snapshot.to_wire()

        self.assertEqual(wire["entries"], [[4, 200, 2], [7, 100, 1]])
        self.assertEqual((wire["id"], wire["label"], wire["totalSize"]), (1, "A", 300))


class TestSampleColumns(unittest.TestCase):
    def setUp(self) -> None:
        self.columns = SampleColumns()
        self.columns.append(1.0, 11, 0, 3)
        self.columns.append(2.0, 12, 1, 0)

    def test_len_returns_number_of_samples(self) -> None:
        self.assertEqual(len(self.columns), 2)

    def test_to_wire_returns_all_columns(self) -> None:
        self.assertDictEqual(
            self.columns.to_wire(), {"t": [1.0, 2.0], "tid": [11, 12], "stack": [0, 1], "status": [3, 0]}
        )

    def test_to_wire_with_start_returns_only_newer_samples(self) -> None:
        self.assertDictEqual(self.columns.to_wire(1), {"t": [2.0], "tid": [12], "stack": [1], "status": [0]})


if __name__ == "__main__":
    unittest.main()
