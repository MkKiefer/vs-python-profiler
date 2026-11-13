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
VS Code extension host (TypeScript, src/extension)        Webview dashboard (TS, canvas, src/webview)
 ├ extension.ts        composition root                                   ▲ postMessage
 ├ EnvironmentResolver ← ms-python API (interpreter per resource, .env)   │ (init + deltas)
 ├ LaunchAdapter       ← debugpy configs, python-profiler debug type      │
 ├ SessionManager / Session / CollectorClient ─────────────────────────────┘
 ├ SessionActions · Commands (every pyprof.* command)
 ├ TerminalHub (PYPROF_HUB, `pyprof` on PATH)
 ├ Dashboards · EditorHeat (decorations, CodeLens) · views/ · StatusBar
 │
 │ JSON-lines RPC over stdio            contract: src/shared/protocol.ts
 ▼
Collector  (python -I, *target's* interpreter, stdlib only)  python/_vscode_pyprof/
 ├ cli.py            entry point and composition root
 ├ collector.py      the RPC API; owns sampler, agent connection and store
 ├ sampler.py        fixed-rate sampling loop: stacks, async stacks, task graph, GC, RSS/CPU, children
 ├ tachyon.py        the only module that touches _remote_debugging
 ├ store.py          interned frames + stack prefix tree + columnar samples → deltas / .pyprof
 ├ frame_classifier.py · funcresolver.py · procstats.py · options.py · records.py · wire.py · rpc.py
 ├ agent_server.py ◄── localhost TCP + token ──► agent.py (inside the target)
 │   agent_injector.py (sys.remote_exec)         tracemalloc, loop-lag probe, asyncio debug, object counts
 ├ launcher.py       runs your program in *your* environment (runpy), starts the agent
 └ processes.py      standalone script: lists Python processes
```

- **One data model.** The collector's store and the TypeScript `ProfileModel`
  (`src/shared/model.ts`) share one schema: frames, stack prefix tree, samples
  (`t, tid, stack, status`), tracks, tasks, snapshots and events. Live deltas and
  `.pyprof` files (gzip JSON) have the same shape.
- **One wire contract.** Every message that crosses a process boundary (webview ⇄
  extension ⇄ collector, terminal launcher → extension) is declared in
  `src/shared/protocol.ts`; the Python side validates incoming JSON once, at the
  boundary, through `wire.WireReader`.
- **Private API, isolated.** `_remote_debugging` is CPython-internal, so only
  `tachyon.py` touches it, with fallbacks for changed signatures. Its types are
  declared in `python/stubs/`.
- **Start mode always uses a real terminal.** VS Code runs the launcher with your
  interpreter, so you get a TTY, stdin and colors. The agent's hello tells the collector
  which PID to sample, which also handles Windows venv launcher stubs.

## Development

```bash
npm install
npm run check              # typecheck + eslint + tests + build (the TypeScript gate)

cd python
pdm install -G dev         # Python 3.15 venv with ruff, mypy, vulture
pdm run check              # ruff lint + format check, mypy --strict, vulture, unit tests (the Python gate)
pdm run test:integration   # collector end-to-end: launch, attach+inject, memory, asyncio, terminal hub
```

| Tests | What they cover |
|---|---|
| `test/*.test.ts` | profile model and exporters against recorded profiles (`test/fixtures`), launch-config parsing, formatting, and an activation smoke test that loads the extension against a stub of the VS Code API |
| `test/session.integration.test.ts` | the TypeScript session layer against a real collector and target: attach, samples, stop, auto-save, remove, reopen. Skipped unless `PYPROF_TEST_PYTHON` points to a Python 3.15 interpreter (`PYPROF_TEST_PYTHON=python/.venv/bin/python npm test`) |
| `python/tests/unit/` | one test module per source module of the collector; no target process needed |
| `python/tests/integration/` | drives a real collector over stdio exactly like the extension, profiling the programs in `test-apps/` |

Press **F5** ("Run Extension") to open an Extension Development Host on `test-apps/`
(`cpu_bound.py`, `leaky.py`, `async_storm.py`).

Settings are under `pyprof.*`: sampling rate, blocking sampling, tracemalloc on start
and frames, asyncio debug and slow-callback threshold, heat map metric, CodeLens,
child-process handling, terminal integration and auto-save. `src/extension/settings.ts`
is the only module that reads them.

### Coding standards

The Python code follows the team's Python and unittest style guides: behaviour lives
in classes with constructor-injected collaborators, interfaces are ABCs, imports are
absolute and at the top of the file, there is no `Any`, and the gate is `pdm run check`.
The TypeScript code follows the TypeScript rules of the Vue & TypeScript guide (no
`any`, no non-null assertions, one module for the wire contract, no fire-and-forget
promises), enforced by ESLint.

This project has a few **documented exceptions**, all caused by code that runs outside
the collector's own Python 3.15 process:

| Exception | Where | Why |
|---|---|---|
| Lazy imports inside functions | `agent.py` (`asyncio`, `tracemalloc`, `logging`, `warnings`, `gc`), `launcher.py` (`ctypes`, `zipfile`) | This code runs inside the *profiled program*. Importing modules the program does not use itself would slow it down, show up in its profile, and break the agent's "does this program use asyncio?" check. |
| Imports after a version check | `cli.py`, `launcher.py` | They must start on older interpreters to print "Python 3.15+ is required" instead of a syntax error; everything that needs 3.15 is imported afterwards. |
| Python 3.10-compatible syntax | `__init__.py`, `cli.py`, `launcher.py`, `processes.py` | Same reason; `processes.py` also runs before we know which interpreter the target uses. Enforced through ruff's per-file target version. |
| No pydantic at boundaries | `wire.py` | The collector is injected into arbitrary environments and must stay stdlib-only; `WireReader` does the one-time validation instead. |
| Module-level entry points | `cli.main`, `launcher.cli_main`, `agent.start` | Called by name from the shell shims and from `sys.remote_exec`; they only delegate to a class. |
| Integration test not type-checked | `python/tests/integration/test_e2e.py` | It predates the guide; it is linted and formatted but not yet under `mypy --strict`. |
