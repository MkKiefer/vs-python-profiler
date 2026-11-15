# Architecture

How the Python Profiler extension is put together. For building and testing it, see
[CONTRIBUTING.md](CONTRIBUTING.md); for using it, the [README](README.md).

```
VS Code extension host (TypeScript, src/extension)        Webview dashboard (Vue 3, src/webview)
 ├ extension.ts        composition root                                   ▲ postMessage
 ├ EnvironmentResolver ← ms-python API (interpreter per resource, .env)   │ (init + deltas)
 ├ LaunchAdapter       ← debugpy configs, python-profiler debug type      │
 ├ SessionManager / Session / CollectorClient ─────────────────────────────┘
 ├ SessionActions · Commands (every vspyprof.* command)
 ├ Dashboards · EditorHeat (decorations, CodeLens) · views/ · StatusBar
 │
 │ JSON-lines RPC over stdio            contract: src/shared/protocol.ts
 ▼
python/_vspyprof/
 ├ collector/          runs in the collector process (python -I, *target's* interpreter, stdlib only)
 │ ├ cli.py            entry point and composition root
 │ ├ session.py        the RPC API (CollectorSession); ties sampler, agent link and store together
 │ ├ protocol.py       names of the RPC methods, notifications and session states (mirror of protocol.ts)
 │ ├ requests.py · rpc_results.py · notifications.py   what the extension sends, what the collector answers
 │ │                   and pushes, as dataclasses
 │ ├ rpc.py · options.py   JSON-lines RPC over stdio · session options
 │ ├ memory_snapshot_builder.py · profile_writer.py   agent snapshot reply → stored snapshot · .vspyprof files
 │ ├ sampling/         sampler.py (fixed-rate loop: stacks, async stacks, task graph, children), gc_recorder.py,
 │ │                   sampler_factory.py, process_stats.py + one RSS/CPU reader per OS,
 │ │                   tachyon.py - the only module that touches _remote_debugging
 │ ├ store/            store.py (thread-safe facade → deltas / .vspyprof) over stack_table.py (interned frames +
 │ │                   stack prefix tree), sample_runs.py (run-length encoded samples) over typed_column.py +
 │ │                   column_snapshot.py, task_table.py, memory_snapshot.py, append_log.py,
 │ │                   session_clock.py, track.py, sampling_stats.py, profile_meta.py, timeline_event.py, async_stack.py
 │ ├ frames/           frame_classifier.py (file → user / library / stdlib / internal),
 │ │                   func_resolver.py ((file, line) → function name)
 │ └ agent/            server.py (accepts the agent, token check), connection.py (requests, messages),
 │                     injector.py (sys.remote_exec)
 │                       ▲ localhost TCP + token
 ├ target/             runs *inside the profiled program*; imports nothing from collector/
 │ ├ launcher.py       Run with Profiler: runs your program in *your* environment (runpy), starts the agent
 │ ├ agent.py          the agent thread: connects back, serves commands, reports metrics
 │ └ memory_probe.py · loop_monitor.py · asyncio_debug.py   tracemalloc + object counts · loop lag · debug events
 ├ agent_protocol/     collector ⇄ agent contract, used by both ends: commands.py, hello.py, metrics.py,
 │                     replies.py, options.py, messages.py (which classes go which way), names.py, address.py
 ├ wire.py             dataclass ⇄ JSON line by "type" (WireEncoder / WireDecoder), Request / Response, LineBuffer
 └ processes.py        standalone script (any Python): lists Python processes
```

- **One data model.** The collector's store and the TypeScript `ProfileModel`
  (`src/shared/model.ts`) share one schema: frames, stack prefix tree, samples
  (`t, tid, stack, status`), tracks, tasks, snapshots and events. Live deltas and
  `.vspyprof` files (gzip JSON) have the same shape.
- **Samples stay compact.** They are the one table that grows with time × threads. A
  thread that waits on a lock, socket or queue repeats one sample every tick, so samples
  are stored as **runs** (profile format 2): one 14-byte row `tick, count, thread, stack,
  status` per stretch of equal samples, plus the time of each tick (`SampleRuns` in the
  collector, `src/shared/sampleTable.ts` in the extension and dashboard). Queries stay
  exact: a time range maps to a range of ticks and a run counts with its overlap. A server
  with one busy thread and eight idle workers measured 1.5 bytes per sample (21.6 with one
  row per sample); one row per sample (format 1) is still read. Runs are typed columns
  everywhere (`array.array`, typed arrays); a dashboard's `init` sends them as typed
  arrays, which `postMessage` transfers as binary and the dashboard adopts without
  copying, and both the collector and the extension stream them into `.vspyprof` files.
- **One wire contract.** Every message that crosses a process boundary (webview ⇄
  extension ⇄ collector) is declared in
  `src/shared/protocol.ts`. Both Python streams (extension ⇄ collector over stdio,
  collector ⇄ agent over TCP) carry one JSON object per line whose `"type"` is the
  name of a plain dataclass: `wire.WireEncoder` writes any dataclass that way
  (nested ones included), and a `wire.WireDecoder` built from the classes an end
  receives (`collector/messages.py`, `agent_protocol/messages.py`) reads them back
  with `cls(**fields)`, so a missing key takes the field's default. Requests and
  answers are the shared `Request(id, body)` / `Response(id, result, error)`; the
  receiving end runs a request with a `match` on the body's class.
- **Two sides, kept apart.** `collector/` observes the program from outside;
  `target/` is everything that runs inside it, so it imports only `wire.py`,
  `agent_protocol/` and the package root (`tests/unit/target/test_isolation.py` fails if that changes).
- **Private API, isolated.** `_remote_debugging` is CPython-internal, so only
  `sampling/tachyon.py` touches it, with fallbacks for changed signatures. Its types are
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

## Coding standards

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
| Imports inside functions | `target/launcher.py` (`ctypes`) | This code runs inside the *profiled program*: importing modules the program does not use itself would slow it down and show up in its profile. The launcher must stay valid on Python 3.10, so it cannot use `lazy` imports; the agent modules (`target/agent.py`, `memory_probe.py`, `loop_monitor.py`, `asyncio_debug.py`) use PEP 810 `lazy` imports at the top of the file instead (`tests/unit/target/test_isolation.py` checks the agent loads none of them on import). `collector/store/` and `collector/agent/listener.py` use `lazy` imports for names that only appear in annotations (the private `_remote_debugging` types; a circular reference). |
| Imports after a version check | `collector/cli.py`, `target/launcher.py` | They must start on older interpreters to print "Python 3.15+ is required" instead of a syntax error; everything that needs 3.15 is imported afterwards. |
| Python 3.10-compatible syntax | `__init__.py` (root, `collector/`, `target/`), `collector/cli.py`, `target/launcher.py`, `processes.py` | Same reason; `processes.py` also runs before we know which interpreter the target uses. Enforced through ruff's per-file target version. |
| No pydantic at boundaries | `wire.py` | The collector is injected into arbitrary environments and must stay stdlib-only. Messages are plain dataclasses read by their `"type"` with `cls(**fields)`; values are not checked against the field types, because both ends are built from the same classes (`protocol.ts` mirrors them for the extension). |
| Module-level entry points | `collector.cli.main`, `target.launcher.main`, `target.agent.start` | Called by name from the extension's `python -c` bootstraps and from `sys.remote_exec`; they only delegate to a class. |
| Plain class instead of a dataclass | `target/loop_monitor._LoopProbe` | `@dataclass` evaluates field annotations at import; its `asyncio` annotation would load `asyncio` into a program that does not use it (`test_isolation.py` fails if it does). |
| Dataclasses without `slots=True` | `agent_protocol/` | The package is imported inside the profiled program (on its main thread when attaching). Slotted dataclasses rebuild every class and load `inspect`; plain frozen dataclasses keep the one-time import pause short. |
| JSON objects as `dict[str, object]` | `wire.py`, the store classes' `to_profile()`, `Store.delta()` / `full()` (the `.vspyprof` format), the `Delta` notification and `ProfileWriter` | JSON exists only at the wire edge and in the profile format. Between classes, data travels as a message dataclass (requests / results, notifications, agent commands / hello / metrics / replies, options) or another named type; names with a fixed set of values are enums. |
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
