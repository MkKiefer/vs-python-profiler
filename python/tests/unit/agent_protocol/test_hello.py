import unittest

from _vscode_pyprof.agent_protocol.hello import AgentHello, ThreadName
from _vscode_pyprof.wire import WireError


class TestThreadName(unittest.TestCase):
    def test_from_wire_reads_ident_native_id_and_name(self) -> None:
        self.assertEqual(ThreadName.from_wire([1, 101, "MainThread"]), ThreadName(1, 101, "MainThread"))

    def test_from_wire_with_missing_id_reads_none(self) -> None:
        self.assertEqual(ThreadName.from_wire([None, 101, "starting"]), ThreadName(None, 101, "starting"))

    def test_from_wire_with_another_length_raises_wire_error(self) -> None:
        with self.assertRaises(WireError):
            ThreadName.from_wire([1, 101])

    def test_to_wire_is_ident_native_id_and_name(self) -> None:
        self.assertEqual(ThreadName(1, 101, "MainThread").to_wire(), [1, 101, "MainThread"])

    def test_ids_returns_native_id_before_ident(self) -> None:
        self.assertEqual(ThreadName(1, 101, "MainThread").ids(), [101, 1])

    def test_ids_leaves_out_unknown_ids(self) -> None:
        self.assertEqual(ThreadName(None, 101, "starting").ids(), [101])


class TestAgentHello(unittest.TestCase):
    def setUp(self) -> None:
        self.hello = AgentHello(
            token="secret",
            pid=12,
            executable="/usr/bin/python3.15",
            argv=["app.py", "1"],
            cwd="/work",
            version="3.15.2",
            threads=[ThreadName(1, 101, "MainThread")],
        )

    def test_to_wire_is_tagged_as_hello_message(self) -> None:
        self.assertEqual(self.hello.to_wire()["type"], "hello")

    def test_to_wire_round_trips_through_from_wire(self) -> None:
        self.assertEqual(AgentHello.from_wire(self.hello.to_wire()), self.hello)

    def test_from_wire_without_optional_fields_reads_none(self) -> None:
        hello = AgentHello.from_wire({"type": "hello", "token": "secret", "pid": 12, "argv": [], "threads": []})

        self.assertEqual(hello, AgentHello("secret", 12, None, [], None, None, []))

    def test_from_wire_without_pid_raises_wire_error(self) -> None:
        with self.assertRaisesRegex(WireError, r"\$\.pid is missing"):
            AgentHello.from_wire({"type": "hello", "token": "secret", "argv": [], "threads": []})

    def test_from_wire_of_another_message_type_raises_wire_error(self) -> None:
        with self.assertRaisesRegex(WireError, "type must be 'hello'"):
            AgentHello.from_wire(self.hello.to_wire() | {"type": "metrics"})


if __name__ == "__main__":
    unittest.main()
