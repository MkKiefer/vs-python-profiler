import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr
from unittest import mock

from _vscode_pyprof.target.launcher import Launcher, LauncherError, Target, TargetKind


class TestTargetParse(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.script = os.path.join(directory.name, "app.py")
        with open(self.script, "w", encoding="utf-8") as f:
            f.write("print('hi')\n")

    def test_parse_with_module_flag_returns_module_target(self) -> None:
        target = Target.parse(["-m", "mypkg.cli", "--verbose"])

        self.assertEqual(target, Target(TargetKind.MODULE, "mypkg.cli", ["--verbose"]))

    def test_parse_with_script_path_returns_path_target(self) -> None:
        target = Target.parse([self.script, "--port", "8000"])

        self.assertEqual(target, Target(TargetKind.PATH, self.script, ["--port", "8000"]))

    def test_parse_with_nothing_to_run_raises_launcher_error(self) -> None:
        with self.assertRaises(LauncherError) as ctx:
            Target.parse([])

        self.assertIn("nothing to run", str(ctx.exception))

    def test_parse_with_module_flag_but_no_name_raises_launcher_error(self) -> None:
        with self.assertRaises(LauncherError):
            Target.parse(["-m"])

    def test_parse_with_missing_script_raises_launcher_error(self) -> None:
        with self.assertRaises(LauncherError) as ctx:
            Target.parse([self.script + ".missing"])

        self.assertIn("cannot find", str(ctx.exception))


class TestLauncher(unittest.TestCase):
    def test_main_with_missing_script_exits_with_error_code(self) -> None:
        errors = io.StringIO()

        with redirect_stderr(errors), self.assertRaises(SystemExit) as ctx:
            Launcher().main(["definitely-not-a-file-xyz.py"])

        self.assertEqual(ctx.exception.code, Launcher.EXIT_ERROR)
        self.assertIn("pyprof: cannot find", errors.getvalue())

    def test_main_without_agent_address_exits_with_error_code(self) -> None:
        errors = io.StringIO()

        with (
            mock.patch.dict(os.environ, {}, clear=False),
            redirect_stderr(errors),
            self.assertRaises(SystemExit) as ctx,
        ):
            os.environ.pop("PYPROF_AGENT", None)
            Launcher().main(["-m", "json.tool"])

        self.assertEqual(ctx.exception.code, Launcher.EXIT_ERROR)
        self.assertIn("PYPROF_AGENT is not set", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
