import os
import subprocess
import sys
import tempfile
import unittest

from _vspyprof.processes import ProcessLister, PythonProcess


class TestProcessLister(unittest.TestCase):
    def setUp(self) -> None:
        self.lister = ProcessLister()

    def test_is_python_name_with_interpreter_names_returns_true(self) -> None:
        for name in ("python", "python3", "python3.15", "python3.15t", "Python.exe", "pythonw.exe", "/usr/bin/python3"):
            with self.subTest(name=name):
                self.assertTrue(ProcessLister.is_python_name(name))

    def test_is_python_name_with_other_programs_returns_false(self) -> None:
        for name in ("pythonista", "ipython", "node", "", None):
            with self.subTest(name=name):
                self.assertFalse(ProcessLister.is_python_name(name))

    def test_guess_version_with_versioned_executable_returns_major_minor(self) -> None:
        self.assertEqual(ProcessLister.guess_version("/venv/bin/python", "/usr/bin/python3.15"), "3.15")

    def test_guess_version_with_unversioned_executable_outside_venv_returns_none(self) -> None:
        self.assertIsNone(ProcessLister.guess_version("/usr/bin/python", "/usr/bin/python"))

    def test_guess_version_with_venv_reads_pyvenv_cfg(self) -> None:
        with tempfile.TemporaryDirectory() as venv:
            os.mkdir(os.path.join(venv, "bin"))
            with open(os.path.join(venv, "pyvenv.cfg"), "w", encoding="utf-8") as f:
                f.write("home = /usr/bin\nversion = 3.15.2\n")
            executable = os.path.join(venv, "bin", "python")

            version = ProcessLister.guess_version(executable, executable)

        self.assertEqual(version, "3.15")

    def test_venv_of_with_executable_in_venv_returns_venv_root(self) -> None:
        with tempfile.TemporaryDirectory() as venv:
            with open(os.path.join(venv, "pyvenv.cfg"), "w", encoding="utf-8") as f:
                f.write("version = 3.15.2\n")

            root = ProcessLister.venv_of(os.path.join(venv, "bin", "python"))

            self.assertEqual(root, venv)

    def test_venv_of_with_system_executable_returns_none(self) -> None:
        self.assertIsNone(ProcessLister.venv_of(os.path.join(tempfile.gettempdir(), "nowhere", "bin", "python")))

    @unittest.skipUnless(sys.platform.startswith("linux") or sys.platform == "darwin", "needs /proc or ps")
    def test_list_processes_finds_running_python_child(self) -> None:
        child = subprocess.Popen(
            [sys.executable, "-c", "import sys; sys.stdin.read()", "marker-arg"], stdin=subprocess.PIPE
        )
        self.addCleanup(child.communicate)
        self.addCleanup(child.kill)

        found = [process for process in self.lister.list_processes() if process.pid == child.pid]

        self.assertEqual(len(found), 1, msg=f"child {child.pid} not listed")
        self.assertIn("marker-arg", found[0].argv)

    def test_list_processes_excludes_own_process(self) -> None:
        pids = [process.pid for process in self.lister.list_processes()]

        self.assertNotIn(os.getpid(), pids)


class TestPythonProcess(unittest.TestCase):
    def test_to_wire_uses_extension_field_names(self) -> None:
        process = PythonProcess(
            pid=10,
            parent_pid=1,
            executable="/venv/bin/python",
            real_executable="/usr/bin/python3.15",
            version="3.15",
            venv="/venv",
            argv=["python", "app.py"],
            title="python app.py",
            cwd="/work",
        )

        self.assertDictEqual(
            process.to_wire(),
            {
                "pid": 10,
                "ppid": 1,
                "executable": "/venv/bin/python",
                "realExecutable": "/usr/bin/python3.15",
                "version": "3.15",
                "venv": "/venv",
                "argv": ["python", "app.py"],
                "title": "python app.py",
                "cwd": "/work",
                "isLauncher": False,
            },
        )


if __name__ == "__main__":
    unittest.main()
