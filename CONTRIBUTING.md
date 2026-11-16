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
version:

1. Describe the changes under `## [Unreleased]` in `CHANGELOG.md` (the Marketplace shows that
   file as the extension's changelog, and the section becomes the release notes).
2. `npm run release -- patch` (or `minor`, `major`, `X.Y.Z`): bumps `package.json`,
   `package-lock.json` and `python/pyproject.toml`, and moves the `[Unreleased]` entries under
   the new version.
3. Commit on a branch, open a pull request, merge it once CI is green.
4. **Actions → Release → Run workflow** on `main` (or `gh workflow run release.yml`). Pushing the
   tag yourself works too: `git tag -a v0.2.0 -m "v0.2.0" && git push origin v0.2.0`.

`.github/workflows/release.yml` checks that the version is `X.Y.Z`, matches in both projects, has
a `CHANGELOG.md` section and is on `main` (and, from "Run workflow", that its tag does not exist
yet), runs the full CI, and creates the release and its `vX.Y.Z` tag with the `.vsix`,
`SHA256SUMS.txt`, the changelog section plus GitHub's list of merged pull requests as notes, and a
signed build provenance attestation. Verify a download with
`gh attestation verify python-profiler-0.2.0.vsix --repo <owner>/<repo>`, install it with
`code --install-extension python-profiler-0.2.0.vsix`.

After the GitHub release, the `marketplace` and `open-vsx` jobs publish the same `.vsix` to the
[Visual Studio Marketplace](https://marketplace.visualstudio.com/) and [Open VSX](https://open-vsx.org/)
(used by VSCodium, Cursor, Windsurf and Gitpod). Each is skipped with a notice until its token
exists. One-time setup:

1. Marketplace: create the publisher `vspyprof` (the `publisher` in `package.json`) at
   <https://marketplace.visualstudio.com/manage>, then an Azure DevOps personal access token with
   the **Marketplace → Manage** scope, and store it as the `VSCE_PAT` secret of the `release`
   environment.
2. Open VSX: sign in at <https://open-vsx.org/> with GitHub, sign the publisher agreement, create the
   namespace once (`npx ovsx create-namespace vspyprof -p <token>`), and store the access token as
   `OVSX_PAT` in the `release` environment.

The README's screenshots are linked from the repository (`raw/HEAD/media/screenshots/…`), so they
show on the Marketplace only while the repository is public. To refresh them, record a profile of a
realistic program and screenshot each dashboard tab at 1400 × 880 in a dark theme.

Hardening: the workflows grant the token only what each job needs (only the `publish`
job can write, and it runs no repository code), pin actions to commit SHAs (Dependabot
updates them, after a 7-day cooldown), install npm packages with `--ignore-scripts`, and build
releases without the npm cache. `.github/workflows/security.yml` lints the workflows with
[zizmor](https://docs.zizmor.sh/) and runs dependency review on pull requests. The repository
settings that go with this are listed below.

## Repository settings

The workflows assume these GitHub settings; set them once.

- **Settings → Actions → General**
  - Actions permissions: allow actions by GitHub plus `pdm-project/setup-pdm` and
    `zizmorcore/zizmor-action`, and tick "Require actions to be pinned to a full-length commit SHA".
  - Fork pull request workflows: require approval for all outside contributors.
  - Workflow permissions: "Read repository contents and packages permissions"; leave "Allow GitHub
    Actions to create and approve pull requests" off.
- **Settings → Rules → Rulesets**
  - Branch ruleset on `main`: require a pull request, require the status checks `extension`,
    `collector (…)` (all three), `package`, `workflows` and `dependencies`, block force pushes and
    deletion.
  - Tag ruleset on `v*`: block updates and deletion, so a released tag can never move. If it also
    restricts creation, add GitHub Actions to its bypass list, or "Run workflow" cannot create the tag.
- **Settings → Environments → `release`**: you as required reviewer; deployment branches and tags
  limited to the `main` branch and `v*` tags (both: "Run workflow" deploys from `main`, a pushed tag
  from `v*`); `VSCE_PAT` and `OVSX_PAT` stored here only, never as repository secrets. Each release
  asks for approval twice: once for the GitHub release, once for the two stores.
- **Settings → General → Releases**: enable immutable releases.
- **Settings → Advanced Security**: private vulnerability reporting (used by
  [SECURITY.md](SECURITY.md)), Dependabot alerts and security updates, secret scanning with push
  protection, and CodeQL default setup (JavaScript/TypeScript, Python, GitHub Actions).
- **Your account**: two-factor authentication with a passkey or security key. Give the store tokens
  an expiry date and note when they run out (an Azure DevOps token lasts at most a year).

Never add a `pull_request_target` or `workflow_run` workflow that checks out or runs pull-request
code: those run with the repository's secrets and write token.
