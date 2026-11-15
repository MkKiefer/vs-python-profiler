import unittest

from _vspyprof.agent_protocol.hello import ThreadName
from _vspyprof.agent_protocol.messages import FROM_AGENT
from _vspyprof.agent_protocol.metrics import AgentEvent, AgentMetrics, EventDetails, LoopMetrics, TracedMemory
from _vspyprof.wire import WireDecoder, WireEncoder


class TestAgentMetrics(unittest.TestCase):
    def setUp(self) -> None:
        self.encoder = WireEncoder()
        self.decoder = WireDecoder(FROM_AGENT)

    def test_encode_round_trips_through_the_collector_decoder(self) -> None:
        metrics = AgentMetrics(
            threads=[ThreadName(1, 101, "MainThread")],
            traced=TracedMemory(1000, 2000),
            loops=[LoopMetrics(7, "MainThread", 3.5, None)],
            events=[AgentEvent("slow-callback", "took 0.2s", 12.5, EventDetails(seconds=0.2))],
        )

        self.assertEqual(self.decoder.decode(self.encoder.encode(metrics)), metrics)

    def test_decode_with_threads_only_has_no_measurements(self) -> None:
        metrics = self.decoder.decode('{"type": "AgentMetrics", "threads": []}')

        self.assertEqual(metrics, AgentMetrics(threads=[], traced=None, loops=[], events=[]))

    def test_decode_of_event_without_time_or_details_has_neither(self) -> None:
        event = self.decoder.decode('{"type": "AgentEvent", "kind": "asyncio", "message": "x"}')

        self.assertEqual(event, AgentEvent("asyncio", "x", None, EventDetails()))


if __name__ == "__main__":
    unittest.main()
