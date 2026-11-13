"""Starts the in-process agent inside an already running program (attach mode)."""

import os
import sys
import tempfile
import threading

from _vscode_pyprof import PACKAGE_DIR
from _vscode_pyprof.wire import JsonObject


class AgentInjectionError(RuntimeError):
    """The agent could not be injected into the target."""


class AgentInjector:
    """Uses ``sys.remote_exec`` (PEP 768) to run a bootstrap script in the target."""

    _SCRIPT_LIFETIME = 60.0  # the target runs the script at its next safe point

    def __init__(self) -> None:
        self._script_path: str | None = None

    @staticmethod
    def is_supported() -> bool:
        return hasattr(sys, "remote_exec")

    def inject(self, pid: int, agent_address: str, options: JsonObject) -> None:
        if not self.is_supported():
            raise AgentInjectionError("sys.remote_exec is not available in this interpreter")
        path = self._write_script(agent_address, options)
        self._script_path = path
        try:
            sys.remote_exec(pid, path)
        except Exception as error:  # remote_exec raises a wide range of OS and runtime errors
            self.cleanup()
            message = str(error)
            if "disable" in message.lower():
                message += (
                    " (the target disabled remote debugging via PYTHON_DISABLE_REMOTE_DEBUG / -X disable_remote_debug)"
                )
            raise AgentInjectionError(message) from error
        timer = threading.Timer(self._SCRIPT_LIFETIME, self.cleanup)
        timer.daemon = True
        timer.start()

    def cleanup(self) -> None:
        """Delete the bootstrap script (called once the agent has connected)."""
        path, self._script_path = self._script_path, None
        if path is not None:
            try:
                os.unlink(path)
            except OSError:
                pass

    @staticmethod
    def _write_script(agent_address: str, options: JsonObject) -> str:
        host, port, token = agent_address.rsplit(":", 2)
        package_parent = os.path.dirname(PACKAGE_DIR)
        # The package is put on sys.path only for the import, so it can never
        # shadow or leak into the user's own imports.
        script = (
            "def _pyprof_boot():\n"
            "    import sys\n"
            f"    p = {package_parent!r}\n"
            "    added = p not in sys.path\n"
            "    if added:\n"
            "        sys.path.insert(0, p)\n"
            "    try:\n"
            "        from _vscode_pyprof import agent\n"
            "    finally:\n"
            "        if added and p in sys.path:\n"
            "            sys.path.remove(p)\n"
            f"    agent.start({host!r}, {int(port)}, {token!r}, {options!r})\n"
            "_pyprof_boot()\n"
            "del _pyprof_boot\n"
        )
        fd, path = tempfile.mkstemp(prefix="pyprof_inject_", suffix=".py")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(script)
        return path
