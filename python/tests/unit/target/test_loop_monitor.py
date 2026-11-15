import asyncio
import threading
import time
import unittest

from _vspyprof.agent_protocol.metrics import AgentEvent
from _vspyprof.target.asyncio_debug import AsyncioDebugCapture
from _vspyprof.target.loop_monitor import LoopMonitor


class TestLoopMonitor(unittest.TestCase):
    def setUp(self) -> None:
        self.events: list[AgentEvent] = []
        self.monitor = LoopMonitor(AsyncioDebugCapture(self.events.append))
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, name="loop-thread", daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_loop)
        self.addCleanup(self.monitor.set_debug, False)
        self.run_on_loop()  # the loop is running once it has executed something

    def stop_loop(self) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(5)
        self.loop.close()

    def run_on_loop(self) -> None:
        """Returns after the loop has run everything scheduled before this call."""
        asyncio.run_coroutine_threadsafe(asyncio.sleep(0), self.loop).result(5)

    def test_probe_finds_running_loop(self) -> None:
        self.monitor.probe(time.perf_counter())

        self.assertEqual(self.monitor.loop_count, 1)

    def test_take_metrics_reports_loop_with_thread_name_and_lag(self) -> None:
        self.monitor.probe(time.perf_counter())
        self.run_on_loop()

        metrics = self.monitor.take_metrics(time.perf_counter())

        self.assertEqual([loop.thread for loop in metrics], ["loop-thread"])
        self.assertEqual(metrics[0].loop_id, id(self.loop))
        self.assertGreaterEqual(metrics[0].lag_ms, 0.0)
        self.assertEqual(metrics[0].tasks, 0)

    def test_take_metrics_with_unanswered_probe_reports_time_blocked_so_far(self) -> None:
        release = threading.Event()
        self.addCleanup(release.set)
        self.loop.call_soon_threadsafe(release.wait, 5)
        sent = time.perf_counter()
        self.monitor.probe(sent)

        metrics = self.monitor.take_metrics(sent + 0.75)[0]

        self.assertGreaterEqual(metrics.lag_ms, 750.0)

    def test_discard_pending_ignores_probe_answered_after_the_pause(self) -> None:
        release = threading.Event()
        self.addCleanup(release.set)
        self.loop.call_soon_threadsafe(release.wait, 5)
        self.monitor.probe(time.perf_counter())
        self.monitor.discard_pending()
        time.sleep(0.3)  # the pause the probe must not report
        release.set()
        self.run_on_loop()

        metrics = self.monitor.take_metrics(time.perf_counter())[0]

        self.assertLess(metrics.lag_ms, 300.0)

    def test_probe_after_discard_pending_measures_afresh(self) -> None:
        release = threading.Event()
        self.addCleanup(release.set)
        self.loop.call_soon_threadsafe(release.wait, 5)
        self.monitor.probe(time.perf_counter())
        self.monitor.discard_pending()
        sent = time.perf_counter()
        self.monitor.probe(sent)

        metrics = self.monitor.take_metrics(sent + 0.5)[0]

        self.assertGreaterEqual(metrics.lag_ms, 500.0)

    def test_probe_forgets_loop_that_stopped(self) -> None:
        self.monitor.probe(time.perf_counter())
        self.run_on_loop()
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(5)

        self.monitor.probe(time.perf_counter())

        self.assertEqual(self.monitor.loop_count, 0)

    def test_set_debug_enables_debug_mode_with_slow_callback_threshold(self) -> None:
        self.monitor.set_debug(True, slow_callback_ms=50.0)
        self.run_on_loop()

        self.assertTrue(self.monitor.debug)
        self.assertEqual((self.loop.get_debug(), self.loop.slow_callback_duration), (True, 0.05))

    def test_set_debug_with_new_threshold_while_enabled_updates_loops(self) -> None:
        self.monitor.set_debug(True, slow_callback_ms=50.0)
        self.run_on_loop()

        self.monitor.set_debug(True, slow_callback_ms=250.0)
        self.run_on_loop()

        self.assertEqual((self.loop.get_debug(), self.loop.slow_callback_duration), (True, 0.25))

    def test_set_debug_false_restores_normal_mode(self) -> None:
        self.monitor.set_debug(True)
        self.run_on_loop()

        self.monitor.set_debug(False)
        self.run_on_loop()

        self.assertFalse(self.loop.get_debug())


if __name__ == "__main__":
    unittest.main()
