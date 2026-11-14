import unittest

from _vscode_pyprof.agent_protocol.hello import ThreadName
from _vscode_pyprof.agent_protocol.metrics import AgentEvent, AgentMetrics, EventDetails, LoopMetrics, TracedMemory
from _vscode_pyprof.wire import WireError, WireReader


class TestLoopMetrics(unittest.TestCase):
    def test_to_wire_round_trips_through_from_wire(self) -> None:
        loop = LoopMetrics(loop_id=7, thread="MainThread", lag_ms=3.5, tasks=4)

        self.assertEqual(LoopMetrics.from_wire(WireReader(loop.to_wire())), loop)

    def test_from_wire_without_task_count_reads_none(self) -> None:
        loop = LoopMetrics.from_wire(WireReader({"loop": 7, "thread": "MainThread", "lagMs": 1.0, "tasks": None}))

        self.assertIsNone(loop.tasks)

    def test_from_wire_without_lag_raises_wire_error(self) -> None:
        with self.assertRaises(WireError):
            LoopMetrics.from_wire(WireReader({"loop": 7}))


class TestEventDetails(unittest.TestCase):
    def test_to_wire_contains_only_known_fields(self) -> None:
        self.assertEqual(
            EventDetails(seconds=0.2, handle="<Handle work()>").to_wire(), {"seconds": 0.2, "handle": "<Handle work()>"}
        )

    def test_to_wire_without_details_is_empty(self) -> None:
        self.assertEqual(EventDetails().to_wire(), {})

    def test_to_wire_round_trips_through_from_wire(self) -> None:
        details = EventDetails(thread="MainThread", seconds=0.2, handle="h", file="app.py", line=12)

        self.assertEqual(EventDetails.from_wire(WireReader(details.to_wire())), details)


class TestAgentEvent(unittest.TestCase):
    def test_from_wire_reads_kind_message_time_and_details(self) -> None:
        event = AgentEvent.from_wire(
            WireReader({"t": 12.5, "kind": "slow-callback", "message": "took 0.2s", "seconds": 0.2})
        )

        self.assertEqual(event, AgentEvent("slow-callback", "took 0.2s", 12.5, EventDetails(seconds=0.2)))

    def test_from_wire_without_kind_defaults_to_asyncio(self) -> None:
        self.assertEqual(AgentEvent.from_wire(WireReader({"message": "x"})).kind, "asyncio")

    def test_from_wire_without_time_has_no_perf_counter(self) -> None:
        self.assertIsNone(AgentEvent.from_wire(WireReader({"message": "x"})).perf_counter)

    def test_to_wire_round_trips_through_from_wire(self) -> None:
        event = AgentEvent(
            "never-awaited", "coroutine 'work' was never awaited", 3.0, EventDetails(file="a.py", line=4)
        )

        self.assertEqual(AgentEvent.from_wire(WireReader(event.to_wire())), event)

    def test_to_wire_without_time_leaves_it_out(self) -> None:
        self.assertEqual(AgentEvent("asyncio", "m").to_wire(), {"kind": "asyncio", "message": "m"})


class TestAgentMetrics(unittest.TestCase):
    def test_from_wire_with_bare_message_has_no_measurements(self) -> None:
        metrics = AgentMetrics.from_wire(WireReader({"type": "metrics"}))

        self.assertEqual(metrics, AgentMetrics(threads=[], traced=None, loops=[], events=[]))

    def test_from_wire_while_tracing_reads_traced_memory(self) -> None:
        metrics = AgentMetrics.from_wire(WireReader({"traced": 1000, "tracedPeak": 2000}))

        self.assertEqual(metrics.traced, TracedMemory(current=1000, peak=2000))

    def test_from_wire_with_traced_but_no_peak_raises_wire_error(self) -> None:
        with self.assertRaises(WireError):
            AgentMetrics.from_wire(WireReader({"traced": 1000}))

    def test_from_wire_skips_events_that_are_not_objects(self) -> None:
        metrics = AgentMetrics.from_wire(WireReader({"events": ["oops", {"kind": "asyncio", "message": "m"}]}))

        self.assertEqual([event.message for event in metrics.events], ["m"])

    def test_to_wire_is_tagged_as_metrics_message(self) -> None:
        self.assertEqual(AgentMetrics(threads=[]).to_wire()["type"], "metrics")

    def test_to_wire_without_tracing_leaves_traced_memory_out(self) -> None:
        self.assertNotIn("traced", AgentMetrics(threads=[]).to_wire())

    def test_to_wire_round_trips_through_from_wire(self) -> None:
        metrics = AgentMetrics(
            threads=[ThreadName(1, 101, "MainThread")],
            traced=TracedMemory(1000, 2000),
            loops=[LoopMetrics(7, "MainThread", 3.5, 4)],
            events=[AgentEvent("slow-callback", "took 0.2s", 12.5, EventDetails(seconds=0.2))],
        )

        self.assertEqual(AgentMetrics.from_wire(WireReader(metrics.to_wire())), metrics)


if __name__ == "__main__":
    unittest.main()
