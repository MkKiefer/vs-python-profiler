import unittest

from _vscode_pyprof.collector import requests
from _vscode_pyprof.collector.messages import FROM_EXTENSION
from _vscode_pyprof.collector.options import CollectorOptions
from _vscode_pyprof.wire import Request, WireDecoder, WireError


class TestFromExtension(unittest.TestCase):
    """The request lines ``CollectorClient`` writes (``src/extension/collectorClient.ts``) decode as expected."""

    def setUp(self) -> None:
        self.decoder = WireDecoder(FROM_EXTENSION)

    def decode_body(self, body: str) -> object:
        request = self.decoder.decode(f'{{"type": "Request", "id": 1, "body": {body}}}')
        assert isinstance(request, Request)
        return request.body

    def test_every_request_the_extension_sends_decodes(self) -> None:
        cases: list[tuple[str, object]] = [
            (
                '{"type": "Initialize", "options": {"type": "CollectorOptions", "rateHz": 200}, "label": "app.py"}',
                requests.Initialize(CollectorOptions(rate_hz=200), "app.py"),
            ),
            ('{"type": "Attach", "pid": 42, "inject": false}', requests.Attach(42, inject=False)),
            ('{"type": "Stop", "reason": "user"}', requests.Stop("user")),
            ('{"type": "GetStatus"}', requests.GetStatus()),
            ('{"type": "SetTracemalloc", "enabled": true}', requests.SetTracemalloc(enabled=True)),
            ('{"type": "TakeSnapshot", "label": "A"}', requests.TakeSnapshot(label="A")),
            ('{"type": "CountObjects"}', requests.CountObjects()),
            ('{"type": "SetAsyncioDebug", "enabled": true, "slowMs": 50}', requests.SetAsyncioDebug(True, 50)),
            ('{"type": "Mark", "name": "deploy"}', requests.Mark("deploy")),
            ('{"type": "Save", "path": "/tmp/a.pyprof"}', requests.Save("/tmp/a.pyprof")),
            ('{"type": "Shutdown"}', requests.Shutdown()),
        ]
        for body, expected in cases:
            with self.subTest(body=body):
                self.assertEqual(self.decode_body(body), expected)

    def test_attach_without_pid_raises_wire_error(self) -> None:
        with self.assertRaisesRegex(WireError, r"\$\.body is not a Attach"):
            self.decode_body('{"type": "Attach"}')


if __name__ == "__main__":
    unittest.main()
