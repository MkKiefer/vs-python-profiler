import json
import unittest

from _vscode_pyprof.agent_protocol.names import AgentCommand, AgentMessageType, EventKind


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
        handlers: dict[str, int] = {AgentCommand.PING: 1}

        self.assertEqual(AgentMessageType.HELLO, "hello")
        self.assertEqual(handlers["ping"], 1)


if __name__ == "__main__":
    unittest.main()
