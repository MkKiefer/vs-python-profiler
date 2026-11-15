"""Accepts the connections of in-process agents."""

import secrets
import socket
import threading

from _vspyprof.agent_protocol.address import AgentAddress
from _vspyprof.agent_protocol.hello import AgentHello
from _vspyprof.collector.agent.connection import AgentConnection
from _vspyprof.collector.agent.listener import AgentListener
from _vspyprof.wire import LineBuffer, WireDecoder, WireEncoder


class AgentServer:
    """Listens on localhost for agents that present our one-time token.

    The token keeps other local processes from posing as the agent: only a
    process the extension started or injected knows it.
    """

    _HANDSHAKE_TIMEOUT = 10.0
    _RECEIVE_SIZE = 65536
    _BACKLOG = 8

    def __init__(self, encoder: WireEncoder, decoder: WireDecoder) -> None:
        """``decoder`` reads what agents send (``agent_protocol.messages.FROM_AGENT``)."""
        self._encoder = encoder
        self._decoder = decoder
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.bind(("127.0.0.1", 0))
        self._socket.listen(self._BACKLOG)
        host, port = self._socket.getsockname()
        self._address = AgentAddress(host, port, secrets.token_hex(16))
        self._listener: AgentListener | None = None

    @property
    def address(self) -> str:
        """``host:port:token`` - what the agent needs to connect back."""
        return str(self._address)

    def start(self, listener: AgentListener) -> None:
        self._listener = listener
        threading.Thread(target=self._accept_loop, name="vspyprof-agent-server", daemon=True).start()

    def close(self) -> None:
        try:
            self._socket.close()
        except OSError:
            pass

    def _accept_loop(self) -> None:
        while True:
            try:
                sock, _ = self._socket.accept()
            except OSError:
                return  # closed
            threading.Thread(target=self._handshake, args=(sock,), daemon=True).start()

    def _handshake(self, sock: socket.socket) -> None:
        """Hand the connection to the listener if its first message is a hello with our token."""
        listener = self._listener
        if listener is None:
            sock.close()
            return
        sock.settimeout(self._HANDSHAKE_TIMEOUT)
        lines = LineBuffer()
        try:
            while (line := lines.next_line()) is None:
                chunk = sock.recv(self._RECEIVE_SIZE)
                if not chunk:
                    raise OSError("closed during handshake")
                lines.feed(chunk)
            hello = self._decoder.decode(line)  # ValueError unless it is a known message
            if not isinstance(hello, AgentHello) or not self._is_authentic(hello):
                raise OSError("bad agent token")
        except OSError, ValueError:
            sock.close()
            return
        sock.settimeout(None)
        connection = AgentConnection(sock, hello, listener, lines, self._encoder, self._decoder)
        listener.on_agent_hello(connection)
        connection.start()

    def _is_authentic(self, hello: AgentHello) -> bool:
        return secrets.compare_digest(hello.token.encode(), self._address.token.encode())
