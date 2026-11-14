import unittest

from _vscode_pyprof.collector.agent.thread_name import ThreadName


class TestThreadName(unittest.TestCase):
    def test_list_from_wire_reads_ident_native_id_and_name(self) -> None:
        threads = ThreadName.list_from_wire([[1, 101, "MainThread"], [2, 102, "worker"]])

        self.assertEqual(threads, [ThreadName(1, 101, "MainThread"), ThreadName(2, 102, "worker")])

    def test_list_from_wire_skips_entries_of_another_shape(self) -> None:
        threads = ThreadName.list_from_wire(["MainThread", [1, 101], [2, 102, "worker"], None])

        self.assertEqual(threads, [ThreadName(2, 102, "worker")])

    def test_list_from_wire_with_missing_id_reads_none(self) -> None:
        self.assertEqual(ThreadName.list_from_wire([[None, 101, "starting"]]), [ThreadName(None, 101, "starting")])

    def test_ids_returns_native_id_before_ident(self) -> None:
        self.assertEqual(ThreadName(1, 101, "MainThread").ids(), [101, 1])

    def test_ids_leaves_out_unknown_ids(self) -> None:
        self.assertEqual(ThreadName(None, 101, "starting").ids(), [101])


if __name__ == "__main__":
    unittest.main()
