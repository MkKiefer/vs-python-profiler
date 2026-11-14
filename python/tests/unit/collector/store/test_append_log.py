import unittest

from _vscode_pyprof.collector.store.append_log import AppendLog


class TestAppendLog(unittest.TestCase):
    def setUp(self) -> None:
        self.log: AppendLog[str] = AppendLog()
        self.log.append("a")
        self.log.append("b")

    def test_len_returns_number_of_rows(self) -> None:
        self.assertEqual(len(self.log), 2)

    def test_rows_returns_every_row(self) -> None:
        self.assertEqual(self.log.rows(new_only=False), ["a", "b"])

    def test_rows_with_new_only_returns_rows_once(self) -> None:
        first = self.log.rows(new_only=True)
        second = self.log.rows(new_only=True)

        self.assertEqual((first, second), (["a", "b"], []))

    def test_rows_with_new_only_returns_rows_appended_since_previous_call(self) -> None:
        self.log.rows(new_only=True)
        self.log.append("c")

        self.assertEqual(self.log.rows(new_only=True), ["c"])

    def test_rows_without_new_only_does_not_mark_rows_as_handed_out(self) -> None:
        self.log.rows(new_only=False)

        self.assertEqual(self.log.rows(new_only=True), ["a", "b"])

    def test_rows_returns_copy_that_does_not_change_the_log(self) -> None:
        self.log.rows(new_only=False).append("x")

        self.assertEqual(len(self.log), 2)


if __name__ == "__main__":
    unittest.main()
