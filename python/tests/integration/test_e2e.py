"""End-to-end tests: drive the collector over stdio exactly like the extension.

Run with a Python >= 3.15 interpreter:

    cd python && pdm run test:integration        (or)    python3.15 python/tests/integration/test_e2e.py
"""

from __future__ import annotations

import gzip
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
PYDIR = os.path.join(ROOT, "python")
APPS = os.path.join(ROOT, "test-apps")
BOOT = "import sys; sys.path.insert(0, sys.argv.pop(1)); from _vscode_pyprof.{mod} import {fn}; {fn}()"


class Client:
    def __init__(self):
        self.proc = subprocess.Popen(
            [sys.executable, "-I", "-c", BOOT.format(mod="cli", fn="main"), PYDIR, "serve"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=sys.stderr,
        )
        self.ids = 0
        self.responses: dict = {}
        self.notes: queue.Queue = queue.Queue()
        self.cv = threading.Condition()
        self.model = {
            "frames": [],
            "stacks": [],
            "samples": 0,
            "asyncSamples": 0,
            "tasks": {},
            "tracks": {},
            "gc": 0,
            "sampleStacks": set(),
            "events": [],
            "threads": {},
            "snapshots": [],
        }
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.proc.stdout:
            msg = json.loads(line)
            if "id" in msg:
                with self.cv:
                    self.responses[msg["id"]] = msg
                    self.cv.notify_all()
            else:
                if msg["method"] == "delta":
                    self._apply(msg["params"])
                self.notes.put(msg)

    def _apply(self, d):
        m = self.model
        m["frames"] += d["frames"]
        m["stacks"] += d["stacks"]
        m["samples"] += len(d["samples"]["t"])
        m["asyncSamples"] += len(d["asyncSamples"]["t"])
        for t in d["tasks"]:
            m["tasks"][t["id"]] = t
        for k, v in d["tracks"].items():
            m["tracks"].setdefault(k, []).extend(v)
        m["gc"] += len(d["gc"])
        m["events"] += d["events"]
        m["threads"].update(d["threads"])
        m["snapshots"] += d["snapshots"]
        # every stack/frame reference must already be known
        for sid in d["samples"]["stack"]:
            assert 0 <= sid < len(m["stacks"]), sid
            m["sampleStacks"].add(sid)

    def call(self, method, params=None, timeout=60):
        self.ids += 1
        mid = self.ids
        self.proc.stdin.write((json.dumps({"id": mid, "method": method, "params": params or {}}) + "\n").encode())
        self.proc.stdin.flush()
        with self.cv:
            ok = self.cv.wait_for(lambda: mid in self.responses, timeout)
        assert ok, f"timeout waiting for {method}"
        r = self.responses.pop(mid)
        if "error" in r:
            raise RuntimeError(r["error"]["message"])
        return r["result"]

    def wait_note(self, method, pred=lambda p: True, timeout=30):
        end = time.time() + timeout
        while time.time() < end:
            try:
                msg = self.notes.get(timeout=0.2)
            except queue.Empty:
                continue
            if msg["method"] == method and pred(msg["params"]):
                return msg["params"]
        raise AssertionError(f"no {method} notification")

    def close(self):
        try:
            self.call("shutdown", timeout=5)
        except Exception:
            pass
        self.proc.wait(5)

    def funcs(self):
        return {f[1] for f in self.model["frames"]}


def launch_target(client, info, app, *args, options=None):
    env = dict(os.environ)
    env["PYPROF_AGENT"] = info["agentAddress"]
    if options:
        env["PYPROF_OPTIONS"] = json.dumps(options)
    return subprocess.Popen(
        [
            sys.executable,
            "-c",
            BOOT.format(mod="launcher", fn="cli_main"),
            PYDIR,
            "run",
            os.path.join(APPS, app),
            *args,
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=APPS,
    )


class E2E(unittest.TestCase):
    def test_launch_cpu(self):
        c = Client()
        try:
            info = c.call("initialize", {"options": {"rateHz": 500, "stripLauncher": True}})
            p = launch_target(c, info, "cpu_bound.py", "3")
            c.wait_note("state", lambda s: s["state"] == "running")
            c.wait_note("state", lambda s: s["state"] == "exited", timeout=30)
            out, err = p.communicate(timeout=10)
            self.assertIn(b"done", out, err)
            time.sleep(0.4)
            funcs = c.funcs()
            self.assertGreater(c.model["samples"], 300)
            for f in ("fib", "checksum", "Worker.run", "parse_rows"):
                self.assertIn(f, funcs)
            # the launcher, runpy and agent must not leak into user stacks
            files = set()
            for sid in c.model["sampleStacks"]:
                while sid >= 0:
                    sid, fid = c.model["stacks"][sid]
                    files.add(c.model["frames"][fid][0])
            self.assertFalse(any("_vscode_pyprof" in f for f in files), files)
            self.assertFalse(any("runpy" in f for f in files), files)
            self.assertIn("checksum-worker", c.model["threads"].values())
            self.assertIn("rss", c.model["tracks"])
            with tempfile.TemporaryDirectory() as d:
                path = os.path.join(d, "x.pyprof")
                c.call("save", {"path": path})
                with gzip.open(path, "rt") as f:
                    data = json.load(f)
                self.assertEqual(data["format"], "pyprof")
                self.assertEqual(len(data["samples"]["t"]), c.model["samples"])
        finally:
            c.close()

    def test_launch_memory_snapshots(self):
        c = Client()
        try:
            info = c.call("initialize", {"options": {"rateHz": 200, "stripLauncher": True, "tracemalloc": True}})
            p = launch_target(c, info, "leaky.py", "6", options={"tracemalloc": True})
            c.wait_note("agent", lambda a: a["connected"])
            time.sleep(1.5)
            a = c.call("snapshot", {"label": "A"})
            time.sleep(1.5)
            b = c.call("snapshot", {"label": "B"})
            self.assertGreater(b["totalSize"], a["totalSize"])
            time.sleep(0.4)
            before, after = (
                {sid: size for sid, size, _count in snap["entries"]}
                for snap in c.model["snapshots"]
                if snap["id"] in (a["id"], b["id"])
            )
            top_sid = max(after, key=lambda sid: after[sid] - before.get(sid, 0))
            # walk the top growing stack: should end in Record.__init__ / handle_request
            names = []
            sid = top_sid
            while sid >= 0:
                parent, fid = c.model["stacks"][sid]
                names.append(c.model["frames"][fid][1])
                sid = parent
            self.assertTrue({"handle_request", "Record.__init__"} & set(names), names)
            counts = c.call("objectCounts")
            self.assertTrue(any(n.endswith("Record") for n, _ in counts["counts"]))
            self.assertIn("traced", c.model["tracks"])
            p.wait(20)
        finally:
            c.close()

    def test_attach_asyncio(self):
        target = subprocess.Popen(
            [sys.executable, os.path.join(APPS, "async_storm.py"), "8"], stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        c = Client()
        try:
            time.sleep(0.5)
            c.call("initialize", {"options": {"rateHz": 500}})
            r = c.call("attach", {"pid": target.pid, "inject": True})
            self.assertTrue(r["injected"], r)
            c.wait_note("agent", lambda a: a["connected"], timeout=15)
            c.call("asyncioDebug", {"enabled": True, "slowMs": 50})
            time.sleep(3.5)
            tasks = c.model["tasks"]
            self.assertTrue(any(t["name"].startswith("worker-") for t in tasks.values()), tasks)
            self.assertGreater(c.model["asyncSamples"], 10)
            self.assertIn("loopLag", c.model["tracks"])
            self.assertGreater(max(v for _, v in c.model["tracks"]["loopLag"]), 100)
            kinds = {e["kind"] for e in c.model["events"]}
            self.assertIn("slow-callback", kinds)
            self.assertIn("slow_db_query", c.funcs())
            c.call("stop", {})
        finally:
            c.close()
            target.kill()

    def test_terminal_hub_handshake(self):
        """`pyprof run` in a VS Code terminal: launcher → hub → collector → agent."""
        import socket

        token = "t0ken"
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        result = {}
        c = Client()

        def hub():
            conn, _ = srv.accept()
            hello = json.loads(conn.makefile().readline())
            result["hello"] = hello
            info = c.call("initialize", {"options": {"rateHz": 300, "stripLauncher": True}})
            conn.sendall((json.dumps({"agent": info["agentAddress"], "options": {}}) + "\n").encode())
            conn.close()

        threading.Thread(target=hub, daemon=True).start()
        try:
            env = dict(os.environ, PYPROF_HUB=f"127.0.0.1:{port}:{token}")
            env.pop("PYPROF_AGENT", None)
            shim = os.path.join(ROOT, "bin", "pyprof")
            cmd = (
                [sys.executable, "-c", BOOT.format(mod="launcher", fn="cli_main"), PYDIR] if os.name == "nt" else [shim]
            )
            env["PYPROF_PYTHON"] = sys.executable
            # `python app.py` form, like a user would type after `pyprof run`
            p = subprocess.run(
                [*cmd, "run", "--", "python", os.path.join(APPS, "cpu_bound.py"), "2"],
                env=env,
                capture_output=True,
                timeout=60,
                cwd=APPS,
            )
            self.assertEqual(p.returncode, 0, p.stderr.decode())
            self.assertIn(b"done", p.stdout)
            self.assertEqual(result["hello"]["token"], token)
            self.assertTrue(result["hello"]["target"].endswith("cpu_bound.py"))
            time.sleep(0.5)
            self.assertIn("fib", c.funcs())
        finally:
            c.close()
            srv.close()

    def test_blocking_mode_has_no_discarded_samples(self):
        c = Client()
        try:
            info = c.call("initialize", {"options": {"rateHz": 300, "stripLauncher": True, "blocking": True}})
            p = launch_target(c, info, "cpu_bound.py", "2")
            c.wait_note("state", lambda s: s["state"] == "exited", timeout=30)
            p.communicate(timeout=10)
            st = c.call("status")["stats"]
            self.assertGreater(st["samples"], 100)
            self.assertLess(st["errors"] / st["samples"], 0.03, st)
        finally:
            c.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
