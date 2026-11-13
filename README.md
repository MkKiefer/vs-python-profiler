# Python Profiler for VS Code (Tachyon)

CPU, memory and asyncio profiling for **Python 3.15+**, built into VS Code. It uses
CPython's built-in sampling profiler **Tachyon** (`profiling.sampling`, PEP 799), safe
remote code execution (`sys.remote_exec`, PEP 768) and asyncio introspection. Nothing
is installed into your environment and your code needs no changes.

- **Start with the profiler**, or **attach** to a program that is already running, on Windows, Linux and macOS
- **Live dashboard**: overview with automatic insights, flame graph, call tree, bottom-up view, top functions, callers/callees
- **Wall / CPU / GIL views** from one recording (each sample keeps its thread state)
- **Memory**: RSS and traced memory over time, tracemalloc snapshots, a **snapshot diff for leak hunting**, allocation flame graph, live object counts, GC pauses
- **asyncio**: task timeline (Gantt), async-aware flame graph, **event-loop lag**, asyncio debug mode (slow callbacks, never-awaited coroutines)
- **Editor integration**: per-line heat in the gutter, inline timings and CodeLens on hot functions. These follow the dashboard's time range, mode and thread filter
- **Timeline**: threads (on-CPU and GIL waits), GC, CPU, memory and loop lag on one time axis. Drag to zoom every view
- Saved `.pyprof` files open in the dashboard. Export to speedscope or collapsed stacks

## Starting a profile

| You want to… | Do this |
|---|---|
| Profile the current file | ▶ dropdown in the editor title → **Profile Python File** |
| Reuse an existing debug config (FastAPI, Django, module…) | **Python Profiler: Profile Launch Configuration…** Your `debugpy` configurations run unchanged, with the profiler instead of the debugger |
| Write a dedicated config | `launch.json` → *Add Configuration* → **Python Profiler: …** snippets (`"type": "python-profiler"`) |
| Profile a test | right-click in a test file → **Profile Test at Cursor** |
| Profile a running process | sidebar **Python Processes**, or **Attach Profiler to Process…** |
| Use the terminal (uv, poetry, make…) | `pyprof run app.py` · `pyprof run -m pkg` · `pyprof run uvicorn app:main` · `uv run pyprof run -- python app.py` |

The extension doesn't manage environments. It uses the interpreter the **Python
extension** selected for each file or folder (venv, uv, Poetry, conda, pyenv; multi-root
aware), plus your `.env`/`envFile`/`env`/`cwd`/`args`. In terminals, `pyprof` uses
whichever environment is active in that terminal. If the interpreter is older than 3.15,
you get a one-click fix: select another interpreter or create a 3.15 venv (uses `uv` when
available).

### Attach permissions

| OS | Notes |
|---|---|
| Linux | Same user. With `kernel.yama.ptrace_scope=1` (the default on Ubuntu) you can only attach to processes **started through the profiler**, which call `PR_SET_PTRACER` for us. Otherwise run `sudo sysctl kernel.yama.ptrace_scope=0`. Containers need `--cap-add=SYS_PTRACE`. |
| macOS | Reading another process's memory requires root. Start programs with the profiler, or run VS Code with elevated rights to attach. |
| Windows | Same user works. Elevated or service processes need an elevated VS Code. venv launcher stubs are resolved to the real interpreter automatically. |

Attaching injects a small agent through `sys.remote_exec` (for memory and asyncio
debug). If the target disabled remote debugging (`PYTHON_DISABLE_REMOTE_DEBUG`), CPU
sampling, task graphs and GC stats still work.

## Architecture

```
VS Code extension host (TypeScript)                       Webview dashboard (TS, canvas)
 ├ EnvironmentResolver ← ms-python API (interpreter per resource, .env)   ▲ postMessage
 ├ LaunchAdapter       ← debugpy configs, python-profiler debug type      │ (init + deltas)
 ├ SessionManager ─────────────────────────────────────────────────────────┘
 ├ TerminalHub (PYPROF_HUB, `pyprof` on PATH)
 ├ EditorHeat (decorations, CodeLens) · Views · StatusBar
 │
 │ JSON-lines RPC over stdio
 ▼
Collector  (python -I, *target's* interpreter, stdlib only)  python/_vscode_pyprof/
 ├ sampler.py   Tachyon adapter: _remote_debugging.RemoteUnwinder, async stacks, task graph, GC, RSS/CPU, children
 ├ store.py     interned frames + stack prefix tree + columnar samples → deltas / .pyprof
 ├ agent_server.py ◄── localhost TCP + token ──► agent.py (inside the target)
 │                                               tracemalloc, loop-lag probe, asyncio debug, object counts
 └ launcher.py  runs your program in *your* environment (runpy), starts the agent
```

- **One data model.** The collector's store and the TypeScript `ProfileModel`
  (`src/shared/model.ts`) share one schema: frames, stack prefix tree, samples
  (`t, tid, stack, status`), tracks, tasks, snapshots and events. Live deltas and
  `.pyprof` files (gzip JSON) have the same shape.
- **Private API, isolated.** `_remote_debugging` is CPython-internal, so only
  `sampler.py` touches it, with fallbacks for changed signatures.
- **Start mode always uses a real terminal.** VS Code runs the launcher with your
  interpreter, so you get a TTY, stdin and colors. The agent's hello tells the collector
  which PID to sample, which also handles Windows venv launcher stubs.

## Development

```bash
npm install
npm run build          # bundles dist/extension.js and dist/webview.js
npm run typecheck
npm test               # model/exporter tests against real recorded profiles (test/fixtures)
python3.15 -W ignore python/tests/test_e2e.py   # collector end-to-end: launch, attach+inject, memory, asyncio, terminal hub
```

Press **F5** ("Run Extension") to open an Extension Development Host on `test-apps/`
(`cpu_bound.py`, `leaky.py`, `async_storm.py`).

Settings are under `pyprof.*`: sampling rate, blocking sampling, tracemalloc on start
and frames, asyncio debug and slow-callback threshold, heat map metric, CodeLens,
child-process handling, terminal integration and auto-save.
