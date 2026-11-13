"""List running Python processes as JSON.

Runs with *any* Python 3.8+ (it is used before we know which interpreter the
target uses), so it must stay stdlib-only and avoid new syntax.

    python -I processes.py            -> JSON list on stdout
"""

import json
import os
import re
import subprocess
import sys

_PY_RE = re.compile(r"^python(\d(\.\d+)?t?)?(\.exe)?$|^pythonw(\.exe)?$", re.I)
_VER_RE = re.compile(r"python(\d)\.(\d+)", re.I)


def _is_python_name(path):
    return bool(_PY_RE.match(os.path.basename(path or "")))


def _venv_of(exe):
    """Return the venv root if ``exe`` lives in one (pyvenv.cfg next to bin/Scripts)."""
    if not exe:
        return None
    root = os.path.dirname(os.path.dirname(exe))
    if os.path.isfile(os.path.join(root, "pyvenv.cfg")):
        return root
    return None


def _version_guess(exe, real):
    for p in (real, exe):
        m = _VER_RE.search(os.path.basename(p or ""))
        if m:
            return "%s.%s" % (m.group(1), m.group(2))
    root = _venv_of(exe)
    if root:
        try:
            with open(os.path.join(root, "pyvenv.cfg")) as f:
                for line in f:
                    k, _, v = line.partition("=")
                    if k.strip() in ("version", "version_info"):
                        return ".".join(v.strip().split(".")[:2])
        except OSError:
            pass
    return None


def _linux():
    me = os.getpid()
    out = []
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        pid = int(name)
        if pid == me:
            continue
        try:
            exe = os.readlink("/proc/%d/exe" % pid)
        except OSError:
            exe = ""
        try:
            with open("/proc/%d/cmdline" % pid, "rb") as f:
                argv = [a.decode("utf-8", "replace") for a in f.read().split(b"\0") if a]
        except OSError:
            continue
        if not argv:
            continue
        if not (_is_python_name(exe) or _is_python_name(argv[0])):
            continue
        try:
            with open("/proc/%d/stat" % pid, "rb") as f:
                data = f.read()
            ppid = int(data[data.rindex(b")") + 2:].split()[1])
        except (OSError, ValueError):
            ppid = 0
        launched = argv[0] if os.path.isabs(argv[0]) else exe
        try:
            cwd = os.readlink("/proc/%d/cwd" % pid)
        except OSError:
            cwd = None
        out.append(_rec(pid, ppid, launched or exe, exe, argv, cwd))
    return out


def _darwin():
    res = subprocess.run(
        ["ps", "-axww", "-o", "pid=,ppid=,comm=,args="],
        capture_output=True, text=True, timeout=5,
    )
    out = []
    me = os.getpid()
    for line in res.stdout.splitlines():
        parts = line.strip().split(None, 3)
        if len(parts) < 3:
            continue
        pid, ppid, comm = int(parts[0]), int(parts[1]), parts[2]
        args = parts[3] if len(parts) > 3 else comm
        if pid == me or not _is_python_name(comm):
            continue
        argv = args.split()
        out.append(_rec(pid, ppid, comm, os.path.realpath(comm) if os.path.isabs(comm) else comm, argv, None))
    return out


def _windows():
    ps = (
        "Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" | "
        "Select-Object ProcessId,ParentProcessId,ExecutablePath,CommandLine | ConvertTo-Json -Compress"
    )
    res = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
        capture_output=True, text=True, timeout=15,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    data = json.loads(res.stdout or "[]")
    if isinstance(data, dict):
        data = [data]
    me = os.getpid()
    out = []
    pids = {d.get("ProcessId") for d in data}
    for d in data:
        pid = d.get("ProcessId")
        if pid == me or d.get("ParentProcessId") == me:
            continue
        exe = d.get("ExecutablePath") or ""
        cmd = d.get("CommandLine") or exe
        rec = _rec(pid, d.get("ParentProcessId") or 0, exe, exe, _split_win(cmd), None)
        # venv launchers on Windows spawn the real interpreter as a child
        rec["isLauncher"] = any(o.get("ParentProcessId") == pid for o in data) and _venv_of(exe) is not None
        rec["hasPythonParent"] = rec["ppid"] in pids
        out.append(rec)
    return out


def _split_win(cmd):
    try:
        import shlex

        return shlex.split(cmd, posix=False)
    except ValueError:
        return cmd.split()


def _rec(pid, ppid, exe, real, argv, cwd):
    title = " ".join(os.path.basename(a) if i == 0 else a for i, a in enumerate(argv))
    return {
        "pid": pid,
        "ppid": ppid,
        "executable": exe,
        "realExecutable": real,
        "version": _version_guess(exe, real),
        "venv": _venv_of(exe),
        "argv": argv,
        "title": title[:300],
        "cwd": cwd,
    }


def list_processes():
    try:
        if sys.platform.startswith("linux"):
            return _linux()
        if sys.platform == "darwin":
            return _darwin()
        if sys.platform == "win32":
            return _windows()
    except Exception as e:  # pragma: no cover - diagnostics only
        sys.stderr.write("process listing failed: %r\n" % (e,))
    return []


if __name__ == "__main__":
    json.dump(list_processes(), sys.stdout)
