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

The extension doesn't manage environments. It uses the interpreter the **Python
extension** selected for each file or folder (venv, uv, Poetry, conda, pyenv; multi-root
aware), plus your `.env`/`envFile`/`env`/`cwd`/`args`. If the interpreter is older than 3.15,
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
VS Code extension host (TypeScript, src/extension)        Webview dashboard (Vue 3, src/webview)
 ├ extension.ts        composition root                                   ▲ postMessage
 ├ EnvironmentResolver ← ms-python API (interpreter per resource, .env)   │ (init + deltas)
 ├ LaunchAdapter       ← debugpy configs, python-profiler debug type      │
 ├ SessionManager / Session / CollectorClient ─────────────────────────────┘
 ├ SessionActions · Commands (every pyprof.* command)
 ├ Dashboards · EditorHeat (decorations, CodeLens) · views/ · StatusBar
 │
 │ JSON-lines RPC over stdio            contract: src/shared/protocol.ts
 ▼
python/_vscode_pyprof/
 ├ collector/          runs in the collector process (python -I, *target's* interpreter, stdlib only)
 │ ├ cli.py            entry point and composition root
 │ ├ service.py        the RPC API (Collector); owns sampler, agent link and store
 │ ├ rpc.py · options.py   JSON-lines RPC over stdio · session options
 │ ├ sampler.py        fixed-rate sampling loop (stacks, async stacks, task graph, GC, children) + RSS/CPU readers
 │ ├ tachyon.py        the only module that touches _remote_debugging
 │ ├ store.py          interned frames + stack prefix tree + columnar samples → deltas / .pyprof; its records
 │ ├ frames.py         file → category (user / library / stdlib / internal), (file, line) → function name
 │ └ agent_link.py     starts the agent in a running program (sys.remote_exec) and accepts its connection
 │                       ▲ localhost TCP + token
 ├ target/             runs *inside the profiled program*; imports nothing from collector/
 │ ├ launcher.py       Run with Profiler: runs your program in *your* environment (runpy), starts the agent
 │ └ agent.py          tracemalloc, loop-lag probe, asyncio debug, object counts → agent_link
 ├ wire.py             typed JSON access, shared by collector/ and target/
 └ processes.py        standalone script (any Python): lists Python processes
```

- **One data model.** The collector's store and the TypeScript `ProfileModel`
  (`src/shared/model.ts`) share one schema: frames, stack prefix tree, samples
  (`t, tid, stack, status`), tracks, tasks, snapshots and events. Live deltas and
  `.pyprof` files (gzip JSON) have the same shape.
- **One wire contract.** Every message that crosses a process boundary (webview ⇄
  extension ⇄ collector) is declared in
  `src/shared/protocol.ts`; the Python side validates incoming JSON once, at the
  boundary, through `wire.WireReader`.
- **Two sides, kept apart.** `collector/` observes the program from outside;
  `target/` is everything that runs inside it, so it imports only `wire.py` and the
  package root (`tests/unit/target/test_isolation.py` fails if that changes).
- **Private API, isolated.** `_remote_debugging` is CPython-internal, so only
  `tachyon.py` touches it, with fallbacks for changed signatures. Its types are
  declared in `python/stubs/`.
- **The dashboard is a Vue app.** `src/webview` is Vue 3 (`<script setup>`), Pinia,
  Vue Router and Tailwind, built by Vite into `dist/webview.js` + `dist/webview.css`:
  `services/` (the `HostClient` interface, its VS Code implementation and an in-memory
  mock), `stores/` (session, view filters, notifications, tooltip), `router/` (one route
  per tab, `/cpu/focus/:fn` for callers & callees), `views/`, `components/ui` (the
  design system), `components/charts` (canvas charts), `domain/insights.ts`. The
  `ProfileModel` stays raw in a shallow ref: live deltas mutate it in place and trigger
  one redraw at most every 500 ms. Commands are request/response (`commandResult`), so
  every button awaits its outcome and a failure is shown as a toast.
- **Start mode always uses a real terminal.** VS Code runs the launcher with your
  interpreter, so you get a TTY, stdin and colors. The agent's hello tells the collector
  which PID to sample, which also handles Windows venv launcher stubs.

## Development

Requires Node.js `^20.19.0` or `>=22.12.0` (Vite) and, for the collector, Python 3.15.

If Node comes from **nvm**: nvm is loaded from `~/.bashrc` only in interactive shells,
and VS Code tasks normally run a non-interactive `bash -c`, so they would get the system
Node. This project's tasks (`npm: build`, `npm: watch`, the F5 pre-launch build) therefore
run in `bash -ic` on Linux (`.vscode/tasks.json`). If a build still stops with "Node.js …
is too old", run it from a terminal, or make the VS Code server itself load nvm (on WSL:
put the two nvm lines from `~/.bashrc` into `~/.vscode-server/server-env-setup`).

```bash
npm install
npm run check              # vue-tsc + eslint + tests + build (the TypeScript gate)
npm run test:webview       # just the dashboard specs (Vitest + jsdom)

cd python
pdm install -G dev         # Python 3.15 venv with ruff, mypy, vulture
pdm run check              # ruff lint + format check, mypy --strict, vulture, unit tests (the Python gate)
pdm run test:integration   # collector end-to-end: launch, attach+inject, memory, asyncio
```

| Tests | What they cover |
|---|---|
| `test/*.test.ts` | profile model and exporters against recorded profiles (`test/fixtures`), launch-config parsing, formatting, and an activation smoke test that loads the extension against a stub of the VS Code API |
| `test/webview/*.spec.ts` | the dashboard: every spec mounts the whole app (real router and stores) over `MockHostClient` through `mountApp(path, …)`; `smoke.spec.ts` opens every route with every fixture, saved and live, and any Vue warning or console error fails a test; feature specs drive tabs, commands, filters and live updates; unit specs cover the host client, persisted state and insights |
| `test/session.integration.test.ts` | the TypeScript session layer against a real collector and target: attach, samples, stop, auto-save, remove, reopen. Skipped unless `PYPROF_TEST_PYTHON` points to a Python 3.15 interpreter (`PYPROF_TEST_PYTHON=python/.venv/bin/python npm test`) |
| `python/tests/unit/` | mirrors the package (`collector/`, `target/`): one test module per source module, plus `target/test_isolation.py`, which fails if code that runs inside the profiled program starts importing collector code; no target process needed |
| `python/tests/integration/` | drives a real collector over stdio exactly like the extension, profiling the programs in `test-apps/` |

Press **F5** ("Run Extension") to open an Extension Development Host on `test-apps/`
(`cpu_bound.py`, `leaky.py`, `async_storm.py`).

Settings are under `pyprof.*`: sampling rate, blocking sampling, tracemalloc on start
and frames, asyncio debug and slow-callback threshold, heat map metric, CodeLens,
child-process handling and auto-save. `src/extension/settings.ts`
is the only module that reads them.

### Coding standards

The Python code follows the team's Python and unittest style guides: behaviour lives
in classes with constructor-injected collaborators, interfaces are ABCs, imports are
absolute and at the top of the file, there is no `Any`, and the gate is `pdm run check`.
The TypeScript and Vue code follows the Vue & TypeScript guide: no `any`, no non-null
assertions, one module for the wire contract, routes named through one enum, one
store per domain, an API-client interface with a real and an in-memory implementation,
awaited writes with visible failures, Tailwind for layout and CSS custom properties for
every theme colour, whole-app specs through `mountApp`, `data-testid`s stripped from
production builds, and `vue-tsc --build` + ESLint (`eslint-plugin-vue`, typed rules) +
tests + build as the gate.

This project has a few **documented exceptions**, all caused by code that runs outside
the collector's own Python 3.15 process:

| Exception | Where | Why |
|---|---|---|
| Imports inside functions | `target/launcher.py` (`ctypes`, `zipfile`) | This code runs inside the *profiled program*: importing modules the program does not use itself would slow it down and show up in its profile. The launcher must stay valid on Python 3.10, so it cannot use `lazy` imports; `target/agent.py` and `collector/store.py` use PEP 810 `lazy` imports at the top of the file instead (`tests/unit/target/test_isolation.py` checks the agent loads none of them on import). |
| Imports after a version check | `collector/cli.py`, `target/launcher.py` | They must start on older interpreters to print "Python 3.15+ is required" instead of a syntax error; everything that needs 3.15 is imported afterwards. |
| Python 3.10-compatible syntax | `__init__.py` (root, `collector/`, `target/`), `collector/cli.py`, `target/launcher.py`, `processes.py` | Same reason; `processes.py` also runs before we know which interpreter the target uses. Enforced through ruff's per-file target version. |
| No pydantic at boundaries | `wire.py` | The collector is injected into arbitrary environments and must stay stdlib-only; `WireReader` does the one-time validation instead. |
| Module-level entry points | `collector.cli.main`, `target.launcher.main`, `target.agent.start` | Called by name from the extension's `python -c` bootstraps and from `sys.remote_exec`; they only delegate to a class. |
| Integration test not type-checked | `python/tests/integration/test_e2e.py` | It predates the guide; it is linted and formatted but not yet under `mypy --strict`. |

The dashboard is a VS Code webview, not a single-page app over a REST API. These parts of
the Vue & TypeScript guide are adapted:

| Guide rule | Here | Why |
|---|---|---|
| Navigation state lives in the URL | The router uses memory history; the current route is saved through the webview state (`HostClient.saveState`) and restored when the panel reopens | A webview has no address bar and no shareable URL; the webview state is what survives hiding, moving and reloading the panel. |
| Filters in the URL (`?tab=`) | Sample mode, grouping, threads, hidden libraries and time range live in the `view` store; only the CPU view kind is a route query | The filters are shared by every tab and reported to the extension (editor heat map, Hotspots view), so they are session view state rather than navigation. |
| `ensureX` / `refreshX` / `fetchX` loads, shared polling helper | Not used | The extension pushes data (`init`, then `delta`s); the dashboard never requests or polls. |
| Explicit save, optimistic concurrency | Not applicable | There are no editors. Each command is one explicit click, awaited, with a failure shown as a toast. |
| Permission gating in router guard, navigation and component | Session capabilities (`live`, `agent`, `tracemalloc`, …) gate actions inside the components only | There are no users or permissions; every tab is useful for every session, so no route needs a guard. |
| Vitest for tests | Extension-host tests (`test/*.test.ts`) stay on `node:test` | They test Node code against a stub of the VS Code API; Vitest covers the Vue app. |
