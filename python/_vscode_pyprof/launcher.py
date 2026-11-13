"""Target-side launcher: runs the user's program *inside their environment*.

Invoked with the user's interpreter (no ``-I``/``-s``) so site-packages,
``.pth`` files and editable installs behave exactly as with ``python app.py``::

    python -c "<bootstrap>" <pkg-parent> run [-m module | script | command] [args...]

The agent address comes from one of:

* ``PYPROF_AGENT=host:port:token``  - set by the extension for "Run with Profiler"
* ``PYPROF_HUB=host:port:token``    - set in every VS Code terminal; we announce
  ourselves to the extension, which starts a collector and replies with the
  agent address (``pyprof run ...`` typed by the user).
"""

from __future__ import annotations

import json
import os
import runpy
import shutil
import socket
import sys

from . import MIN_PYTHON, PACKAGE_DIR

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

PYTHON_FLAGS_WITH_ARG = {"-W", "-X", "-Q"}


def _die(msg: str, code: int = 2):
    sys.stderr.write(f"pyprof: {msg}\n")
    raise SystemExit(code)


def _check_version():
    if sys.version_info < MIN_PYTHON:
        want = ".".join(map(str, MIN_PYTHON))
        _die(
            f"Python {want}+ is required for profiling, but this environment uses "
            f"Python {sys.version.split()[0]} ({sys.executable}).\n"
            f"  Select a {want} interpreter in VS Code, or create one: uv venv -p {want}"
        )


def _allow_ptrace():
    """Linux Yama: let any same-user process (our collector) attach to us."""
    if not sys.platform.startswith("linux"):
        return
    try:
        import ctypes

        libc = ctypes.CDLL(None, use_errno=True)
        PR_SET_PTRACER = 0x59616D61
        PR_SET_PTRACER_ANY = ctypes.c_ulong(-1).value
        libc.prctl(PR_SET_PTRACER, PR_SET_PTRACER_ANY, 0, 0, 0)
    except Exception:
        pass


def _looks_like_python_exe(name: str) -> bool:
    base = os.path.basename(name).lower()
    if base.endswith(".exe"):
        base = base[:-4]
    return base == "python" or base == "pythonw" or (base.startswith("python") and base[6:].replace(".", "").rstrip("t").isdigit())


def _is_python_script(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            head = f.read(4096)
    except OSError:
        return False
    if head.startswith(b"#!") and b"python" in head.split(b"\n", 1)[0].lower():
        return True
    # Windows console-script .exe: a launcher with a zip (containing __main__.py) appended
    if path.lower().endswith(".exe"):
        import zipfile

        try:
            with zipfile.ZipFile(path) as z:
                return "__main__.py" in z.namelist()
        except (zipfile.BadZipFile, OSError):
            return False
    return path.endswith((".py", ".pyw"))


def parse_target(argv: list[str]):
    """Return ("module", name, args) or ("path", path, args)."""
    if argv and argv[0] == "--":
        argv = argv[1:]
    if not argv:
        _die("nothing to run\n\n" + USAGE)
    if argv[0] == "-m":
        if len(argv) < 2:
            _die("-m requires a module name")
        return "module", argv[1], argv[2:]
    head = argv[0]
    # `pyprof run python [-flags] (-m mod | script) ...`
    if _looks_like_python_exe(head) and not os.path.isfile(head + ".py"):
        rest = argv[1:]
        while rest and rest[0].startswith("-") and rest[0] not in ("-m", "-c", "--"):
            flag = rest.pop(0)
            if flag in PYTHON_FLAGS_WITH_ARG and rest:
                rest.pop(0)
        if rest and rest[0] == "-c":
            _die("`python -c` is not supported; put the code in a file")
        if rest and rest[0] == "--":
            rest = rest[1:]
        return parse_target(rest)
    if os.path.exists(head):
        return "path", head, argv[1:]
    found = shutil.which(head)
    if found and _is_python_script(found):
        return "path", found, argv[1:]
    if found:
        _die(f"{head!r} ({found}) is not a Python program; only Python programs can be profiled")
    _die(f"cannot find {head!r} (not a file, and not a command on PATH)")


def _hub_handshake(hub: str, kind: str, target: str, args: list[str]) -> dict:
    host, port, token = hub.rsplit(":", 2)
    try:
        s = socket.create_connection((host, int(port)), timeout=5)
    except OSError as e:
        _die(f"cannot reach the VS Code extension ({e}). Is the Python Profiler extension running?")
    s.settimeout(60)
    hello = {
        "type": "hello", "token": token, "pid": os.getpid(), "executable": sys.executable,
        "version": sys.version.split()[0], "cwd": os.getcwd(), "kind": kind, "target": target,
        "args": args, "argv": sys.argv,
    }
    s.sendall((json.dumps(hello) + "\n").encode())
    buf = b""
    while b"\n" not in buf:
        chunk = s.recv(65536)
        if not chunk:
            _die("the extension closed the connection")
        buf += chunk
    s.close()
    reply = json.loads(buf.split(b"\n", 1)[0])
    if reply.get("error"):
        _die(reply["error"])
    return reply


def run(argv: list[str]):
    _check_version()
    kind, target, args = parse_target(argv)
    _allow_ptrace()

    agent_addr = os.environ.pop("PYPROF_AGENT", None)
    options = {}
    raw_opts = os.environ.pop("PYPROF_OPTIONS", None)
    if raw_opts:
        try:
            options = json.loads(raw_opts)
        except ValueError:
            pass
    if not agent_addr:
        hub = os.environ.get("PYPROF_HUB")
        if not hub:
            _die("not running inside a VS Code terminal with the Python Profiler extension "
                 "(PYPROF_HUB is not set)")
        reply = _hub_handshake(hub, kind, target, args)
        agent_addr = reply["agent"]
        options.update(reply.get("options") or {})
    os.environ.pop("PYPROF_HUB", None)  # child processes are not auto-profiled

    from . import agent

    host, port, token = agent_addr.rsplit(":", 2)
    ag = agent.start(host, int(port), token, options)
    # Give the agent a moment to connect so the collector starts sampling
    # before user code runs (bounded; never blocks startup for long).
    import time

    deadline = time.monotonic() + 3.0
    while ag.sock is None and ag.is_alive() and time.monotonic() < deadline:
        time.sleep(0.005)
    time.sleep(0.05)

    _cleanup_sys_path()
    if kind == "module":
        sys.argv = [target] + args
        sys.path.insert(0, os.getcwd())
        runpy._run_module_as_main(target, alter_argv=True)  # what `python -m` does
    else:
        path = os.path.abspath(target)
        sys.argv = [target] + args
        sys.path.insert(0, os.path.dirname(path))
        runpy.run_path(path, run_name="__main__")


def _cleanup_sys_path():
    parent = os.path.normcase(os.path.dirname(PACKAGE_DIR))
    sys.path[:] = [p for p in sys.path if not p or os.path.normcase(os.path.abspath(p)) != parent]
    # -c puts '' (cwd) at sys.path[0]; `python script.py` would not, so drop it
    if sys.path and sys.path[0] == "":
        sys.path.pop(0)


def attach(argv: list[str]):
    if not argv or not argv[0].isdigit():
        _die("usage: pyprof attach <pid>")
    hub = os.environ.get("PYPROF_HUB")
    if not hub:
        _die("not running inside a VS Code terminal with the Python Profiler extension")
    _hub_handshake(hub, "attach", argv[0], [])
    print(f"pyprof: profiling PID {argv[0]} in VS Code")


def cli_main():
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(USAGE)
        return
    cmd, rest = argv[0], argv[1:]
    if cmd == "run":
        run(rest)
    elif cmd == "attach":
        attach(rest)
    else:
        # convenience: `pyprof app.py` == `pyprof run app.py`
        run(argv)
