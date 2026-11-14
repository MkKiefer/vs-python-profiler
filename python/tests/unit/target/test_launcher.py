import io
import json
import os
import socket
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout

from _vscode_pyprof.target.launcher import HubClient, Launcher, LauncherError, Target, TargetParser
from _vscode_pyprof.wire import WireReader


class TestTargetParser(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = TargetParser()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.script = os.path.join(directory.name, "app.py")
        with open(self.script, "w", encoding="utf-8") as f:
            f.write("print('hi')\n")

    def test_parse_with_module_flag_returns_module_target(self) -> None:
        target = self.parser.parse(["-m", "mypkg.cli", "--verbose"])

        self.assertEqual(target, Target(Target.MODULE, "mypkg.cli", ["--verbose"]))

    def test_parse_with_script_path_returns_path_target(self) -> None:
        target = self.parser.parse([self.script, "--port", "8000"])

        self.assertEqual(target, Target(Target.PATH, self.script, ["--port", "8000"]))

    def test_parse_with_leading_double_dash_ignores_it(self) -> None:
        target = self.parser.parse(["--", self.script])

        self.assertEqual(target.name, self.script)

    def test_parse_with_python_command_unwraps_interpreter(self) -> None:
        target = self.parser.parse(["python", self.script, "1"])

        self.assertEqual(target, Target(Target.PATH, self.script, ["1"]))

    def test_parse_with_python_flags_skips_flags_and_their_arguments(self) -> None:
        target = self.parser.parse(["python3.15", "-X", "dev", "-u", "-m", "pytest", "-k", "slow"])

        self.assertEqual(target, Target(Target.MODULE, "pytest", ["-k", "slow"]))

    def test_parse_with_python_dash_c_raises_launcher_error(self) -> None:
        with self.assertRaises(LauncherError) as ctx:
            self.parser.parse(["python", "-c", "print(1)"])

        self.assertIn("-c", str(ctx.exception))

    def test_parse_with_nothing_to_run_raises_launcher_error(self) -> None:
        with self.assertRaises(LauncherError) as ctx:
            self.parser.parse(["--"])

        self.assertIn("nothing to run", str(ctx.exception))

    def test_parse_with_module_flag_but_no_name_raises_launcher_error(self) -> None:
        with self.assertRaises(LauncherError):
            self.parser.parse(["-m"])

    def test_parse_with_unknown_command_raises_launcher_error(self) -> None:
        with self.assertRaises(LauncherError) as ctx:
            self.parser.parse(["definitely-not-a-command-xyz"])

        self.assertIn("cannot find", str(ctx.exception))

    def test_looks_like_python_executable_with_interpreter_names_returns_true(self) -> None:
        for name in (
            "python",
            "pythonw",
            "python3",
            "python3.15",
            "python3.15t",
            "C:\\Py\\Python.EXE".replace("\\", os.sep),
        ):
            with self.subTest(name=name):
                self.assertTrue(TargetParser.looks_like_python_executable(name))

    def test_looks_like_python_executable_with_other_names_returns_false(self) -> None:
        for name in ("pythonic", "uvicorn", "python-config"):
            with self.subTest(name=name):
                self.assertFalse(TargetParser.looks_like_python_executable(name))

    def test_is_python_script_with_python_shebang_returns_true(self) -> None:
        tool = self.script.replace("app.py", "tool")
        with open(tool, "w", encoding="utf-8") as f:
            f.write("#!/usr/bin/env python3\nprint('x')\n")

        self.assertTrue(TargetParser.is_python_script(tool))

    def test_is_python_script_with_shell_script_returns_false(self) -> None:
        tool = self.script.replace("app.py", "tool")
        with open(tool, "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\necho x\n")

        self.assertFalse(TargetParser.is_python_script(tool))

    def test_is_python_script_with_py_extension_returns_true(self) -> None:
        self.assertTrue(TargetParser.is_python_script(self.script))

    def test_is_python_script_with_missing_file_returns_false(self) -> None:
        self.assertFalse(TargetParser.is_python_script(self.script + ".missing"))


class _FakeHub:
    """A one-shot terminal hub: records the hello line and answers with a fixed reply."""

    def __init__(self, reply: bytes) -> None:
        self._reply = reply
        self._server = socket.socket()
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(1)
        self.hello = WireReader({})
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    @property
    def address(self) -> str:
        return f"127.0.0.1:{self._server.getsockname()[1]}:secret"

    def _serve(self) -> None:
        connection, _ = self._server.accept()
        with connection:
            self.hello = WireReader.of(json.loads(connection.makefile().readline()))
            connection.sendall(self._reply)

    def close(self) -> None:
        self._thread.join(5)
        self._server.close()


class TestHubClient(unittest.TestCase):
    def start_hub(self, reply: bytes) -> _FakeHub:
        hub = _FakeHub(reply)
        self.addCleanup(hub.close)
        return hub

    def test_announce_sends_token_and_target(self) -> None:
        hub = self.start_hub(b'{"agent": "127.0.0.1:1:t"}\n')

        HubClient(hub.address).announce("path", "app.py", ["1"])

        hub.close()
        self.assertEqual(
            (
                hub.hello.get_str("token"),
                hub.hello.get_str("kind"),
                hub.hello.get_str("target"),
                hub.hello.get_int("pid"),
            ),
            ("secret", "path", "app.py", os.getpid()),
        )

    def test_announce_returns_reply_object(self) -> None:
        hub = self.start_hub(b'{"agent": "127.0.0.1:1:t", "options": {"rateHz": 5}}\n')

        reply = HubClient(hub.address).announce("path", "app.py", [])

        self.assertEqual(reply, {"agent": "127.0.0.1:1:t", "options": {"rateHz": 5}})

    def test_announce_with_error_reply_raises_launcher_error(self) -> None:
        hub = self.start_hub(b'{"error": "bad token"}\n')

        with self.assertRaises(LauncherError) as ctx:
            HubClient(hub.address).announce("path", "app.py", [])

        self.assertEqual(str(ctx.exception), "bad token")

    def test_announce_when_hub_closes_without_reply_raises_launcher_error(self) -> None:
        hub = self.start_hub(b"")

        with self.assertRaises(LauncherError):
            HubClient(hub.address).announce("path", "app.py", [])

    def test_announce_with_unreachable_hub_raises_launcher_error(self) -> None:
        unused = socket.socket()
        unused.bind(("127.0.0.1", 0))
        port = unused.getsockname()[1]
        unused.close()

        with self.assertRaises(LauncherError) as ctx:
            HubClient(f"127.0.0.1:{port}:secret").announce("path", "app.py", [])

        self.assertIn("cannot reach", str(ctx.exception))


class TestLauncher(unittest.TestCase):
    def setUp(self) -> None:
        self.launcher = Launcher(TargetParser())

    def test_main_with_help_prints_usage(self) -> None:
        output = io.StringIO()

        with redirect_stdout(output):
            self.launcher.main(["--help"])

        self.assertIn("usage: pyprof run", output.getvalue())

    def test_main_with_invalid_target_exits_with_error_code(self) -> None:
        errors = io.StringIO()

        with redirect_stderr(errors), self.assertRaises(SystemExit) as ctx:
            self.launcher.main(["run", "definitely-not-a-command-xyz"])

        self.assertEqual(ctx.exception.code, Launcher.EXIT_ERROR)
        self.assertIn("pyprof: cannot find", errors.getvalue())

    def test_attach_with_non_numeric_pid_raises_launcher_error(self) -> None:
        with self.assertRaises(LauncherError) as ctx:
            self.launcher.attach(["abc"])

        self.assertIn("usage: pyprof attach", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
