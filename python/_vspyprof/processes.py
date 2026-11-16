"""List running Python processes as JSON.

Runs as a standalone script with *any* Python 3.10+ (it is used before we know
which interpreter the target uses), so it must stay stdlib-only, must not import
the rest of the package and must avoid newer syntax::

    python -I processes.py            -> JSON list on stdout
"""

import json
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class PythonProcess:
    """One running Python interpreter. Mirror of ``ProcInfo`` in ``src/extension/processes.ts``."""

    pid: int
    parent_pid: int
    executable: str
    real_executable: str
    version: str | None
    """``major.minor`` if it can be told without running the interpreter."""
    venv: str | None
    argv: list[str]
    title: str
    cwd: str | None
    is_launcher: bool = False
    """A Windows venv launcher stub: the real interpreter is its child."""

    def to_wire(self) -> dict[str, object]:
        return {
            "pid": self.pid,
            "ppid": self.parent_pid,
            "executable": self.executable,
            "realExecutable": self.real_executable,
            "version": self.version,
            "venv": self.venv,
            "argv": self.argv,
            "title": self.title,
            "cwd": self.cwd,
            "isLauncher": self.is_launcher,
        }


class ProcessLister:
    """Finds Python interpreters among the running processes of this machine."""

    _PYTHON_NAME = re.compile(r"^python(\d(\.\d+)?t?)?(\.exe)?$|^pythonw(\.exe)?$", re.IGNORECASE)
    _VERSION_IN_NAME = re.compile(r"python(\d)\.(\d+)", re.IGNORECASE)
    _TITLE_LIMIT = 300

    def list_processes(self) -> list[PythonProcess]:
        """Every running Python process except this one; empty if the platform cannot be inspected."""
        try:
            if sys.platform.startswith("linux"):
                return self._list_linux()
            if sys.platform == "darwin":
                return self._list_macos()
            if sys.platform == "win32":
                return self._list_windows()
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            sys.stderr.write(f"process listing failed: {error!r}\n")
        return []

    @classmethod
    def is_python_name(cls, path: str | None) -> bool:
        return bool(cls._PYTHON_NAME.match(os.path.basename(path or "")))

    @staticmethod
    def venv_of(executable: str | None) -> str | None:
        """The venv root if ``executable`` lives in one (pyvenv.cfg next to bin/Scripts)."""
        if not executable:
            return None
        root = os.path.dirname(os.path.dirname(executable))
        return root if os.path.isfile(os.path.join(root, "pyvenv.cfg")) else None

    @classmethod
    def guess_version(cls, executable: str | None, real_executable: str | None) -> str | None:
        """``major.minor`` from the executable name or the venv's pyvenv.cfg, without running it."""
        for path in (real_executable, executable):
            match = cls._VERSION_IN_NAME.search(os.path.basename(path or ""))
            if match:
                return f"{match.group(1)}.{match.group(2)}"
        root = cls.venv_of(executable)
        if root is None:
            return None
        try:
            with open(os.path.join(root, "pyvenv.cfg"), encoding="utf-8") as f:
                for line in f:
                    key, _, value = line.partition("=")
                    if key.strip() in ("version", "version_info"):
                        return ".".join(value.strip().split(".")[:2])
        except OSError:
            pass
        return None

    def _list_linux(self) -> list[PythonProcess]:
        own_pid = os.getpid()
        records = []
        for name in os.listdir("/proc"):
            if not name.isdigit() or int(name) == own_pid:
                continue
            pid = int(name)
            try:
                with open(f"/proc/{pid}/cmdline", "rb") as f:
                    argv = [arg.decode("utf-8", "replace") for arg in f.read().split(b"\0") if arg]
            except OSError:
                continue
            executable = self._read_link(f"/proc/{pid}/exe") or ""
            if not argv or not (self.is_python_name(executable) or self.is_python_name(argv[0])):
                continue
            try:
                with open(f"/proc/{pid}/stat", "rb") as f:
                    stat = f.read()
                parent_pid = int(stat[stat.rindex(b")") + 2 :].split()[1])
            except (OSError, ValueError, IndexError):
                parent_pid = 0
            launched = argv[0] if os.path.isabs(argv[0]) else executable
            cwd = self._read_link(f"/proc/{pid}/cwd")
            records.append(self._process(pid, parent_pid, launched or executable, executable, argv, cwd))
        return records

    def _list_macos(self) -> list[PythonProcess]:
        # The executable path (comm) may contain spaces, so it gets a ps call of its own,
        # where it is the last column; args is the last column of the other one.
        executables = {int(row[0]): row[1] for row in self._ps("comm=") if len(row) == 2}
        own_pid = os.getpid()
        records = []
        for row in self._ps("ppid=,args="):
            if len(row) < 2:
                continue
            pid, parent_pid = int(row[0]), int(row[1])
            command = executables.get(pid, "")
            argv = row[2].split() if len(row) > 2 else [command]
            if pid == own_pid or not (self.is_python_name(command) or self.is_python_name(argv[0])):
                continue
            executable = command if os.path.isabs(command) else argv[0]
            real = os.path.realpath(executable) if os.path.isabs(executable) else executable
            records.append(self._process(pid, parent_pid, executable, real, argv, None))
        return records

    @staticmethod
    def _ps(columns: str) -> list[list[str]]:
        """``ps -ax`` rows: the pid, then ``columns``; the last column keeps its spaces."""
        result = subprocess.run(
            ["ps", "-axww", "-o", "pid=," + columns],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return [line.split(None, columns.count(",") + 1) for line in result.stdout.splitlines() if line.strip()]

    def _list_windows(self) -> list[PythonProcess]:
        query = (
            "Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" | "
            "Select-Object ProcessId,ParentProcessId,ExecutablePath,CommandLine | ConvertTo-Json -Compress"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", query],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        rows = json.loads(result.stdout or "[]")
        if isinstance(rows, dict):
            rows = [rows]
        own_pid = os.getpid()
        parent_pids = {row.get("ParentProcessId") for row in rows}
        records = []
        for row in rows:
            pid = row.get("ProcessId")
            parent_pid = row.get("ParentProcessId") or 0
            if pid == own_pid or parent_pid == own_pid:
                continue
            executable = row.get("ExecutablePath") or ""
            argv = self._split_windows_command_line(row.get("CommandLine") or executable)
            # venv launchers on Windows spawn the real interpreter as a child
            is_launcher = pid in parent_pids and self.venv_of(executable) is not None
            records.append(self._process(pid, parent_pid, executable, executable, argv, None, is_launcher))
        return records

    def _process(
        self,
        pid: int,
        parent_pid: int,
        executable: str,
        real_executable: str,
        argv: list[str],
        cwd: str | None,
        is_launcher: bool = False,
    ) -> PythonProcess:
        title = " ".join(os.path.basename(arg) if i == 0 else arg for i, arg in enumerate(argv))
        return PythonProcess(
            pid=pid,
            parent_pid=parent_pid,
            executable=executable,
            real_executable=real_executable,
            version=self.guess_version(executable, real_executable),
            venv=self.venv_of(executable),
            argv=argv,
            title=title[: self._TITLE_LIMIT],
            cwd=cwd,
            is_launcher=is_launcher,
        )

    @staticmethod
    def _read_link(path: str) -> str | None:
        try:
            return os.readlink(path)
        except OSError:
            return None

    @staticmethod
    def _split_windows_command_line(command_line: str) -> list[str]:
        try:
            return shlex.split(command_line, posix=False)
        except ValueError:
            return command_line.split()


if __name__ == "__main__":
    json.dump([process.to_wire() for process in ProcessLister().list_processes()], sys.stdout)
