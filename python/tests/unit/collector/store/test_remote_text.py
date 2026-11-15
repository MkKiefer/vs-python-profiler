import unittest

from _vspyprof.collector.store.remote_text import CorruptTextError, RemoteText
from tests.unit.torn_text import TornText


class TestRemoteText(unittest.TestCase):
    def test_checked_with_valid_text_returns_it(self) -> None:
        text = "/srv/app/main.py"

        self.assertIs(RemoteText.checked(text), text)

    def test_checked_with_empty_text_returns_it(self) -> None:
        self.assertEqual(RemoteText.checked(""), "")

    def test_checked_with_torn_text_raises_corrupt_text_error(self) -> None:
        with self.assertRaises(CorruptTextError):
            RemoteText.checked(TornText("/srv/app/main.py"))

    def test_corrupt_text_error_counts_as_value_error(self) -> None:
        self.assertTrue(issubclass(CorruptTextError, ValueError))


if __name__ == "__main__":
    unittest.main()
