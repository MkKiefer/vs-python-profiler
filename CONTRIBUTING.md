# Contributing

How to build, test and release the Python Profiler extension. How the code is organised,
and the coding standards it follows, are in [ARCHITECTURE.md](ARCHITECTURE.md).

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
| `test/session.integration.test.ts` | the TypeScript session layer against a real collector and target: attach, samples, stop, auto-save, remove, reopen. Skipped unless `VSPYPROF_TEST_PYTHON` points to a Python 3.15 interpreter (`VSPYPROF_TEST_PYTHON=python/.venv/bin/python npm test`) |
| `python/tests/unit/` | mirrors the package (`collector/…`, `target/`): one test module per source module, plus `target/test_isolation.py`, which fails if code that runs inside the profiled program starts importing collector code; no target process needed |
| `python/tests/integration/` | drives a real collector over stdio exactly like the extension, profiling the programs in `test-apps/` |

Press **F5** ("Run Extension") to open an Extension Development Host on `test-apps/`
(`cpu_bound.py`, `leaky.py`, `async_storm.py`).

Settings are under `vspyprof.*`: sampling rate, blocking sampling, tracemalloc on start
and frames, asyncio debug and slow-callback threshold, heat map metric, CodeLens,
child-process handling and auto-save. `src/extension/settings.ts`
is the only module that reads them.

## Releasing

Every CI run uploads the packaged extension as the `vsix` workflow artifact. To publish a
version, bump `version` in both `package.json` and `python/pyproject.toml`, merge to `main`,
then tag that commit:

```bash
git tag -a v0.2.0 -m "v0.2.0" && git push origin v0.2.0
```

`.github/workflows/release.yml` checks that the tag is `vX.Y.Z`, matches both versions and is
on `main`, runs the full CI, and creates a GitHub release with the `.vsix`, `SHA256SUMS.txt`,
generated notes and a signed build provenance attestation. Verify a download with
`gh attestation verify python-profiler-0.2.0.vsix --repo <owner>/<repo>`, install it with
`code --install-extension python-profiler-0.2.0.vsix`.

Hardening: the workflows grant the token only what each job needs (only the final `publish`
job can write, and it runs no repository code), pin actions to commit SHAs (Dependabot
updates them), install npm packages with `--ignore-scripts`, and build releases without the
npm cache. Recommended repository settings: a tag ruleset restricting who may create `v*`
tags, required reviewers on the `release` environment, and immutable releases.
