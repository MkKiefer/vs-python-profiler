"""In-memory profile store.

Everything the UI shows is kept in a handful of append-only tables that share
one clock (milliseconds since session start):

* frames   - interned ``[file, func, line, category]``
* stacks   - prefix tree ``[parent_stack, frame]`` (parent -1 = root)
* samples  - columnar ``t / tid / stack / status`` (thread stacks)
* async    - same layout, stacks reconstructed per asyncio task
* tracks   - named time series ``[[t, value], ...]``
* gc, markers, tasks, task_events, snapshots, events

The store hands out *deltas* (everything appended since the last call) so the
extension can stream live data cheaply, and ``full()`` returns the same shape
for saving ``.pyprof`` files. The TypeScript ``ProfileModel`` consumes both.
"""

from __future__ import annotations

import os
import sys
import sysconfig
import threading
import time

from . import PACKAGE_DIR

CAT_USER = 0
CAT_LIB = 1
CAT_STD = 2
CAT_SYNTH = 3

_RUNPY_SUFFIX = os.sep + "runpy.py"


def _norm_dirs(paths):
    out = []
    for p in paths:
        if not p:
            continue
        p = os.path.normcase(os.path.abspath(p))
        if not p.endswith(os.sep):
            p += os.sep
        if p not in out:
            out.append(p)
    return out


def default_dirs():
    """Return (std_dirs, lib_dirs) for the *running* interpreter.

    The collector always runs with the same interpreter as the target, so its
    own sysconfig paths classify the target's frames correctly.
    """
    paths = sysconfig.get_paths()
    std = [paths.get("stdlib"), paths.get("platstdlib")]
    lib = [paths.get("purelib"), paths.get("platlib")]
    # base installation site-packages (venv's base interpreter) and user site
    try:
        base = sysconfig.get_paths(vars={"base": sys.base_prefix, "platbase": sys.base_exec_prefix})
        std += [base.get("stdlib"), base.get("platstdlib")]
        lib += [base.get("purelib"), base.get("platlib")]
    except Exception:
        pass
    for p in sys.path:
        if p and ("site-packages" in p or "dist-packages" in p):
            lib.append(p)
    return _norm_dirs(std), _norm_dirs(lib)


class Store:
    def __init__(self, strip_launcher=False):
        self.lock = threading.RLock()
        self.t0 = time.perf_counter()
        self.t0_ns = time.perf_counter_ns()
        self.wall_start = time.time()
        self.std_dirs, self.lib_dirs = default_dirs()
        self.internal_dir = os.path.normcase(PACKAGE_DIR) + os.sep
        self.strip_launcher = strip_launcher

        self.frames: list[list] = []
        self._frame_ix: dict = {}
        self._file_cat: dict = {}
        self._file_internal: dict = {}

        self.stacks: list[list] = []
        self._stack_ix: dict = {}
        self._stack_internal: list[bool] = []
        self._raw_cache: dict = {}

        self.samples = {"t": [], "tid": [], "stack": [], "status": []}
        self.async_samples = {"t": [], "tid": [], "stack": [], "status": []}
        self.tracks: dict[str, list] = {}
        self.gc: list = []
        self.markers: list = []
        self.events: list = []  # asyncio debug events, warnings, agent logs
        self.threads: dict = {}
        self.tasks: dict = {}
        self.task_events: list = []
        self.snapshots: dict = {}
        self.object_counts: list = []
        self.meta: dict = {
            "python": sys.version.split()[0],
            "implementation": sys.implementation.name,
            "freeThreaded": bool(sysconfig.get_config_var("Py_GIL_DISABLED")),
            "platform": sys.platform,
            "startedAt": self.wall_start,
        }
        self.stats = {"samples": 0, "errors": 0, "rateHz": 0.0}

        self._cursor = self._new_cursor()
        self._dirty_tasks: set = set()
        self._dirty_threads: set = set()
        self._new_snapshots: list = []
        self._new_object_counts = False
        self._meta_dirty = True

    # ------------------------------------------------------------------ time
    def now(self) -> float:
        return (time.perf_counter() - self.t0) * 1000.0

    def ns_to_t(self, ns: int) -> float:
        return (ns - self.t0_ns) / 1e6

    # -------------------------------------------------------------- interning
    def _category(self, filename: str) -> int:
        cat = self._file_cat.get(filename)
        if cat is not None:
            return cat
        if not filename or filename[0] in "<~" or filename == "<native>":
            cat = CAT_SYNTH
        else:
            f = os.path.normcase(filename)
            if any(f.startswith(d) for d in self.lib_dirs):
                cat = CAT_LIB
            elif any(f.startswith(d) for d in self.std_dirs):
                cat = CAT_STD
            else:
                cat = CAT_USER
        self._file_cat[filename] = cat
        return cat

    def _is_internal_file(self, filename: str) -> bool:
        v = self._file_internal.get(filename)
        if v is None:
            v = os.path.normcase(filename).startswith(self.internal_dir)
            self._file_internal[filename] = v
        return v

    def intern_frame(self, filename: str, funcname: str, lineno: int) -> int:
        key = (filename, funcname, lineno)
        fid = self._frame_ix.get(key)
        if fid is None:
            fid = len(self.frames)
            self.frames.append([filename, funcname, lineno, self._category(filename)])
            self._frame_ix[key] = fid
        return fid

    def intern_path(self, frame_keys_root_first) -> tuple[int, bool]:
        """Intern a stack given ``(file, func, line)`` tuples root-first."""
        parent = -1
        internal = False
        for filename, funcname, lineno in frame_keys_root_first:
            fid = self.intern_frame(filename, funcname, lineno)
            key = (parent, fid)
            sid = self._stack_ix.get(key)
            if sid is None:
                sid = len(self.stacks)
                self.stacks.append([parent, fid])
                internal = internal or self._is_internal_file(filename)
                self._stack_internal.append(internal)
                self._stack_ix[key] = sid
            else:
                internal = self._stack_internal[sid]
            parent = sid
        return parent, internal

    @staticmethod
    def _frame_key(fi):
        loc = fi.location
        if loc is None:
            line = 0
        elif isinstance(loc, int):
            line = loc
        else:
            line = loc[0] or 0
        return fi.filename, fi.funcname, line

    def stack_for_frames(self, frame_infos, strip=True):
        """Intern a list of ``FrameInfo`` (leaf first). Cached on the raw tuple."""
        raw = tuple(frame_infos)
        hit = self._raw_cache.get(raw)
        if hit is not None:
            return hit
        keys = [self._frame_key(f) for f in reversed(raw)]  # root first
        if strip and self.strip_launcher:
            # drop the `-c` bootstrap, our launcher and runpy frames at the root
            i = 0
            while i < len(keys):
                fn = keys[i][0]
                if (fn == "<string>" or fn == "<frozen runpy>" or fn.endswith(_RUNPY_SUFFIX)
                        or self._is_internal_file(fn)):
                    i += 1
                else:
                    break
            if i:
                keys = keys[i:]
        sid, internal = self.intern_path(keys) if keys else (-1, True)
        if len(self._raw_cache) > 200_000:
            self._raw_cache.clear()
        self._raw_cache[raw] = (sid, internal)
        return sid, internal

    # ---------------------------------------------------------------- samples
    def add_thread_sample(self, t: float, interpreters) -> int:
        n = 0
        s = self.samples
        with self.lock:
            for interp in interpreters:
                for th in interp.threads:
                    fr = th.frame_info
                    if not fr:
                        continue
                    sid, internal = self.stack_for_frames(fr)
                    if internal or sid < 0:
                        continue
                    s["t"].append(round(t, 3))
                    s["tid"].append(th.thread_id)
                    s["stack"].append(sid)
                    s["status"].append(th.status)
                    n += 1
            self.stats["samples"] += 1
        return n

    def add_async_sample(self, t: float, linear_stacks) -> None:
        s = self.async_samples
        with self.lock:
            for frames, thread_id, _leaf in linear_stacks:
                sid, internal = self.stack_for_frames(frames, strip=False)
                if internal or sid < 0:
                    continue
                s["t"].append(round(t, 3))
                s["tid"].append(thread_id)
                s["stack"].append(sid)
                s["status"].append(0)

    def add_track(self, name: str, t: float, value: float) -> None:
        with self.lock:
            self.tracks.setdefault(name, []).append([round(t, 2), value])

    def add_gc(self, t: float, dur_ms: float, gen: int, collected: int, heap: int) -> None:
        with self.lock:
            self.gc.append([round(t, 3), round(dur_ms, 4), gen, collected, heap])

    def add_marker(self, name: str, t: float | None = None) -> None:
        with self.lock:
            self.markers.append([round(self.now() if t is None else t, 2), name])

    def add_event(self, kind: str, message: str, t: float | None = None, **extra) -> None:
        with self.lock:
            ev = {"t": round(self.now() if t is None else t, 2), "kind": kind, "message": message}
            ev.update(extra)
            self.events.append(ev)

    def set_thread(self, tid, name: str) -> None:
        with self.lock:
            if self.threads.get(tid) != name:
                self.threads[tid] = name
                self._dirty_threads.add(tid)

    def set_meta(self, **kw) -> None:
        with self.lock:
            self.meta.update(kw)
            self._meta_dirty = True

    # ------------------------------------------------------------------ tasks
    def update_tasks(self, t: float, awaited_infos, running_ids) -> None:
        t = round(t, 2)
        seen = set()
        with self.lock:
            for info in awaited_infos:
                for task in info.awaited_by:
                    tid = task.task_id
                    seen.add(tid)
                    frames = []
                    for coro in task.coroutine_stack:
                        frames.extend(coro.call_stack)
                    sid = self.stack_for_frames(frames, strip=False)[0] if frames else -1
                    parent = task.awaited_by[0].task_name if task.awaited_by else None
                    if isinstance(parent, str):
                        parent = None
                    state = "running" if tid in running_ids else "waiting"
                    rec = self.tasks.get(tid)
                    if rec is None:
                        rec = {
                            "id": tid,
                            "name": task.task_name or f"Task-{tid}",
                            "parent": parent,
                            "thread": info.thread_id,
                            "start": t,
                            "end": None,
                            "stack": sid,
                            "state": state,
                        }
                        self.tasks[tid] = rec
                        self.task_events.append([t, tid, state])
                        self._dirty_tasks.add(tid)
                    else:
                        if rec["state"] != state or rec["stack"] != sid or rec["parent"] != parent:
                            if rec["state"] != state:
                                self.task_events.append([t, tid, state])
                            rec["state"] = state
                            rec["stack"] = sid
                            rec["parent"] = parent
                            self._dirty_tasks.add(tid)
            for tid, rec in self.tasks.items():
                if rec["end"] is None and tid not in seen:
                    rec["end"] = t
                    rec["state"] = "done"
                    self.task_events.append([t, tid, "done"])
                    self._dirty_tasks.add(tid)

    # -------------------------------------------------------------- snapshots
    def add_snapshot(self, snap: dict) -> None:
        with self.lock:
            self.snapshots[snap["id"]] = snap
            self._new_snapshots.append(snap["id"])

    def set_object_counts(self, t: float, counts) -> None:
        with self.lock:
            self.object_counts.append({"t": round(t, 2), "counts": counts})
            self._new_object_counts = True

    # ----------------------------------------------------------------- deltas
    @staticmethod
    def _new_cursor():
        return {
            "frames": 0, "stacks": 0, "samples": 0, "async": 0, "gc": 0,
            "markers": 0, "events": 0, "task_events": 0, "tracks": {},
        }

    def _collect(self, cur, everything: bool) -> dict:
        d: dict = {"now": round(self.now(), 2)}
        d["frames"] = self.frames[cur["frames"]:]
        d["stacks"] = self.stacks[cur["stacks"]:]
        i = cur["samples"]
        d["samples"] = {k: v[i:] for k, v in self.samples.items()}
        j = cur["async"]
        d["asyncSamples"] = {k: v[j:] for k, v in self.async_samples.items()}
        tracks = {}
        for name, pts in self.tracks.items():
            k = cur["tracks"].get(name, 0)
            if k < len(pts):
                tracks[name] = pts[k:]
        d["tracks"] = tracks
        d["gc"] = self.gc[cur["gc"]:]
        d["markers"] = self.markers[cur["markers"]:]
        d["events"] = self.events[cur["events"]:]
        d["taskEvents"] = self.task_events[cur["task_events"]:]
        if everything:
            d["tasks"] = list(self.tasks.values())
            d["threads"] = {str(k): v for k, v in self.threads.items()}
            d["snapshots"] = list(self.snapshots.values())
            d["objectCounts"] = self.object_counts
            d["meta"] = self.meta
        else:
            d["tasks"] = [self.tasks[t] for t in self._dirty_tasks if t in self.tasks]
            d["threads"] = {str(k): self.threads[k] for k in self._dirty_threads}
            d["snapshots"] = [self.snapshots[s] for s in self._new_snapshots]
            d["objectCounts"] = self.object_counts[-1:] if self._new_object_counts else []
            if self._meta_dirty:
                d["meta"] = self.meta
        d["stats"] = dict(self.stats)
        return d

    def delta(self) -> dict:
        with self.lock:
            cur = self._cursor
            d = self._collect(cur, everything=False)
            cur["frames"] = len(self.frames)
            cur["stacks"] = len(self.stacks)
            cur["samples"] = len(self.samples["t"])
            cur["async"] = len(self.async_samples["t"])
            cur["gc"] = len(self.gc)
            cur["markers"] = len(self.markers)
            cur["events"] = len(self.events)
            cur["task_events"] = len(self.task_events)
            cur["tracks"] = {k: len(v) for k, v in self.tracks.items()}
            self._dirty_tasks.clear()
            self._dirty_threads.clear()
            self._new_snapshots.clear()
            self._new_object_counts = False
            self._meta_dirty = False
            return d

    def full(self) -> dict:
        with self.lock:
            d = self._collect(self._new_cursor(), everything=True)
            d["format"] = "pyprof"
            d["version"] = 1
            return d
