"""Shared harness for the agent link tests: a real ``AgentServer`` and a scripted agent on a real socket."""

import json
import socket
import threading
import unittest

from _vspyprof.agent_protocol.messages import FROM_AGENT, TO_AGENT
from _vspyprof.agent_protocol.metrics import AgentMetrics
from _vspyprof.collector.agent.connection import AgentConnection
from _vspyprof.collector.agent.listener import AgentListener
from _vspyprof.collector.agent.server import AgentServer
from _vspyprof.wire import JsonObject, Request, WireDecoder, WireEncoder


class RecordingListener(AgentListener):
    def __init__(self) -> None:
        self.connected = threading.Event()
        self.closed = threading.Event()
        self.message_received = threading.Event()
        self.connection: AgentConnection | None = None
        self.metrics: list[AgentMetrics] = []

    def on_agent_hello(self, connection: AgentConnection) -> None:
        self.connection = connection
        self.connected.set()

    def on_agent_metrics(self, connection: AgentConnection, metrics: AgentMetrics) -> None:
        self.metrics.append(metrics)
        self.message_received.set()

    def on_agent_close(self, connection: AgentConnection) -> None:
        self.closed.set()


class FakeAgent:
    """The target-process end of the connection, driven by the test."""

    def __init__(self, address: str) -> None:
        host, port, self.token = address.rsplit(":", 2)
        self._socket = socket.create_connection((host, int(port)), timeout=5)
        self._reader = self._socket.makefile("rb")
        self._decoder = WireDecoder(TO_AGENT)

    def send(self, message: JsonObject) -> None:
        self._socket.sendall((json.dumps(message) + "\n").encode())

    def hello(self, token: str | None = None) -> None:
        self.send(
            {
                "type": "AgentHello",
                "token": token or self.token,
                "pid": 4242,
                "executable": "/usr/bin/python3.15",
                "argv": ["app.py"],
                "cwd": "/work",
                "version": "3.15.2",
                "threads": [],
            }
        )

    def read(self) -> Request:
        request = self._decoder.decode(self._reader.readline())
        assert isinstance(request, Request)
        return request

    def read_is_end_of_stream(self) -> bool:
        return self._reader.readline() == b""

    def close(self) -> None:
        self._reader.close()
        self._socket.close()


class AgentLinkTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.listener = RecordingListener()
        self.server = AgentServer(WireEncoder(), WireDecoder(FROM_AGENT))
        self.addCleanup(self.server.close)
        self.server.start(self.listener)
        self.addCleanup(self.close_accepted_connection)
        self.agent = FakeAgent(self.server.address)
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
