import unittest

from _vspyprof.agent_protocol.messages import TO_AGENT
from _vspyprof.agent_protocol.options import AgentOptions
from _vspyprof.target.agent import AgentRegistry
from _vspyprof.wire import WireDecoder, WireEncoder


class TestAgentRegistryReadOptions(unittest.TestCase):
    def setUp(self) -> None:
        self.decoder = WireDecoder(TO_AGENT)

    def read(self, text: str | None) -> AgentOptions:
        return AgentRegistry.read_options(self.decoder, text)

    def test_read_options_reads_the_line_the_collector_wrote(self) -> None:
        options = AgentOptions(tracemalloc=True, tracemalloc_frames=4)

        self.assertEqual(self.read(WireEncoder().to_text(options)), options)

    def test_read_options_without_text_returns_defaults(self) -> None:
        self.assertEqual((self.read(None), self.read("")), (AgentOptions(), AgentOptions()))

    def test_read_options_with_text_that_is_not_json_returns_defaults(self) -> None:
        self.assertEqual(self.read("{not json"), AgentOptions())

    def test_read_options_with_unknown_key_returns_defaults(self) -> None:
        self.assertEqual(self.read('{"type": "AgentOptions", "rateHz": 200}'), AgentOptions())

    def test_read_options_with_another_message_returns_defaults(self) -> None:
        self.assertEqual(self.read('{"type": "Ping"}'), AgentOptions())


if __name__ == "__main__":
    unittest.main()
