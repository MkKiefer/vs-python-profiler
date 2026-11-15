import unittest

from _vscode_pyprof.agent_protocol.messages import FROM_AGENT
from _vscode_pyprof.agent_protocol.replies import (
    Allocation,
    AsyncioDebugStatus,
    HeapSnapshot,
    ObjectCounts,
    Pong,
    SourceLine,
    TracingStatus,
    TypeCount,
)
from _vscode_pyprof.wire import Response, WireDecoder, WireEncoder


class TestReplies(unittest.TestCase):
    def test_every_reply_round_trips_as_the_result_of_a_response(self) -> None:
        encoder, decoder = WireEncoder(), WireDecoder(FROM_AGENT)
        replies = [
            TracingStatus(True, 16),
            TracingStatus(False),
            AsyncioDebugStatus(enabled=True, loops=2),
            HeapSnapshot(
                perf_counter=5.0,
                total_size=300,
                total_count=3,
                other_size=20,
                other_count=1,
                traced=400,
                peak=500,
                take_ms=None,
                top=[Allocation([SourceLine("app.py", 3)], 280, 2)],
            ),
            ObjectCounts(3.0, [TypeCount("dict", 10)]),
            Pong(2.5, 4242),
        ]
        for reply in replies:
            with self.subTest(reply=type(reply).__name__):
                response = Response(7, result=reply)

                self.assertEqual(decoder.decode(encoder.encode(response)), response)


if __name__ == "__main__":
    unittest.main()
