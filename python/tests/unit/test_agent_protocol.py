import json
import unittest

from _vscode_pyprof.agent_protocol import AgentAddress, AgentCommand, AgentMessageType, EventKind


class TestAgentAddress(unittest.TestCase):
    def test_parse_reads_host_port_and_token(self) -> None:
        address = AgentAddress.parse("127.0.0.1:5123:abc123")

        self.assertEqual((address.host, address.port, address.token), ("127.0.0.1", 5123, "abc123"))

    def test_parse_with_colons_in_host_keeps_them_in_host(self) -> None:
        address = AgentAddress.parse("::1:5123:abc123")

        self.assertEqual((address.host, address.port), ("::1", 5123))

    def test_parse_with_missing_part_raises_value_error(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            AgentAddress.parse("5123:abc123")

        self.assertIn("expected host:port:token", str(ctx.exception))

    def test_parse_with_non_numeric_port_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            AgentAddress.parse("127.0.0.1:http:abc123")

    def test_str_round_trips_through_parse(self) -> None:
        self.assertEqual(str(AgentAddress.parse("127.0.0.1:5123:abc123")), "127.0.0.1:5123:abc123")


class TestProtocolNames(unittest.TestCase):
    def test_names_serialise_as_their_wire_value(self) -> None:
        message = {
            "type": AgentMessageType.RESULT,
            "method": AgentCommand.OBJECT_COUNTS,
            "kind": EventKind.SLOW_CALLBACK,
        }

        self.assertEqual(
            json.loads(json.dumps(message)), {"type": "result", "method": "object_counts", "kind": "slow-callback"}
        )

    def test_names_compare_equal_to_their_wire_value(self) -> None:
        self.assertEqual(AgentMessageType.HELLO, "hello")
        handlers: dict[str, int] = {AgentCommand.PING: 1}
        self.assertEqual(handlers["ping"], 1)


if __name__ == "__main__":
    unittest.main()
