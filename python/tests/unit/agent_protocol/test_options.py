import unittest

from _vscode_pyprof.agent_protocol.messages import TO_AGENT
from _vscode_pyprof.agent_protocol.options import AgentOptions
from _vscode_pyprof.wire import WireDecoder, WireEncoder


class TestAgentOptions(unittest.TestCase):
    def setUp(self) -> None:
        self.decoder = WireDecoder(TO_AGENT)

    def test_decode_without_keys_returns_defaults(self) -> None:
        self.assertEqual(self.decoder.decode('{"type": "AgentOptions"}'), AgentOptions())

    def test_decode_reads_camel_case_keys(self) -> None:
        line = '{"type": "AgentOptions", "tracemalloc": true, "tracemallocFrames": 8, "slowCallbackMs": 50}'

        self.assertEqual(
            self.decoder.decode(line), AgentOptions(tracemalloc=True, tracemalloc_frames=8, slow_callback_ms=50)
        )

    def test_encode_round_trips_through_decode(self) -> None:
        options = AgentOptions(tracemalloc=True, tracemalloc_frames=4, asyncio_debug=True, slow_callback_ms=12.5)

        self.assertEqual(self.decoder.decode(WireEncoder().encode(options)), options)


if __name__ == "__main__":
    unittest.main()
