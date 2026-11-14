import unittest

from _vscode_pyprof.agent_protocol.address import AgentAddress


class TestAgentAddress(unittest.TestCase):
    def test_parse_reads_host_port_and_token(self) -> None:
        self.assertEqual(AgentAddress.parse("127.0.0.1:5123:abc123"), AgentAddress("127.0.0.1", 5123, "abc123"))

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


if __name__ == "__main__":
    unittest.main()
