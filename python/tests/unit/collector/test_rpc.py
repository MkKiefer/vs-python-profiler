import io
import json
import threading
import unittest
from dataclasses import dataclass

from _vscode_pyprof.collector.rpc import RpcError, RpcServer
from _vscode_pyprof.collector.rpc_params import NoParams
from _vscode_pyprof.wire import JsonObject, WireMessage
from tests.unit.json_view import JsonView


@dataclass(frozen=True, slots=True)
class _Echo(WireMessage):
    """The params and the result of the test's ``echo`` method."""

    name: str


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

    def _serve(self, *requests: JsonObject) -> RpcServer:
        payload = "".join(json.dumps(request) + "\n" for request in requests).encode()
        server = RpcServer(io.BytesIO(payload), self.output)
        server.register("echo", _Echo, lambda params: _Echo(params.name))
        server.register("fail", NoParams, self._raise_rpc_error)
        server.serve()
        return server

    @staticmethod
    def _raise_rpc_error(_params: NoParams) -> WireMessage:
        raise RpcError("not now")

    def test_serve_with_known_method_writes_result(self) -> None:
        self._serve({"id": 1, "method": "echo", "params": {"name": "x"}})

        messages = self.output.wait_for_messages(1)

        self.assertListEqual(messages, [{"id": 1, "result": {"name": "x"}}])

    def test_serve_with_unknown_method_writes_error(self) -> None:
        self._serve({"id": 2, "method": "nope"})

        messages = self.output.wait_for_messages(1)

        self.assertEqual(messages[0]["error"], {"message": "unknown method 'nope'", "type": "RpcError"})

    def test_serve_with_failing_handler_writes_error_message(self) -> None:
        self._serve({"id": 3, "method": "fail"})

        messages = self.output.wait_for_messages(1)

        self.assertEqual(messages[0]["error"], {"message": "not now", "type": "RpcError"})

    def test_serve_with_malformed_params_writes_wire_error(self) -> None:
        self._serve({"id": 4, "method": "echo", "params": {"name": 5}})

        messages = self.output.wait_for_messages(1)

        self.assertEqual(JsonView.of(messages[0]["error"]).get_str("type"), "WireError")

    def test_serve_with_invalid_json_line_skips_it(self) -> None:
        server = RpcServer(
            io.BytesIO(b'not json\n{"id": 5, "method": "echo", "params": {"name": "ok"}}\n'), self.output
        )
        server.register("echo", _Echo, lambda params: _Echo(params.name))

        server.serve()

        self.assertListEqual(self.output.wait_for_messages(1), [{"id": 5, "result": {"name": "ok"}}])

    def test_serve_when_input_ends_marks_server_closed(self) -> None:
        server = self._serve()

        self.assertTrue(server.closed)

    def test_notify_writes_message_without_id(self) -> None:
        server = RpcServer(io.BytesIO(), self.output)

        server.notify("state", {"state": "running"})

        self.assertListEqual(self.output.wait_for_messages(1), [{"method": "state", "params": {"state": "running"}}])

    def test_notify_on_closed_output_marks_server_closed(self) -> None:
        self.output.close()
        server = RpcServer(io.BytesIO(), self.output)

        server.notify("state", {"state": "running"})

        self.assertTrue(server.closed)


if __name__ == "__main__":
    unittest.main()
