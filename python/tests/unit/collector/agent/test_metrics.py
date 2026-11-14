import unittest

from _vscode_pyprof.collector.agent.metrics import AgentEvent, AgentMetrics, LoopMetrics
from _vscode_pyprof.collector.agent.thread_name import ThreadName
from _vscode_pyprof.wire import WireError, WireReader


class TestAgentEvent(unittest.TestCase):
    def test_from_wire_separates_known_fields_from_extra(self) -> None:
        event = AgentEvent.from_wire(
            WireReader({"t": 12.5, "kind": "slow-callback", "message": "took 0.2s", "seconds": 0.2})
        )

        self.assertEqual(event, AgentEvent("slow-callback", "took 0.2s", 12.5, {"seconds": 0.2}))

    def test_from_wire_without_kind_defaults_to_asyncio(self) -> None:
        self.assertEqual(AgentEvent.from_wire(WireReader({"message": "x"})).kind, "asyncio")

    def test_from_wire_without_time_has_no_perf_counter(self) -> None:
        self.assertIsNone(AgentEvent.from_wire(WireReader({"message": "x"})).perf_counter)


class TestAgentMetrics(unittest.TestCase):
    def test_from_wire_with_bare_message_has_no_measurements(self) -> None:
        metrics = AgentMetrics.from_wire(WireReader({"type": "metrics"}))

        self.assertEqual(metrics, AgentMetrics(threads=[], traced=None, traced_peak=None, loops=[], events=[]))

    def test_from_wire_reads_threads(self) -> None:
        metrics = AgentMetrics.from_wire(WireReader({"threads": [[1, 101, "MainThread"]]}))

        self.assertEqual(metrics.threads, [ThreadName(1, 101, "MainThread")])

    def test_from_wire_while_tracing_reads_traced_memory(self) -> None:
        metrics = AgentMetrics.from_wire(WireReader({"traced": 1000, "tracedPeak": 2000}))

        self.assertEqual((metrics.traced, metrics.traced_peak), (1000, 2000))

    def test_from_wire_with_traced_but_no_peak_raises_wire_error(self) -> None:
        with self.assertRaises(WireError):
            AgentMetrics.from_wire(WireReader({"traced": 1000}))

    def test_from_wire_reads_loops_with_and_without_task_count(self) -> None:
        message = WireReader({"loops": [{"lagMs": 3.5, "tasks": 4}, {"lagMs": 1.0, "tasks": None}]})

        self.assertEqual(AgentMetrics.from_wire(message).loops, [LoopMetrics(3.5, 4), LoopMetrics(1.0, None)])

    def test_from_wire_skips_events_that_are_not_objects(self) -> None:
        metrics = AgentMetrics.from_wire(WireReader({"events": ["oops", {"kind": "asyncio", "message": "m"}]}))

        self.assertEqual([event.message for event in metrics.events], ["m"])


if __name__ == "__main__":
    unittest.main()
