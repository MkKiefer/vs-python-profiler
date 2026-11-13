"""Collector session: owns the sampler, the agent connection and the store.

One collector process serves exactly one profiling session. It always runs
with the *target's* interpreter (Tachyon's remote unwinder is tied to the
target's CPython version and build).
"""

from __future__ import annotations

import gzip
import json
import os
import sys
import tempfile
import threading

from . import PACKAGE_DIR, PROTOCOL_VERSION
from .agent_server import AgentServer
from .funcresolver import FuncResolver
from .rpc import Rpc, RpcError
from .sampler import Sampler, SamplerError, check_support, rd
from .store import Store

DEFAULT_OPTIONS = {
    "rateHz": 1000,
    "native": False,
    "gc": True,
    "asyncAware": True,
    "tracemalloc": False,
    "tracemallocFrames": 16,
    "asyncioDebug": False,
    "slowCallbackMs": 100,
    "stripLauncher": False,
    "blocking": False,
}


class Collector:
    def __init__(self, rpc: Rpc):
        self.rpc = rpc
        self.options = dict(DEFAULT_OPTIONS)
        self.store: Store | None = None
        self.sampler: Sampler | None = None
        self.agent = None
        self.server = AgentServer(self._on_agent_hello, self._on_agent_message, self._on_agent_close)
        self.resolver = FuncResolver()
        self.target_pid: int | None = None
        self.state = "idle"
        self._snap_seq = 0
        self._pump_stop = threading.Event()
        self._inject_file = None
        self._lock = threading.RLock()
        for name in ("initialize", "attach", "stop", "tracemalloc", "snapshot", "diff",
                     "objectCounts", "asyncioDebug", "mark", "save", "shutdown", "status"):
            rpc.handlers[name] = getattr(self, "rpc_" + name)

    # ================================================================ RPC API
    def rpc_initialize(self, p):
        check_support()
        self.options.update({k: v for k, v in (p.get("options") or {}).items() if v is not None})
        self.store = Store(strip_launcher=bool(self.options.get("stripLauncher")))
        self.store.set_meta(options=self.options, label=p.get("label"), command=p.get("command"))
        threading.Thread(target=self._pump, name="pyprof-pump", daemon=True).start()
        return {
            "protocol": PROTOCOL_VERSION,
            "python": sys.version.split()[0],
            "executable": sys.executable,
            "platform": sys.platform,
            "pid": os.getpid(),
            "agentAddress": self.server.address,
            "packageDir": PACKAGE_DIR,
            "features": {
                "gcStats": hasattr(rd, "GCMonitor") or hasattr(rd, "get_gc_stats"),
                "remoteExec": hasattr(sys, "remote_exec"),
                "asyncAware": True,
            },
        }

    def rpc_attach(self, p):
        pid = int(p["pid"])
        self._start_sampler(pid)
        injected = False
        inject_error = None
        if p.get("inject", True) and self.agent is None:
            try:
                self._inject(pid)
                injected = True
            except Exception as e:  # sampling still works without the agent
                inject_error = str(e)
                self.store.add_event("agent", f"Agent injection failed: {e}")
        return {"pid": self.sampler.pid, "injected": injected, "injectError": inject_error}

    def rpc_stop(self, p):
        with self._lock:
            if self.sampler:
                self.sampler.stop()
                self.sampler.join(2)
            if self.agent is not None:
                self.agent.close()
                self.agent = None
            self.state = "stopped"
        self._flush()
        self.rpc.notify("state", {"state": "stopped", "reason": p.get("reason", "user")})
        return {"ok": True}

    def rpc_status(self, p):
        return {"state": self.state, "pid": self.target_pid, "agent": self.agent is not None,
                "stats": self.store.stats if self.store else None}

    def rpc_tracemalloc(self, p):
        agent = self._require_agent()
        self.options["tracemalloc"] = bool(p.get("enabled", True))
        if self.options["tracemalloc"]:
            return agent.request("tracemalloc_start", {"frames": p.get("frames", self.options["tracemallocFrames"])})
        return agent.request("tracemalloc_stop")

    def rpc_snapshot(self, p):
        agent = self._require_agent()
        raw = agent.request("snapshot", {"limit": p.get("limit", 3000)}, timeout=120)
        store = self.store
        entries = []
        with store.lock:
            for frames, size, count in raw["top"]:
                frames = _strip_launcher_frames(frames, store)
                if not frames:
                    continue  # allocated by the launcher itself
                keys = [(f, self.resolver.resolve(f, ln), ln) for f, ln in frames]  # oldest first
                sid, _ = store.intern_path(keys) if keys else (-1, False)
                entries.append([sid, size, count])
        self._snap_seq += 1
        snap = {
            "id": self._snap_seq,
            "label": p.get("label") or f"Snapshot {self._snap_seq}",
            "t": round((raw["t"] - store.t0) * 1000.0, 2),
            "totalSize": raw["totalSize"], "totalCount": raw["totalCount"],
            "otherSize": raw["otherSize"], "otherCount": raw["otherCount"],
            "traced": raw["traced"], "peak": raw["peak"], "takeMs": raw.get("takeMs"),
            "entries": entries,
        }
        store.add_snapshot(snap)
        store.add_marker(snap["label"], snap["t"])
        return {"id": snap["id"], "totalSize": snap["totalSize"], "entries": len(entries)}

    def rpc_diff(self, p):
        a = self.store.snapshots.get(int(p["a"]))
        b = self.store.snapshots.get(int(p["b"]))
        if not a or not b:
            raise RpcError("unknown snapshot id")
        return diff_snapshots(a, b, int(p.get("limit", 500)))

    def rpc_objectCounts(self, p):
        agent = self._require_agent()
        raw = agent.request("object_counts", {"limit": p.get("limit", 60)}, timeout=120)
        t = (raw["t"] - self.store.t0) * 1000.0
        self.store.set_object_counts(t, raw["counts"])
        return {"t": t, "counts": raw["counts"]}

    def rpc_asyncioDebug(self, p):
        agent = self._require_agent()
        self.options["asyncioDebug"] = bool(p.get("enabled", True))
        return agent.request("asyncio_debug", {"enabled": self.options["asyncioDebug"],
                                               "slowMs": p.get("slowMs", self.options["slowCallbackMs"])})

    def rpc_mark(self, p):
        self.store.add_marker(str(p.get("name") or "marker"))
        return {"ok": True}

    def rpc_save(self, p):
        path = p["path"]
        self._flush()
        data = self.store.full()
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        tmp = path + ".tmp"
        with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=6) as f:
            json.dump(data, f, separators=(",", ":"), default=str)
        os.replace(tmp, path)
        return {"path": path, "bytes": os.path.getsize(path)}

    def rpc_shutdown(self, p):
        try:
            self.rpc_stop({"reason": "shutdown"})
        finally:
            self.server.close()
            self._pump_stop.set()
            threading.Timer(0.2, lambda: os._exit(0)).start()
        return {"ok": True}

    # ============================================================== internals
    def _require_agent(self):
        if self.agent is None or not self.agent.alive:
            raise RpcError(
                "The in-process agent is not connected. Memory and asyncio-debug features need it; "
                "CPU sampling works without it."
            )
        return self.agent

    def _start_sampler(self, pid: int):
        with self._lock:
            if self.sampler is not None:
                return
            try:
                self.sampler = Sampler(
                    pid, self.store,
                    rate_hz=int(self.options["rateHz"]),
                    native=bool(self.options["native"]),
                    gc=bool(self.options["gc"]),
                    async_aware=bool(self.options["asyncAware"]),
                    blocking=bool(self.options.get("blocking")),
                    on_exit=self._on_target_exit,
                    on_children=lambda pids: self.rpc.notify("children", {"pids": pids}),
                )
            except SamplerError as e:
                raise RpcError(str(e)) from None
            self.target_pid = self.sampler.pid
            self.store.set_meta(pid=self.sampler.pid)
            self.sampler.start()
            self.state = "running"
        self.rpc.notify("state", {"state": "running", "pid": self.target_pid})

    def _on_target_exit(self, reason):
        self.state = "exited"
        if self.agent is not None:
            self.agent = None
        self._flush()
        self.rpc.notify("state", {"state": "exited", "reason": reason})

    def _inject(self, pid: int):
        if not hasattr(sys, "remote_exec"):
            raise RuntimeError("sys.remote_exec is not available in this interpreter")
        host, port, token = self.server.address.split(":")
        opts = {k: self.options[k] for k in ("tracemalloc", "tracemallocFrames", "asyncioDebug", "slowCallbackMs")}
        parent = os.path.dirname(PACKAGE_DIR)
        code = (
            "def _pyprof_boot():\n"
            "    import sys\n"
            f"    p = {parent!r}\n"
            "    added = p not in sys.path\n"
            "    if added:\n"
            "        sys.path.insert(0, p)\n"
            "    try:\n"
            "        from _vscode_pyprof import agent\n"
            "    finally:\n"
            "        if added and p in sys.path:\n"
            "            sys.path.remove(p)\n"
            f"    agent.start({host!r}, {int(port)}, {token!r}, {opts!r})\n"
            "_pyprof_boot()\n"
            "del _pyprof_boot\n"
        )
        fd, path = tempfile.mkstemp(prefix="pyprof_inject_", suffix=".py")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(code)
        self._inject_file = path
        try:
            sys.remote_exec(pid, path)
        except Exception as e:
            _unlink(path)
            msg = str(e)
            if "disable" in msg.lower():
                msg += " (the target disabled remote debugging via PYTHON_DISABLE_REMOTE_DEBUG / -X disable_remote_debug)"
            raise RuntimeError(msg) from e
        # The script runs at the target's next safe point; clean up later.
        threading.Timer(60, _unlink, args=(path,)).start()

    # -- agent callbacks ------------------------------------------------------
    def _on_agent_hello(self, conn):
        self.agent = conn
        hello = conn.hello
        self.store.set_meta(agent=True, executable=hello.get("executable"), argv=hello.get("argv"),
                            cwd=hello.get("cwd"))
        self._apply_threads(hello.get("threads") or [])
        self.store.add_event("agent", f"Agent connected (pid {hello.get('pid')})")
        if self._inject_file:
            _unlink(self._inject_file)
            self._inject_file = None
        self.rpc.notify("agent", {"connected": True, "pid": hello.get("pid"),
                                  "argv": hello.get("argv"), "cwd": hello.get("cwd")})
        # start mode: the launcher's agent tells us which pid to sample
        if self.sampler is None and hello.get("pid"):
            try:
                self._start_sampler(int(hello["pid"]))
            except RpcError as e:
                self.rpc.notify("error", {"message": str(e)})

    def _on_agent_message(self, conn, msg):
        if msg.get("type") != "metrics":
            return
        store = self.store
        t = store.now()
        self._apply_threads(msg.get("threads") or [])
        if "traced" in msg:
            store.add_track("traced", t, msg["traced"])
            store.add_track("tracedPeak", t, msg["tracedPeak"])
        loops = msg.get("loops")
        if loops:
            store.add_track("loopLag", t, round(max(l["lagMs"] for l in loops), 3))
            tasks = [l["tasks"] for l in loops if l.get("tasks") is not None]
            if tasks:
                store.add_track("loopTasks", t, sum(tasks))
        for ev in msg.get("events") or []:
            ev_t = (ev.pop("t", 0) - store.t0) * 1000.0 if "t" in ev else t
            kind = ev.pop("kind", "asyncio")
            message = ev.pop("message", "")
            store.add_event(kind, message, ev_t, **ev)

    def _on_agent_close(self, conn):
        if self.agent is conn:
            self.agent = None
            if self.store:
                self.store.add_event("agent", "Agent disconnected")
            self.rpc.notify("agent", {"connected": False})

    def _apply_threads(self, threads):
        for ident, native_id, name in threads:
            if native_id is not None:
                self.store.set_thread(native_id, name)
            if ident is not None:
                self.store.set_thread(ident, name)

    # -- streaming -----------------------------------------------------------
    def _flush(self):
        if self.store is not None:
            self.rpc.notify("delta", self.store.delta())

    def _pump(self):
        while not self._pump_stop.wait(0.25):
            if self.rpc.closed.is_set():
                break
            self._flush()


def diff_snapshots(a: dict, b: dict, limit: int):
    ma = {sid: (size, count) for sid, size, count in a["entries"]}
    mb = {sid: (size, count) for sid, size, count in b["entries"]}
    rows = []
    for sid in set(ma) | set(mb):
        sa, ca = ma.get(sid, (0, 0))
        sb, cb = mb.get(sid, (0, 0))
        if sa == sb and ca == cb:
            continue
        rows.append([sid, sb - sa, cb - ca, sb, cb])
    rows.sort(key=lambda r: -abs(r[1]))
    return {
        "a": a["id"], "b": b["id"],
        "totalSizeDiff": b["totalSize"] - a["totalSize"],
        "totalCountDiff": b["totalCount"] - a["totalCount"],
        "rows": rows[:limit],
    }


def _strip_launcher_frames(frames, store):
    """Drop the `-c` bootstrap / launcher / runpy frames at the root of a traceback."""
    i = 0
    while i < len(frames):
        fn = frames[i][0]
        if fn in ("<string>", "<frozen runpy>") or fn.endswith("runpy.py") or store._is_internal_file(fn):
            i += 1
        else:
            break
    return frames[i:]


def _unlink(path):
    try:
        os.unlink(path)
    except OSError:
        pass


def serve():
    out = sys.stdout.buffer
    sys.stdout = sys.stderr  # nothing may print to the RPC channel
    rpc = Rpc(sys.stdin.buffer, out)
    Collector(rpc)
    rpc.serve()
    # stdin closed: the extension went away
    os._exit(0)

