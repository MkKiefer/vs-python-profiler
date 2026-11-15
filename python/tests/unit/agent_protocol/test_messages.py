import unittest

from _vspyprof.agent_protocol.commands import (
    CountObjects,
    Ping,
    SetAsyncioDebug,
    Shutdown,
    StartTracing,
    StopTracing,
    TakeSnapshot,
)
from _vspyprof.agent_protocol.messages import TO_AGENT
from _vspyprof.wire import Request, WireDecoder, WireEncoder


class TestToAgent(unittest.TestCase):
    def test_every_command_round_trips_as_the_body_of_a_request(self) -> None:
        encoder, decoder = WireEncoder(), WireDecoder(TO_AGENT)
        commands = [
            StartTracing(16),
            StopTracing(),
            TakeSnapshot(3000),
            CountObjects(60),
            SetAsyncioDebug(True, 50.0),
            Ping(),
            Shutdown(),
        ]
        for command in commands:
            with self.subTest(command=type(command).__name__):
                request = Request(3, command)

                self.assertEqual(decoder.decode(encoder.encode(request)), request)


if __name__ == "__main__":
    unittest.main()
