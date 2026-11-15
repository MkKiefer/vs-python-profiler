import threading
import unittest

from _vspyprof.agent_protocol.commands import CountObjects, Ping, TakeSnapshot
from _vspyprof.agent_protocol.replies import ObjectCounts, Pong, TypeCount
from _vspyprof.collector.agent.connection import AgentError
from tests.unit.collector.agent.agent_link_harness import AgentLinkTestCase


class TestAgentConnection(AgentLinkTestCase):
    def test_request_returns_result_sent_by_agent(self) -> None:
        connection = self.connect()
        replies: list[ObjectCounts] = []
        caller = threading.Thread(target=lambda: replies.append(connection.request(CountObjects(5), ObjectCounts)))
        caller.start()

        request = self.agent.read()
        counts = {"type": "ObjectCounts", "t": 1.5, "counts": [{"type": "TypeCount", "typeName": "dict", "count": 3}]}
        self.agent.send({"type": "Response", "id": request.id, "result": counts, "error": None})
        caller.join(5)

        self.assertEqual(request.body, CountObjects(5))
        self.assertEqual(replies, [ObjectCounts(1.5, [TypeCount("dict", 3)])])

    def test_request_with_reply_of_another_shape_raises_agent_error(self) -> None:
        connection = self.connect()
        errors: list[AgentError] = []

        def call() -> None:
            try:
                connection.request(Ping(), Pong)
            except AgentError as error:
                errors.append(error)

        caller = threading.Thread(target=call)
        caller.start()

        request = self.agent.read()
        self.agent.send({"type": "Response", "id": request.id, "result": {"type": "TracingStatus", "tracing": True}})
        caller.join(5)

        self.assertEqual(str(errors[0]), "agent answered Ping with TracingStatus")

    def test_request_with_error_reply_raises_agent_error(self) -> None:
        connection = self.connect()
        errors: list[AgentError] = []

        def call() -> None:
            try:
                connection.request(TakeSnapshot(10), ObjectCounts)
            except AgentError as error:
                errors.append(error)

        caller = threading.Thread(target=call)
        caller.start()

        request = self.agent.read()
        self.agent.send({"type": "Response", "id": request.id, "error": "RuntimeError: not tracing"})
        caller.join(5)

        self.assertEqual(str(errors[0]), "RuntimeError: not tracing")

    def test_request_without_answer_raises_agent_error_after_timeout(self) -> None:
        connection = self.connect()

        with self.assertRaises(AgentError) as ctx:
            connection.request(Ping(), Pong, timeout=0.05)

        self.assertIn("did not answer Ping", str(ctx.exception))

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
            connection.request(Ping(), Pong)


if __name__ == "__main__":
    unittest.main()
