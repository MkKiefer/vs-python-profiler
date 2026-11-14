import json
import socket
import threading
import unittest

from _vscode_pyprof.collector.agent_link import AgentConnection, AgentError, AgentHello, AgentListener, AgentServer
from _vscode_pyprof.wire import JsonObject, WireReader


class _RecordingListener(AgentListener):
    def __init__(self) -> None:
        self.connected = threading.Event()
        self.closed = threading.Event()
        self.message_received = threading.Event()
        self.connection: AgentConnection | None = None
        self.messages: list[WireReader] = []

    def on_agent_hello(self, connection: AgentConnection) -> None:
        self.connection = connection
        self.connected.set()

    def on_agent_message(self, connection: AgentConnection, message: WireReader) -> None:
        self.messages.append(message)
        self.message_received.set()

    def on_agent_close(self, connection: AgentConnection) -> None:
        self.closed.set()


class _FakeAgent:
    """The target-process end of the connection, driven by the test."""

    def __init__(self, address: str) -> None:
        host, port, self.token = address.rsplit(":", 2)
        self._socket = socket.create_connection((host, int(port)), timeout=5)
        self._reader = self._socket.makefile("rb")

    def send(self, message: JsonObject) -> None:
        self._socket.sendall((json.dumps(message) + "\n").encode())

    def hello(self, token: str | None = None) -> None:
        self.send({"type": "hello", "token": token or self.token, "pid": 4242, "argv": ["app.py"], "cwd": "/work"})

    def read(self) -> WireReader:
        return WireReader.of(json.loads(self._reader.readline()))

    def read_is_end_of_stream(self) -> bool:
        return self._reader.readline() == b""

    def close(self) -> None:
        self._reader.close()
        self._socket.close()


class TestAgentHello(unittest.TestCase):
    def test_from_wire_reads_process_details(self) -> None:
        message = WireReader({"pid": 12, "executable": "/usr/bin/python3.15", "argv": ["app.py", "1"], "cwd": "/work"})

        hello = AgentHello.from_wire(message)

        self.assertEqual(hello, AgentHello(12, "/usr/bin/python3.15", ["app.py", "1"], "/work", []))


class TestAgentServer(unittest.TestCase):
    def setUp(self) -> None:
        self.listener = _RecordingListener()
        self.server = AgentServer()
        self.addCleanup(self.server.close)
        self.server.start(self.listener)
        self.addCleanup(self.close_accepted_connection)
        self.agent = _FakeAgent(self.server.address)
        self.addCleanup(self.agent.close)

    def close_accepted_connection(self) -> None:
        """Runs after the fake agent hung up: release the server-side socket."""
        connection = self.listener.connection
        if connection is not None:
            self.listener.closed.wait(5)
            connection.close()

    def connect(self) -> AgentConnection:
        self.agent.hello()
        self.assertTrue(self.listener.connected.wait(5), msg="agent hello was not accepted")
        connection = self.listener.connection
        assert connection is not None
        return connection

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

        self.agent.send({"type": "metrics", "traced": 100})

        self.assertTrue(self.listener.message_received.wait(5))
        self.assertEqual(self.listener.messages[0].get_int("traced"), 100)

    def test_request_returns_result_sent_by_agent(self) -> None:
        connection = self.connect()
        replies: list[WireReader] = []
        caller = threading.Thread(target=lambda: replies.append(connection.request("ping", {"n": 1})))
        caller.start()

        request = self.agent.read()
        self.agent.send({"type": "result", "id": request.get_int("id"), "result": {"pong": True}})
        caller.join(5)

        self.assertEqual((request.get_str("method"), request.get_object("params").get_int("n")), ("ping", 1))
        self.assertTrue(replies[0].get_bool("pong", False))

    def test_request_with_error_reply_raises_agent_error(self) -> None:
        connection = self.connect()
        errors: list[AgentError] = []

        def call() -> None:
            try:
                connection.request("snapshot")
            except AgentError as error:
                errors.append(error)

        caller = threading.Thread(target=call)
        caller.start()

        request = self.agent.read()
        self.agent.send({"type": "result", "id": request.get_int("id"), "error": "RuntimeError: not tracing"})
        caller.join(5)

        self.assertEqual(str(errors[0]), "RuntimeError: not tracing")

    def test_request_without_answer_raises_agent_error_after_timeout(self) -> None:
        connection = self.connect()

        with self.assertRaises(AgentError) as ctx:
            connection.request("ping", timeout=0.05)

        self.assertIn("did not answer 'ping'", str(ctx.exception))

    def test_disconnect_notifies_listener_and_marks_connection_dead(self) -> None:
        connection = self.connect()

        self.agent.close()

        self.assertTrue(self.listener.closed.wait(5))
        self.assertFalse(connection.alive)

    def test_request_after_disconnect_raises_agent_error(self) -> None:
        connection = self.connect()
        self.agent.close()
        self.assertTrue(self.listener.closed.wait(5))

        with self.assertRaises(AgentError):
            connection.request("ping")


if __name__ == "__main__":
    unittest.main()
