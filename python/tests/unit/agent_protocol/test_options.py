import unittest

from _vscode_pyprof.agent_protocol.options import AgentOptions
from _vscode_pyprof.wire import WireReader


class TestAgentOptions(unittest.TestCase):
    def test_from_wire_with_empty_object_returns_defaults(self) -> None:
        self.assertEqual(AgentOptions.from_wire(WireReader({})), AgentOptions())

    def test_from_wire_reads_camel_case_names(self) -> None:
        raw = WireReader({"tracemalloc": True, "tracemallocFrames": 8, "asyncioDebug": True, "slowCallbackMs": 50})

        self.assertEqual(AgentOptions.from_wire(raw), AgentOptions(True, 8, True, 50.0))

    def test_from_wire_ignores_options_meant_for_the_collector(self) -> None:
        raw = WireReader({"rateHz": 200, "native": True, "tracemalloc": True})

        self.assertEqual(AgentOptions.from_wire(raw), AgentOptions(tracemalloc=True))

    def test_from_wire_with_zero_traceback_frames_uses_one(self) -> None:
        self.assertEqual(AgentOptions.from_wire(WireReader({"tracemallocFrames": 0})).tracemalloc_frames, 1)

    def test_from_json_without_text_returns_defaults(self) -> None:
        self.assertEqual((AgentOptions.from_json(None), AgentOptions.from_json("")), (AgentOptions(), AgentOptions()))

    def test_from_json_with_text_that_is_not_json_returns_defaults(self) -> None:
        self.assertEqual(AgentOptions.from_json("{not json"), AgentOptions())

    def test_from_json_with_value_of_wrong_type_returns_defaults(self) -> None:
        self.assertEqual(AgentOptions.from_json('{"tracemallocFrames": "many"}'), AgentOptions())

    def test_from_json_with_non_object_returns_defaults(self) -> None:
        self.assertEqual(AgentOptions.from_json("[1, 2]"), AgentOptions())

    def test_to_json_round_trips_through_from_json(self) -> None:
        options = AgentOptions(tracemalloc=True, tracemalloc_frames=4, asyncio_debug=True, slow_callback_ms=12.5)

        self.assertEqual(AgentOptions.from_json(options.to_json()), options)


if __name__ == "__main__":
    unittest.main()
