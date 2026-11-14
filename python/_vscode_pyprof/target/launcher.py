"""Target-side launcher: runs the user's program *inside their environment*.

The extension's "Run with Profiler" starts it with the user's interpreter (no
``-I``/``-s``) so site-packages, ``.pth`` files and editable installs behave
exactly as with ``python app.py``::

    python -c "<bootstrap>" <pkg-parent> (-m module | script) [args...]

The extension passes the agent address in ``PYPROF_AGENT=host:port:token`` and
the collector options in ``PYPROF_OPTIONS``.

This module runs in the profiled process and with whatever interpreter the user
has: it must import on Python 3.10+ (to report a clear version error) and keeps
imports it rarely needs out of the module top level.
"""

import json
import os
import runpy
import sys
import time
from dataclasses import dataclass
from enum import Enum

from _vscode_pyprof import MIN_PYTHON, PACKAGE_DIR


class LauncherError(Exception):
    """A problem the user has to fix; shown as ``pyprof: <message>``."""


class TargetKind(Enum):
    MODULE = "module"
    """Run like ``python -m name``."""
    PATH = "path"
    """Run like ``python name``."""


@dataclass(frozen=True)
class Target:
    """What to run: a module or a script path, and its arguments."""

    kind: TargetKind
    name: str
    args: list[str]

    @classmethod
    def parse(cls, argv: list[str]) -> "Target":
        """``-m module [args...]`` or ``script [args...]``, as the extension passes them."""
        if not argv:
            raise LauncherError("nothing to run")
        if argv[0] == "-m":
            if len(argv) < 2:
                raise LauncherError("-m requires a module name")
            return cls(TargetKind.MODULE, argv[1], argv[2:])
        if not os.path.exists(argv[0]):
            raise LauncherError(f"cannot find {argv[0]!r}")
        return cls(TargetKind.PATH, argv[0], argv[1:])


class Launcher:
    EXIT_ERROR = 2
    _AGENT_CONNECT_TIMEOUT = 3.0

    def main(self, argv: list[str]) -> None:
        try:
            self.run(argv)
        except LauncherError as error:
            sys.stderr.write(f"pyprof: {error}\n")
            raise SystemExit(self.EXIT_ERROR) from None

    def run(self, argv: list[str]) -> None:
        """Start the agent, then run the target exactly like ``python`` would."""
        self._check_version()
        target = Target.parse(argv)
        self._allow_ptrace()
        agent_address, options = self._agent_endpoint()
        self._start_agent(agent_address, options)
        self._restore_sys_path()
        sys.argv = [target.name, *target.args]
        if target.kind is TargetKind.MODULE:
            sys.path.insert(0, os.getcwd())
            runpy._run_module_as_main(target.name, alter_argv=True)  # what `python -m` does
        else:
            path = os.path.abspath(target.name)
            sys.path.insert(0, os.path.dirname(path))
            runpy.run_path(path, run_name="__main__")

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

    @staticmethod
    def _agent_endpoint() -> tuple[str, dict[str, object]]:
        """Where the agent connects to, and its options; popped so child processes are not auto-profiled."""
        agent_address = os.environ.pop("PYPROF_AGENT", None)
        raw_options = os.environ.pop("PYPROF_OPTIONS", None)
        if not agent_address:
            raise LauncherError("PYPROF_AGENT is not set; start the program with the profiler from VS Code")
        try:
            decoded = json.loads(raw_options) if raw_options else None
        except ValueError:
            decoded = None
        return agent_address, decoded if isinstance(decoded, dict) else {}

    def _start_agent(self, agent_address: str, options: dict[str, object]) -> None:
        # Imported only after the version check: the agent needs Python 3.15.
        from _vscode_pyprof.target import agent

        try:
            started = agent.start(agent_address, options)
        except ValueError as error:  # a malformed PYPROF_AGENT
            raise LauncherError(str(error)) from None
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


def main() -> None:
    Launcher().main(sys.argv[1:])
