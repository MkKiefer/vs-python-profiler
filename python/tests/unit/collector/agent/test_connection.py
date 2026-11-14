import threading
import unittest

from _vscode_pyprof.collector.agent.connection import AgentError
from _vscode_pyprof.wire import WireReader
from tests.unit.collector.agent.agent_link_harness import AgentLinkTestCase


class TestAgentConnection(AgentLinkTestCase):
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
