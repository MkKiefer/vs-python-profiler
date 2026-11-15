import unittest

from _vscode_pyprof.agent_protocol.metrics import TracedMemory
from tests.unit.collector.agent.agent_link_harness import AgentLinkTestCase


class TestAgentServer(AgentLinkTestCase):
    def test_address_contains_host_port_and_token(self) -> None:
        host, port, token = self.server.address.rsplit(":", 2)

        self.assertEqual(host, "127.0.0.1")
        self.assertGreater(int(port), 0)
        self.assertEqual(len(token), 32)

    def test_hello_with_valid_token_notifies_listener(self) -> None:
        connection = self.connect()

        self.assertEqual((connection.hello.pid, connection.hello.argv), (4242, ["app.py"]))
        self.assertTrue(connection.alive)

    def test_hello_with_wrong_token_closes_connection(self) -> None:
        self.agent.hello(token="wrong")

        self.assertTrue(self.agent.read_is_end_of_stream())
        self.assertFalse(self.listener.connected.is_set())

    def test_unsolicited_message_is_forwarded_to_listener(self) -> None:
        self.connect()

        self.agent.send(
            {"type": "AgentMetrics", "threads": [], "traced": {"type": "TracedMemory", "current": 100, "peak": 150}}
        )

        self.assertTrue(self.listener.message_received.wait(5))
        self.assertEqual(self.listener.metrics[0].traced, TracedMemory(100, 150))

    def test_first_message_that_is_not_a_hello_closes_connection(self) -> None:
        self.agent.send({"type": "AgentMetrics", "threads": []})

        self.assertTrue(self.agent.read_is_end_of_stream())
        self.assertFalse(self.listener.connected.is_set())


if __name__ == "__main__":
    unittest.main()
