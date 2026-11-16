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
BOOT = "import sys; sys.path.insert(0, sys.argv.pop(1)); from _vspyprof.{mod} import {fn}; {fn}()"


class Client:
    def __init__(self):
        self.proc = subprocess.Popen(
            [sys.executable, "-I", "-c", BOOT.format(mod="collector.cli", fn="main"), PYDIR, "serve"],
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
            if msg["type"] == "Response":
                with self.cv:
                    self.responses[msg["id"]] = msg
                    self.cv.notify_all()
            else:
                if msg["type"] == "Delta":
                    self._apply(msg["data"])
                self.notes.put(msg)

    def _apply(self, d):
        m = self.model
        m["frames"] += d["frames"]
        m["stacks"] += d["stacks"]
        m["samples"] += sum(d["samples"]["count"])  # samples are runs of equal samples (format 2)
        m["asyncSamples"] += sum(d["asyncSamples"]["count"])
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

    def call(self, request_type, params=None, timeout=60):
        self.ids += 1
        mid = self.ids
        request = {"type": "Request", "id": mid, "body": {"type": request_type, **(params or {})}}
        self.proc.stdin.write((json.dumps(request) + "\n").encode())
        self.proc.stdin.flush()
        with self.cv:
            ok = self.cv.wait_for(lambda: mid in self.responses, timeout)
        assert ok, f"timeout waiting for {request_type}"
        r = self.responses.pop(mid)
        if r["error"] is not None:
            raise RuntimeError(r["error"])
        return r["result"]

    def initialize(self, **options):
        return self.call("Initialize", {"options": {"type": "CollectorOptions", **options}})

    def wait_note(self, note_type, pred=lambda p: True, timeout=30):
        end = time.time() + timeout
        while time.time() < end:
            try:
                msg = self.notes.get(timeout=0.2)
            except queue.Empty:
                continue
            if msg["type"] == note_type and pred(msg):
                return msg
        raise AssertionError(f"no {note_type} notification")

    def close(self):
        try:
            self.call("Shutdown", timeout=5)
        except Exception:
            pass
        self.proc.wait(5)

    def funcs(self):
        return {f[1] for f in self.model["frames"]}


def launch_target(client, info, app, *args):
    env = dict(os.environ)
    env["VSPYPROF_AGENT"] = info["agentAddress"]
    env["VSPYPROF_OPTIONS"] = info["agentOptions"]
    return subprocess.Popen(
        [
            sys.executable,
            "-c",
            BOOT.format(mod="target.launcher", fn="main"),
            PYDIR,
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
            info = c.initialize(rateHz=500, stripLauncher=True)
            p = launch_target(c, info, "cpu_bound.py", "3")
            c.wait_note("StateChanged", lambda s: s["state"] == "running")
            c.wait_note("StateChanged", lambda s: s["state"] == "exited", timeout=30)
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
            self.assertFalse(any("_vspyprof" in f for f in files), files)
            self.assertFalse(any("runpy" in f for f in files), files)
            self.assertIn("checksum-worker", c.model["threads"].values())
            self.assertIn("rss", c.model["tracks"])
            with tempfile.TemporaryDirectory() as d:
                path = os.path.join(d, "x.vspyprof")
                c.call("Save", {"path": path})
                with gzip.open(path, "rt") as f:
                    data = json.load(f)
                self.assertEqual(data["format"], "vspyprof")
                self.assertEqual(sum(data["samples"]["count"]), c.model["samples"])
        finally:
            c.close()

    def test_launch_memory_snapshots(self):
        c = Client()
        p = None
        try:
            info = c.initialize(rateHz=200, stripLauncher=True, tracemalloc=True)
            # runs until killed below: snapshots can take seconds on slow runners
            p = launch_target(c, info, "leaky.py", "120")
            c.wait_note("AgentConnected")
            time.sleep(1.5)
            a = c.call("TakeSnapshot", {"label": "A"})
            time.sleep(1.5)
            b = c.call("TakeSnapshot", {"label": "B"})
            self.assertGreater(b["totalSize"], a["totalSize"])
            time.sleep(0.4)
            before, after = (
                {sid: size for sid, size, _count in snap["entries"]}
                for snap in c.model["snapshots"]
                if snap["id"] in (a["snapshotId"], b["snapshotId"])
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
            counts = c.call("CountObjects")
            self.assertTrue(any(count["typeName"].endswith("Record") for count in counts["counts"]))
            self.assertIn("traced", c.model["tracks"])
        finally:
            c.close()
            if p is not None:
                p.kill()
                p.communicate()

    def test_attach_asyncio(self):
        target = subprocess.Popen(
            [sys.executable, os.path.join(APPS, "async_storm.py"), "8"], stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        c = Client()
        try:
            time.sleep(0.5)
            c.initialize(rateHz=500)
            r = c.call("Attach", {"pid": target.pid, "inject": True})
            self.assertTrue(r["injected"], r)
            c.wait_note("AgentConnected", timeout=15)
            c.call("SetAsyncioDebug", {"enabled": True, "slowMs": 50})
            time.sleep(3.5)
            # Some builds (Homebrew's python@3.15 on macOS) lack the AsyncioDebug section that the remote
            # task table and async-aware stacks are read from; the sampler then says so on the timeline.
            no_asyncio_debug = any(
                e["kind"] == "sampler" and "AsyncioDebug section not available" in e["message"]
                for e in c.model["events"]
            )
            if not no_asyncio_debug:
                tasks = c.model["tasks"]
                self.assertTrue(
                    any(t["name"].startswith("worker-") for t in tasks.values()), (tasks, c.model["events"])
                )
                self.assertGreater(c.model["asyncSamples"], 10)
            self.assertIn("loopLag", c.model["tracks"])
            self.assertGreater(max(v for _, v in c.model["tracks"]["loopLag"]), 100)
            kinds = {e["kind"] for e in c.model["events"]}
            self.assertIn("slow-callback", kinds)
            self.assertIn("slow_db_query", c.funcs())
            c.call("Stop")
        finally:
            c.close()
            target.kill()

    def test_blocking_mode_has_no_discarded_samples(self):
        c = Client()
        try:
            info = c.initialize(rateHz=300, stripLauncher=True, blocking=True)
            p = launch_target(c, info, "cpu_bound.py", "2")
            c.wait_note("StateChanged", lambda s: s["state"] == "exited", timeout=30)
            p.communicate(timeout=10)
            st = c.call("GetStatus")["stats"]
            self.assertGreater(st["samples"], 100)
            self.assertLess(st["errors"] / st["samples"], 0.03, st)
        finally:
            c.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
