import unittest

from _vspyprof.agent_protocol.hello import AgentHello, ThreadName
from _vspyprof.agent_protocol.messages import FROM_AGENT
from _vspyprof.wire import WireDecoder, WireEncoder


class TestThreadName(unittest.TestCase):
    def test_ids_returns_native_id_before_ident(self) -> None:
        self.assertEqual(ThreadName(1, 101, "MainThread").ids(), [101, 1])

    def test_ids_leaves_out_unknown_ids(self) -> None:
        self.assertEqual(ThreadName(None, 101, "starting").ids(), [101])


class TestAgentHello(unittest.TestCase):
    def test_encode_round_trips_through_the_collector_decoder(self) -> None:
        hello = AgentHello(
            token="secret",
            pid=12,
            executable="/usr/bin/python3.15",
            argv=["app.py", "1"],
            cwd=None,
            version="3.15.2",
            threads=[ThreadName(1, None, "MainThread")],
        )

        self.assertEqual(WireDecoder(FROM_AGENT).decode(WireEncoder().encode(hello)), hello)


if __name__ == "__main__":
    unittest.main()
