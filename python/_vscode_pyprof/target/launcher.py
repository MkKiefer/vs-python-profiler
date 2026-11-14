"""Target-side launcher: runs the user's program *inside their environment*.

Invoked with the user's interpreter (no ``-I``/``-s``) so site-packages,
``.pth`` files and editable installs behave exactly as with ``python app.py``::

    python -c "<bootstrap>" <pkg-parent> run [-m module | script | command] [args...]

The agent address comes from one of:

* ``PYPROF_AGENT=host:port:token``  - set by the extension for "Run with Profiler"
* ``PYPROF_HUB=host:port:token``    - set in every VS Code terminal; we announce
  ourselves to the extension, which starts a collector and replies with the
  agent address (``pyprof run ...`` typed by the user).

This module runs in the profiled process and with whatever interpreter the user
has: it must import on Python 3.10+ (to report a clear version error) and keeps
imports it rarely needs out of the module top level.
"""

import json
import os
import runpy
import shutil
import socket
import sys
import time
from dataclasses import dataclass

from _vscode_pyprof import MIN_PYTHON, PACKAGE_DIR


class LauncherError(Exception):
    """A problem the user has to fix; shown as ``pyprof: <message>``."""


@dataclass(frozen=True)
class Target:
    """What to run: a module (``python -m name``) or a script path."""

    kind: str
    name: str
    args: list[str]

    MODULE = "module"
    PATH = "path"


class TargetParser:
    """Understands everything a user may type after ``pyprof run``."""

    _PYTHON_FLAGS_WITH_ARGUMENT = frozenset({"-W", "-X", "-Q"})

    def parse(self, argv: list[str]) -> Target:
        if argv and argv[0] == "--":
            argv = argv[1:]
        if not argv:
            raise LauncherError("nothing to run\n\n" + Launcher.USAGE)
        head = argv[0]
        if head == "-m":
            if len(argv) < 2:
                raise LauncherError("-m requires a module name")
            return Target(Target.MODULE, argv[1], argv[2:])
        # `pyprof run python [-flags] (-m mod | script) ...`
        if self.looks_like_python_executable(head) and not os.path.isfile(head + ".py"):
            return self.parse(self._without_interpreter_flags(argv[1:]))
        if os.path.exists(head):
            return Target(Target.PATH, head, argv[1:])
        found = shutil.which(head)
        if found is None:
            raise LauncherError(f"cannot find {head!r} (not a file, and not a command on PATH)")
        if not self.is_python_script(found):
            raise LauncherError(f"{head!r} ({found}) is not a Python program; only Python programs can be profiled")
        return Target(Target.PATH, found, argv[1:])

    @staticmethod
    def looks_like_python_executable(name: str) -> bool:
        base = os.path.basename(name).lower().removesuffix(".exe")
        if base in ("python", "pythonw"):
            return True
        # python3, python3.15, python3.15t
        return base.startswith("python") and base[6:].replace(".", "").rstrip("t").isdigit()

    @staticmethod
    def is_python_script(path: str) -> bool:
        try:
            with open(path, "rb") as f:
                head = f.read(4096)
        except OSError:
            return False
        if head.startswith(b"#!") and b"python" in head.split(b"\n", 1)[0].lower():
            return True
        # Windows console-script .exe: a launcher with a zip (containing __main__.py) appended
        if path.lower().endswith(".exe"):
            import zipfile  # rarely needed; keep it out of the profiled program's startup

            try:
                with zipfile.ZipFile(path) as archive:
                    return "__main__.py" in archive.namelist()
            except (zipfile.BadZipFile, OSError):
                return False
        return path.endswith((".py", ".pyw"))

    def _without_interpreter_flags(self, args: list[str]) -> list[str]:
        rest = list(args)
        while rest and rest[0].startswith("-") and rest[0] not in ("-m", "-c", "--"):
            flag = rest.pop(0)
            if flag in self._PYTHON_FLAGS_WITH_ARGUMENT and rest:
                rest.pop(0)
        if rest and rest[0] == "-c":
            raise LauncherError("`python -c` is not supported; put the code in a file")
        return rest


class HubClient:
    """Talks to the extension's terminal hub (``PYPROF_HUB``)."""

    _CONNECT_TIMEOUT = 5.0
    _REPLY_TIMEOUT = 60.0

    def __init__(self, address: str) -> None:
        host, port, token = address.rsplit(":", 2)
        self._endpoint = (host, int(port))
        self._token = token

    def announce(self, kind: str, target: str, args: list[str]) -> dict[str, object]:
        """Tell the extension what is about to run; returns its reply."""
        hello = {
            "type": "hello",
            "token": self._token,
            "pid": os.getpid(),
            "executable": sys.executable,
            "version": sys.version.split()[0],
            "cwd": os.getcwd(),
            "kind": kind,
            "target": target,
            "args": args,
            "argv": sys.argv,
        }
        try:
            connection = socket.create_connection(self._endpoint, timeout=self._CONNECT_TIMEOUT)
        except OSError as error:
            raise LauncherError(
                f"cannot reach the VS Code extension ({error}). Is the Python Profiler extension running?"
            ) from error
        with connection:
            connection.settimeout(self._REPLY_TIMEOUT)
            connection.sendall((json.dumps(hello) + "\n").encode())
            buffer = b""
            while b"\n" not in buffer:
                chunk = connection.recv(65536)
                if not chunk:
                    raise LauncherError("the extension closed the connection")
                buffer += chunk
        reply = json.loads(buffer.split(b"\n", 1)[0])
        if not isinstance(reply, dict):
            raise LauncherError("unexpected reply from the extension")
        if reply.get("error"):
            raise LauncherError(str(reply["error"]))
        return reply


class Launcher:
    USAGE = """\
usage: pyprof run [-m module | script.py | command] [args...]
       pyprof attach <pid>

Examples:
  pyprof run app.py --port 8000
  pyprof run -m mypkg.cli
  pyprof run uvicorn app:main --reload
  pyprof run -- python -m pytest -k slow
  uv run pyprof run app.py

Must be run from a VS Code terminal with the Python Profiler extension active.
"""
    EXIT_ERROR = 2
    _AGENT_CONNECT_TIMEOUT = 3.0
    _NOT_IN_VSCODE = "not running inside a VS Code terminal with the Python Profiler extension (PYPROF_HUB is not set)"

    def __init__(self, parser: TargetParser) -> None:
        self._parser = parser

    def main(self, argv: list[str]) -> None:
        if not argv or argv[0] in ("-h", "--help", "help"):
            print(self.USAGE)
            return
        try:
            if argv[0] == "run":
                self.run(argv[1:])
            elif argv[0] == "attach":
                self.attach(argv[1:])
            else:
                self.run(argv)  # convenience: `pyprof app.py` == `pyprof run app.py`
        except LauncherError as error:
            sys.stderr.write(f"pyprof: {error}\n")
            raise SystemExit(self.EXIT_ERROR) from None

    def run(self, argv: list[str]) -> None:
        """Start the agent, then run the target exactly like ``python`` would."""
        self._check_version()
        target = self._parser.parse(argv)
        self._allow_ptrace()
        agent_address, options = self._agent_endpoint(target)
        self._start_agent(agent_address, options)
        self._restore_sys_path()
        sys.argv = [target.name, *target.args]
        if target.kind == Target.MODULE:
            sys.path.insert(0, os.getcwd())
            runpy._run_module_as_main(target.name, alter_argv=True)  # what `python -m` does
        else:
            path = os.path.abspath(target.name)
            sys.path.insert(0, os.path.dirname(path))
            runpy.run_path(path, run_name="__main__")

    def attach(self, argv: list[str]) -> None:
        if not argv or not argv[0].isdigit():
            raise LauncherError("usage: pyprof attach <pid>")
        hub = os.environ.get("PYPROF_HUB")
        if not hub:
            raise LauncherError(self._NOT_IN_VSCODE)
        HubClient(hub).announce("attach", argv[0], [])
        print(f"pyprof: profiling PID {argv[0]} in VS Code")

    # --------------------------------------------------------------- helpers
    @staticmethod
    def _check_version() -> None:
        if sys.version_info >= MIN_PYTHON:
            return
        wanted = ".".join(map(str, MIN_PYTHON))
        raise LauncherError(
            f"Python {wanted}+ is required for profiling, but this environment uses "
            f"Python {sys.version.split()[0]} ({sys.executable}).\n"
            f"  Select a {wanted} interpreter in VS Code, or create one: uv venv -p {wanted}"
        )

    @staticmethod
    def _allow_ptrace() -> None:
        """Linux Yama: let any same-user process (our collector) attach to us."""
        if not sys.platform.startswith("linux"):
            return
        import ctypes  # Linux only; keep it out of the profiled program elsewhere

        pr_set_ptracer = 0x59616D61
        pr_set_ptracer_any = ctypes.c_ulong(-1).value
        try:
            ctypes.CDLL(None, use_errno=True).prctl(pr_set_ptracer, pr_set_ptracer_any, 0, 0, 0)
        except (OSError, AttributeError):
            pass  # no Yama / no prctl: attaching either works anyway or reports its own error

    def _agent_endpoint(self, target: Target) -> tuple[str, dict[str, object]]:
        """Where the agent connects to, and its options (from the environment or the hub)."""
        options: dict[str, object] = {}
        raw_options = os.environ.pop("PYPROF_OPTIONS", None)
        if raw_options:
            try:
                decoded = json.loads(raw_options)
            except ValueError:
                decoded = None
            if isinstance(decoded, dict):
                options = decoded
        agent_address = os.environ.pop("PYPROF_AGENT", None)
        hub = os.environ.pop("PYPROF_HUB", None)  # popped: child processes are not auto-profiled
        if agent_address:
            return agent_address, options
        if not hub:
            raise LauncherError(self._NOT_IN_VSCODE)
        reply = HubClient(hub).announce(target.kind, target.name, target.args)
        hub_options = reply.get("options")
        if isinstance(hub_options, dict):
            options.update(hub_options)
        return str(reply["agent"]), options

    def _start_agent(self, agent_address: str, options: dict[str, object]) -> None:
        # Imported only after the version check: the agent needs Python 3.15.
        from _vscode_pyprof.target import agent

        host, port, token = agent_address.rsplit(":", 2)
        started = agent.start(host, int(port), token, options)
        # Give the agent a moment to connect so the collector starts sampling
        # before user code runs (bounded; never blocks startup for long).
        deadline = time.monotonic() + self._AGENT_CONNECT_TIMEOUT
        while not started.connected and started.is_alive() and time.monotonic() < deadline:
            time.sleep(0.005)
        time.sleep(0.05)

    @staticmethod
    def _restore_sys_path() -> None:
        """Make ``sys.path`` look as if the target had been started directly."""
        parent = os.path.normcase(os.path.dirname(PACKAGE_DIR))
        sys.path[:] = [p for p in sys.path if not p or os.path.normcase(os.path.abspath(p)) != parent]
        # -c puts '' (cwd) at sys.path[0]; `python script.py` would not, so drop it
        if sys.path and sys.path[0] == "":
            sys.path.pop(0)


def cli_main() -> None:
    Launcher(TargetParser()).main(sys.argv[1:])
