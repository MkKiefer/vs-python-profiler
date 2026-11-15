import logging
import unittest
import warnings
from typing import TextIO

from _vspyprof.agent_protocol.metrics import AgentEvent
from _vspyprof.agent_protocol.names import EventKind
from _vspyprof.target.asyncio_debug import AsyncioDebugCapture


class TestAsyncioDebugCapture(unittest.TestCase):
    def setUp(self) -> None:
        self.events: list[AgentEvent] = []
        self.shown: list[str] = []
        self.capture = AsyncioDebugCapture(self.events.append)
        self.logger = logging.getLogger("asyncio")
        self.logger.propagate = False  # keep the test records out of the test runner's output
        self.addCleanup(setattr, self.logger, "propagate", True)
        self.original_showwarning = warnings.showwarning
        self.addCleanup(setattr, warnings, "showwarning", self.original_showwarning)
        self.addCleanup(self.capture.remove)

    def last_event(self) -> AgentEvent:
        return self.events[-1]

    def show_warnings_in_test(self) -> None:
        """The program's own ``showwarning``: the capture must keep calling it."""

        def show(
            message: Warning | str,
            category: type[Warning],
            filename: str,
            lineno: int,
            file: TextIO | None = None,
            line: str | None = None,
        ) -> None:
            self.shown.append(str(message))

        warnings.showwarning = show

    def test_install_captures_slow_callback_with_duration(self) -> None:
        self.capture.install()

        self.logger.warning("Executing %s took %.3f seconds", "<Handle work()>", 0.25)

        event = self.last_event()
        self.assertEqual((event.kind, event.details.seconds), (EventKind.SLOW_CALLBACK, 0.25))
        self.assertEqual(event.details.handle, "<Handle work()>")
        self.assertIsNotNone(event.perf_counter)

    def test_install_captures_destroyed_pending_task(self) -> None:
        self.capture.install()

        self.logger.error("Task was destroyed but it is pending!")

        self.assertEqual(self.last_event().kind, EventKind.TASK_DESTROYED_PENDING)

    def test_install_captures_other_asyncio_warnings_as_plain_events(self) -> None:
        self.capture.install()

        self.logger.warning("socket.send() raised exception.")

        self.assertEqual(self.last_event().kind, EventKind.ASYNCIO)

    def test_install_ignores_records_below_warning_level(self) -> None:
        self.capture.install()

        self.logger.info("poll took 1.0 ms")

        self.assertEqual(self.events, [])

    def test_install_twice_adds_one_handler(self) -> None:
        handlers_before = len(self.logger.handlers)

        self.capture.install()
        self.capture.install()

        self.assertEqual(len(self.logger.handlers), handlers_before + 1)

    def test_install_captures_never_awaited_warning_and_still_shows_it(self) -> None:
        self.show_warnings_in_test()
        self.capture.install()

        warnings.showwarning("coroutine 'work' was never awaited", RuntimeWarning, "app.py", 12)

        event = self.last_event()
        self.assertEqual((event.kind, event.details.file, event.details.line), (EventKind.NEVER_AWAITED, "app.py", 12))
        self.assertEqual(self.shown, ["coroutine 'work' was never awaited"])

    def test_install_does_not_capture_unrelated_warnings(self) -> None:
        self.show_warnings_in_test()
        self.capture.install()

        warnings.showwarning("something is deprecated", DeprecationWarning, "app.py", 3)

        self.assertEqual(self.events, [])
        self.assertEqual(self.shown, ["something is deprecated"])

    def test_remove_restores_logger_and_showwarning(self) -> None:
        handlers_before = list(self.logger.handlers)
        self.capture.install()

        self.capture.remove()

        self.assertEqual(self.logger.handlers, handlers_before)
        self.assertIs(warnings.showwarning, self.original_showwarning)


if __name__ == "__main__":
    unittest.main()
