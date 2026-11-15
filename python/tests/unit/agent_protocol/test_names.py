import json
import unittest

from _vscode_pyprof.agent_protocol.names import EventKind


class TestEventKind(unittest.TestCase):
    def test_event_kind_serialises_as_its_wire_value(self) -> None:
        self.assertEqual(json.dumps({"kind": EventKind.SLOW_CALLBACK}), '{"kind": "slow-callback"}')

    def test_event_kind_compares_equal_to_its_wire_value(self) -> None:
        self.assertEqual(EventKind.NEVER_AWAITED, "never-awaited")


if __name__ == "__main__":
    unittest.main()
