import unittest

from _vscode_pyprof.agent_protocol.options import AgentOptions
from _vscode_pyprof.collector.options import CollectorOptions
from _vscode_pyprof.wire import WireReader


class TestCollectorOptions(unittest.TestCase):
    def test_from_wire_with_empty_object_uses_defaults(self) -> None:
        options = CollectorOptions.from_wire(WireReader({}))

        self.assertEqual(options, CollectorOptions())

    def test_from_wire_with_null_value_keeps_default(self) -> None:
        options = CollectorOptions.from_wire(WireReader({"rateHz": None}))

        self.assertEqual(options.rate_hz, 1000)

    def test_from_wire_reads_camel_case_keys(self) -> None:
        raw = WireReader({"rateHz": 250, "stripLauncher": True, "slowCallbackMs": 20, "tracemallocFrames": 4})

        options = CollectorOptions.from_wire(raw)

        self.assertEqual(
            (options.rate_hz, options.strip_launcher, options.slow_callback_ms, options.tracemalloc_frames),
            (250, True, 20.0, 4),
        )

    def test_from_wire_with_zero_rate_clamps_to_one(self) -> None:
        options = CollectorOptions.from_wire(WireReader({"rateHz": 0}))

        self.assertEqual(options.rate_hz, 1)

    def test_to_wire_round_trips_through_from_wire(self) -> None:
        options = CollectorOptions(rate_hz=333, native=True, blocking=True, asyncio_debug=True)

        restored = CollectorOptions.from_wire(WireReader(options.to_wire()))

        self.assertEqual(restored, options)

    def test_agent_options_contains_only_agent_settings(self) -> None:
        options = CollectorOptions(tracemalloc=True, tracemalloc_frames=8)

        agent_options = options.agent_options()

        self.assertEqual(agent_options, AgentOptions(tracemalloc=True, tracemalloc_frames=8))

    def test_with_tracemalloc_returns_changed_copy(self) -> None:
        options = CollectorOptions()

        changed = options.with_tracemalloc(True)

        self.assertEqual((options.tracemalloc, changed.tracemalloc), (False, True))

    def test_with_asyncio_debug_returns_changed_copy(self) -> None:
        options = CollectorOptions()

        changed = options.with_asyncio_debug(True)

        self.assertEqual((options.asyncio_debug, changed.asyncio_debug), (False, True))


if __name__ == "__main__":
    unittest.main()
