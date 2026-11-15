import io
import json
import threading
import unittest
from dataclasses import dataclass

from _vscode_pyprof.collector.notifications import StateChanged
from _vscode_pyprof.collector.protocol import SessionState
from _vscode_pyprof.collector.rpc import RpcError, RpcServer
from _vscode_pyprof.wire import JsonObject, Request, WireDecoder, WireEncoder


@dataclass(frozen=True)
class _Echo:
    """The request and the result of the test's handler."""

    name: str


@dataclass(frozen=True)
class _Fail:
    pass


class _RecordingOutput(io.BytesIO):
    """An output stream tests can wait on (handlers answer from worker threads)."""

    def __init__(self) -> None:
        super().__init__()
        self._written = threading.Semaphore(0)

    def flush(self) -> None:
        super().flush()
        self._written.release()

    def wait_for_messages(self, count: int) -> list[JsonObject]:
        for _ in range(count):
            if not self._written.acquire(timeout=5):
                raise AssertionError("the server did not write the expected message")
        return [json.loads(line) for line in self.getvalue().splitlines()]


class TestRpcServer(unittest.TestCase):
    def setUp(self) -> None:
        self.output = _RecordingOutput()

    def server(self, payload: bytes = b"") -> RpcServer:
        return RpcServer(io.BytesIO(payload), self.output, WireEncoder(), WireDecoder([Request, _Echo, _Fail]))

    def serve(self, *lines: str) -> RpcServer:
        server = self.server("".join(line + "\n" for line in lines).encode())
        server.serve(self.handle)
        return server

    @staticmethod
    def handle(request: object) -> object:
        match request:
            case _Echo(name=name):
                return _Echo(name.upper())
            case _Fail():
                raise RpcError("not now")
        raise RpcError(f"unknown request {type(request).__name__}")

    def test_serve_answers_a_request_with_the_handler_result(self) -> None:
        self.serve('{"type": "Request", "id": 1, "body": {"type": "_Echo", "name": "x"}}')

        messages = self.output.wait_for_messages(1)

        self.assertListEqual(
            messages, [{"type": "Response", "id": 1, "result": {"type": "_Echo", "name": "X"}, "error": None}]
        )

    def test_serve_with_failing_handler_answers_its_error(self) -> None:
        self.serve('{"type": "Request", "id": 3, "body": {"type": "_Fail"}}')

        messages = self.output.wait_for_messages(1)

        self.assertEqual((messages[0]["result"], messages[0]["error"]), (None, "not now"))

    def test_serve_with_malformed_body_answers_the_wire_error(self) -> None:
        self.serve('{"type": "Request", "id": 4, "body": {"type": "_Echo", "nom": "x"}}')

        messages = self.output.wait_for_messages(1)

        self.assertRegex(str(messages[0]["error"]), r"\$\.body is not a _Echo")

    def test_serve_with_line_that_is_not_a_request_skips_it(self) -> None:
        self.serve(
            "not json", '{"type": "_Echo", "name": "x"}', '{"type": "Request", "id": 5, "body": {"type": "_Fail"}}'
        )

        messages = self.output.wait_for_messages(1)

        self.assertEqual([message["id"] for message in messages], [5])

    def test_serve_when_input_ends_marks_server_closed(self) -> None:
        server = self.serve()

        self.assertTrue(server.closed)

    def test_notify_writes_the_message(self) -> None:
        self.server().notify(StateChanged(SessionState.RUNNING, pid=12))

        self.assertListEqual(
            self.output.wait_for_messages(1), [{"type": "StateChanged", "state": "running", "pid": 12, "reason": None}]
        )

    def test_notify_on_closed_output_marks_server_closed(self) -> None:
        self.output.close()
        server = self.server()

        server.notify(StateChanged(SessionState.RUNNING))

        self.assertTrue(server.closed)


if __name__ == "__main__":
    unittest.main()
