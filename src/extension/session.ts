/**
 * Sessions: one per profiled process (live) or per opened .pyprof file.
 *
 * Every live path ends in the same place – a collector process running with
 * the *target's* interpreter:
 *
 *   launch   : collector first → terminal runs our launcher with PYPROF_AGENT
 *              → launcher's agent says hello (pid) → collector starts sampling
 *   terminal : `pyprof run …` → hub hello → collector → reply agent address → same as launch
 *   attach   : collector → attach(pid) → optional sys.remote_exec agent injection
 */
import * as vscode from 'vscode';
import * as fs from 'node:fs';
import * as path from 'node:path';
import * as zlib from 'node:zlib';
import { CollectorClient } from './collectorClient';
import { ExtPaths, LAUNCHER_BOOT } from './paths';
import { ProfileModel, type Delta } from '../shared/model';
import type { Capabilities, CollectorOptions, SessionState } from '../shared/protocol';
import type { PythonInfo } from './environment';

export type SessionKind = 'launch' | 'attach' | 'terminal' | 'file';

export interface LaunchSpec {
  python: PythonInfo;
  kind: 'path' | 'module';
  target: string;
  args: string[];
  cwd?: string;
  env?: Record<string, string>;
  label: string;
  options?: CollectorOptions;
}

let seq = 0;

export class Session implements vscode.Disposable {
  readonly id = `s${++seq}-${Date.now().toString(36)}`;
  readonly model = new ProfileModel();
  state: SessionState = 'starting';
  pid: number | undefined;
  client: CollectorClient | undefined;
  terminal: vscode.Terminal | undefined;
  filePath: string | undefined;
  loaded = true;
  error: string | undefined;
  readonly startedAt = Date.now();
  capabilities: Capabilities = { agent: false, tracemalloc: false, asyncioDebug: false, live: true };
  childPids = new Set<number>();

  private readonly changed = new vscode.EventEmitter<Session>();
  readonly onDidChange = this.changed.event;
  private readonly delta = new vscode.EventEmitter<Delta>();
  readonly onDidDelta = this.delta.event;
  private disposables: vscode.Disposable[] = [];

  constructor(
    public label: string,
    readonly kind: SessionKind,
    readonly python?: PythonInfo,
  ) {}

  get live(): boolean {
    return this.kind !== 'file' && (this.state === 'starting' || this.state === 'waiting' || this.state === 'running');
  }

  setState(state: SessionState, error?: string): void {
    this.state = state;
    if (error) this.error = error;
    this.capabilities = { ...this.capabilities, live: this.live };
    this.changed.fire(this);
  }

  attachClient(client: CollectorClient): void {
    this.client = client;
    this.disposables.push(
      client.onNotification(({ method, params }) => {
        switch (method) {
          case 'delta':
            this.model.applyDelta(params);
            this.delta.fire(params);
            break;
          case 'state':
            if (params.pid) this.pid = params.pid;
            if (params.state === 'running') this.setState('running');
            else if (params.state === 'exited') this.setState('exited');
            else if (params.state === 'stopped') this.setState('stopped');
            break;
          case 'agent':
            this.capabilities = { ...this.capabilities, agent: !!params.connected };
            if (params.connected && params.argv && this.kind !== 'attach') {
              this.label = this.label || params.argv.join(' ');
            }
            this.changed.fire(this);
            break;
          case 'error':
            this.error = params.message;
            vscode.window.showErrorMessage(`Python Profiler: ${params.message}`);
            break;
        }
      }),
      client.onExit(() => {
        if (this.live) this.setState('error', this.error ?? 'collector exited unexpectedly');
      }),
    );
  }

  /** Forward a collector notification to other listeners (children etc). */
  onCollector(method: string, cb: (params: any) => void): void {
    if (!this.client) return;
    this.disposables.push(this.client.onNotification((n) => n.method === method && cb(n.params)));
  }

  dispose(): void {
    this.disposables.forEach((d) => d.dispose());
    this.client?.dispose();
    this.changed.dispose();
    this.delta.dispose();
  }
}

export class SessionManager implements vscode.Disposable {
  readonly sessions: Session[] = [];
  private _active: Session | undefined;
  private readonly changed = new vscode.EventEmitter<void>();
  readonly onDidChange = this.changed.event;
  private readonly activeChanged = new vscode.EventEmitter<Session | undefined>();
  readonly onDidChangeActive = this.activeChanged.event;
  private readonly started = new vscode.EventEmitter<Session>();
  readonly onDidStart = this.started.event;

  constructor(
    private readonly paths: ExtPaths,
    private readonly log: vscode.LogOutputChannel,
    private readonly storageDir: string,
  ) {
    fs.mkdirSync(this.storageDir, { recursive: true });
  }

  get active(): Session | undefined {
    return this._active;
  }

  setActive(s: Session | undefined): void {
    if (this._active === s) return;
    this._active = s;
    vscode.commands.executeCommand('setContext', 'pyprof.hasLiveSession', this.sessions.some((x) => x.live));
    this.activeChanged.fire(s);
  }

  private add(s: Session): Session {
    this.sessions.unshift(s);
    s.onDidChange(() => {
      vscode.commands.executeCommand('setContext', 'pyprof.hasLiveSession', this.sessions.some((x) => x.live));
      this.changed.fire();
      if (!s.live && s.client && (s.state === 'exited' || s.state === 'stopped')) void this.finalize(s);
    });
    this.setActive(s);
    this.changed.fire();
    return s;
  }

  defaultOptions(resource?: vscode.Uri, overrides: CollectorOptions = {}): CollectorOptions {
    const c = vscode.workspace.getConfiguration('pyprof', resource);
    return {
      rateHz: c.get('samplingRate', 1000),
      native: c.get('nativeFrames', false),
      blocking: c.get('blockingSampling', false),
      tracemalloc: c.get('memory.tracemallocOnStart', false),
      tracemallocFrames: c.get('memory.tracebackFrames', 16),
      asyncioDebug: c.get('asyncio.debugOnStart', false),
      slowCallbackMs: c.get('asyncio.slowCallbackMs', 100),
      asyncAware: true,
      gc: true,
      ...Object.fromEntries(Object.entries(overrides).filter(([, v]) => v !== undefined)),
    };
  }

  private async startCollector(s: Session, python: string, options: CollectorOptions): Promise<any> {
    const client = new CollectorClient(python, this.paths.python, this.log);
    s.attachClient(client);
    client.start();
    const info = await client.request('initialize', { options, label: s.label }, 30_000);
    s.capabilities = {
      ...s.capabilities,
      tracemalloc: !!options.tracemalloc,
      asyncioDebug: !!options.asyncioDebug,
    };
    return info;
  }

  /** "Run with Profiler": real terminal (TTY, stdin, colors) running our launcher. */
  async launch(spec: LaunchSpec): Promise<Session> {
    const s = this.add(new Session(spec.label, 'launch', spec.python));
    try {
      const options = { ...spec.options, stripLauncher: true };
      const info = await this.startCollector(s, spec.python.executable, options);
      s.setState('waiting');
      const shellArgs = [
        '-c', LAUNCHER_BOOT, this.paths.python, 'run',
        ...(spec.kind === 'module' ? ['-m', spec.target] : [spec.target]),
        ...spec.args,
      ];
      s.terminal = vscode.window.createTerminal({
        name: `Profile: ${spec.label}`,
        shellPath: spec.python.executable,
        shellArgs,
        cwd: spec.cwd,
        env: {
          ...spec.env,
          PYPROF_AGENT: info.agentAddress,
          PYPROF_OPTIONS: JSON.stringify(options),
          PYTHONUNBUFFERED: spec.env?.PYTHONUNBUFFERED ?? '1',
        },
        iconPath: new vscode.ThemeIcon('flame'),
        isTransient: true,
      });
      s.terminal.show(true);
      this.watchStartup(s, 20_000);
      this.started.fire(s);
    } catch (e) {
      s.setState('error', String((e as Error).message ?? e));
      throw e;
    }
    return s;
  }

  /** `pyprof run …` typed in a VS Code terminal. Returns the agent address for the launcher. */
  async fromTerminal(hello: any): Promise<{ agent: string; options: CollectorOptions }> {
    const python: PythonInfo = {
      executable: hello.executable,
      version: hello.version,
      major: Number(String(hello.version).split('.')[0]),
      minor: Number(String(hello.version).split('.')[1]),
      freeThreaded: false,
      label: `Python ${hello.version}`,
    };
    const label = [path.basename(String(hello.target)), ...(hello.args ?? [])].join(' ');
    const s = this.add(new Session(label, 'terminal', python));
    const options = { ...this.defaultOptions(), stripLauncher: true };
    try {
      const info = await this.startCollector(s, hello.executable, options);
      s.setState('waiting');
      this.watchStartup(s, 20_000);
      this.started.fire(s);
      return { agent: info.agentAddress, options };
    } catch (e) {
      s.setState('error', String((e as Error).message ?? e));
      throw e;
    }
  }

  async attach(pid: number, python: PythonInfo, label: string, overrides: CollectorOptions & { inject?: boolean } = {}): Promise<Session> {
    const s = this.add(new Session(label, 'attach', python));
    s.pid = pid;
    try {
      const { inject = true, ...opts } = overrides;
      await this.startCollector(s, python.executable, this.defaultOptions(undefined, opts));
      const r = await s.client!.request('attach', { pid, inject }, 30_000);
      s.pid = r.pid;
      if (r.injectError) {
        vscode.window.showWarningMessage(
          `Profiling PID ${pid} (CPU + asyncio tasks). The in-process agent could not be injected, so memory tracing ` +
            `and asyncio debug are unavailable: ${r.injectError}`,
        );
      }
      if (s.state === 'starting') s.setState('running');
      this.started.fire(s);
    } catch (e) {
      s.setState('error', String((e as Error).message ?? e));
      throw e;
    }
    return s;
  }

  private watchStartup(s: Session, ms: number): void {
    setTimeout(() => {
      if (s.state === 'waiting') {
        s.setState('error', 'The program did not connect to the profiler. Check its terminal for errors.');
        vscode.window.showErrorMessage(
          `Python Profiler: "${s.label}" did not start profiling within ${ms / 1000}s. Check the terminal output.`,
        );
        void s.client?.shutdown();
      }
    }, ms);
  }

  async stop(s: Session, terminate = false): Promise<void> {
    if (s.client?.alive) {
      try {
        await s.client.request('stop', { reason: 'user' }, 10_000);
      } catch (e) {
        this.log.warn(`stop failed: ${e}`);
      }
    }
    if (terminate) {
      if (s.terminal) s.terminal.dispose();
      else if (s.pid) {
        try {
          process.kill(s.pid);
        } catch (e) {
          vscode.window.showWarningMessage(`Could not terminate PID ${s.pid}: ${e}`);
        }
      }
    }
    if (s.live) s.setState('stopped');
  }

  /** Save (auto) and shut down the collector once a session ends. */
  private finalizing = new Set<Session>();
  private async finalize(s: Session): Promise<void> {
    if (this.finalizing.has(s) || !s.client) return;
    this.finalizing.add(s);
    const client = s.client;
    try {
      if (vscode.workspace.getConfiguration('pyprof').get('autoSave', true) && s.model.stats.samples > 0) {
        const name = `${new Date(s.startedAt).toISOString().replace(/[:.]/g, '-')}_${sanitize(s.label)}.pyprof`;
        const file = path.join(this.storageDir, name);
        await client.request('save', { path: file }, 60_000);
        s.filePath = file;
      }
    } catch (e) {
      this.log.warn(`auto-save failed: ${e}`);
    } finally {
      await client.shutdown();
      this.changed.fire();
    }
  }

  async saveAs(s: Session, target: string): Promise<void> {
    if (s.client?.alive) {
      await s.client.request('save', { path: target }, 60_000);
    } else {
      await writeProfile(target, s.model.toDelta());
    }
  }

  // ------------------------------------------------------------ saved files
  savedFiles(): { file: string; mtime: number; size: number }[] {
    try {
      return fs
        .readdirSync(this.storageDir)
        .filter((f) => f.endsWith('.pyprof'))
        .map((f) => {
          const file = path.join(this.storageDir, f);
          const st = fs.statSync(file);
          return { file, mtime: st.mtimeMs, size: st.size };
        })
        .filter((f) => !this.sessions.some((s) => s.filePath === f.file))
        .sort((a, b) => b.mtime - a.mtime);
    } catch {
      return [];
    }
  }

  async openFile(file: string): Promise<Session> {
    const existing = this.sessions.find((s) => s.filePath === file && s.kind === 'file');
    if (existing) {
      this.setActive(existing);
      return existing;
    }
    const data = await readProfile(file);
    const label = String(data.meta?.label ?? path.basename(file, '.pyprof'));
    const s = new Session(label, 'file');
    s.filePath = file;
    s.model.applyDelta(data);
    s.capabilities = { agent: false, tracemalloc: false, asyncioDebug: false, live: false };
    s.state = 'file';
    this.add(s);
    return s;
  }

  deleteSaved(file: string): void {
    fs.rmSync(file, { force: true });
    const idx = this.sessions.findIndex((s) => s.filePath === file && s.kind === 'file');
    if (idx >= 0) {
      const [s] = this.sessions.splice(idx, 1);
      if (this._active === s) this.setActive(this.sessions[0]);
      s.dispose();
    }
    this.changed.fire();
  }

  dispose(): void {
    for (const s of this.sessions) {
      if (s.client?.alive) void s.client.shutdown();
      s.dispose();
    }
    this.changed.dispose();
    this.activeChanged.dispose();
  }
}

function sanitize(s: string): string {
  return s.replace(/[^\w.-]+/g, '_').slice(0, 60) || 'profile';
}

export async function readProfile(file: string): Promise<Delta> {
  const buf = await fs.promises.readFile(file);
  const text = buf[0] === 0x1f && buf[1] === 0x8b ? zlib.gunzipSync(buf).toString('utf8') : buf.toString('utf8');
  const data = JSON.parse(text) as Delta;
  if (data.format !== 'pyprof') throw new Error(`${file} is not a .pyprof file`);
  return data;
}

export async function writeProfile(file: string, data: Delta): Promise<void> {
  const gz = zlib.gzipSync(Buffer.from(JSON.stringify(data), 'utf8'));
  await fs.promises.writeFile(file, gz);
}
