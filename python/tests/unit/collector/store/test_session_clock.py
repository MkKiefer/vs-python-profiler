import time
import unittest

from _vspyprof.collector.store.session_clock import SessionClock


class TestSessionClock(unittest.TestCase):
    def setUp(self) -> None:
        self.before = time.perf_counter()
        self.clock = SessionClock()

    def test_now_is_not_negative_and_advances(self) -> None:
        first = self.clock.now()
        second = self.clock.now()

        self.assertGreaterEqual(first, 0.0)
        self.assertGreaterEqual(second, first)

    def test_from_perf_counter_converts_seconds_to_milliseconds(self) -> None:
        origin = self.clock.from_perf_counter(0.0)

        self.assertAlmostEqual(self.clock.from_perf_counter(1.5) - origin, 1500.0)

    def test_from_perf_counter_with_reading_before_session_start_is_not_positive(self) -> None:
        self.assertLessEqual(self.clock.from_perf_counter(self.before), 0.0)

    def test_from_perf_counter_ns_agrees_with_from_perf_counter(self) -> None:
        seconds = time.perf_counter() + 2.0

        self.assertAlmostEqual(
            self.clock.from_perf_counter_ns(int(seconds * 1e9)), self.clock.from_perf_counter(seconds), delta=1.0
        )


if __name__ == "__main__":
    unittest.main()
