import unittest

from _vspyprof.agent_protocol.options import AgentOptions
from _vspyprof.collector.messages import FROM_EXTENSION
from _vspyprof.collector.options import CollectorOptions
from _vspyprof.wire import WireDecoder, WireEncoder


class TestCollectorOptions(unittest.TestCase):
    def setUp(self) -> None:
        self.decoder = WireDecoder(FROM_EXTENSION)

    def test_decode_without_keys_uses_defaults(self) -> None:
        self.assertEqual(self.decoder.decode('{"type": "CollectorOptions"}'), CollectorOptions())

    def test_decode_without_strip_launcher_strips_launcher_frames(self) -> None:
        options = self.decoder.decode('{"type": "CollectorOptions"}')

        assert isinstance(options, CollectorOptions)
        self.assertTrue(options.strip_launcher)

    def test_decode_reads_camel_case_keys(self) -> None:
        line = '{"type": "CollectorOptions", "rateHz": 250, "stripLauncher": true, "tracemallocFrames": 4}'

        self.assertEqual(
            self.decoder.decode(line), CollectorOptions(rate_hz=250, strip_launcher=True, tracemalloc_frames=4)
        )

    def test_encode_round_trips_through_decode(self) -> None:
        options = CollectorOptions(rate_hz=333, native=True, blocking=True, asyncio_debug=True)

        self.assertEqual(self.decoder.decode(WireEncoder().encode(options)), options)

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
