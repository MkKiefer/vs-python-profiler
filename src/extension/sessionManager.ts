/**
 * Owns all sessions and the two ways a live one starts. Every live path ends
 * in the same place – a collector process running with the *target's* interpreter:
 *
 *   launch   : collector first → terminal runs our launcher with VSPYPROF_AGENT
 *              → launcher's agent says hello (pid) → collector starts sampling
 *   attach   : collector → attach(pid) → optional sys.remote_exec agent injection
 */
import * as vscode from 'vscode';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { CollectorClient } from './collectorClient';
import type { PythonInfo } from './environment';
import { ExtPaths, LAUNCHER_BOOT } from './paths';
import { PROFILE_EXTENSION, profileFileStem, readProfile, writeProfile } from './profileFile';
import { Session } from './session';
import { settings } from './settings';
import { errorMessage } from '../shared/errors';
import type { AttachOptions, CollectorOptions, InitializeResult } from '../shared/protocol';

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

export interface SavedProfile {
  file: string;
  mtime: number;
  size: number;
}

const STARTUP_TIMEOUT_MS = 20_000;
const LIVE_CONTEXT_KEY = 'vspyprof.hasLiveSession';

export class SessionManager implements vscode.Disposable {
  private readonly all: Session[] = [];
  private activeSession: Session | undefined;
  /** sessions whose auto-save and collector shutdown are under way */
  private readonly finalizing = new Map<Session, Promise<void>>();
  private readonly startupTimers = new Map<Session, NodeJS.Timeout>();

  private readonly changed = new vscode.EventEmitter<void>();
  /** a session was added, removed or changed state */
  readonly onDidChange = this.changed.event;
  private readonly activeChanged = new vscode.EventEmitter<Session | undefined>();
  readonly onDidChangeActive = this.activeChanged.event;
  private readonly started = new vscode.EventEmitter<Session>();
  /** a live session is set up and waiting for (or already receiving) samples */
  readonly onDidStart = this.started.event;

  constructor(
    private readonly paths: ExtPaths,
    private readonly log: vscode.LogOutputChannel,
    private readonly storageDir: string,
  ) {
    fs.mkdirSync(this.storageDir, { recursive: true });
    this.terminalClosed = vscode.window.onDidCloseTerminal((terminal) => this.onTerminalClosed(terminal));
    this.refreshContext();
  }

  private readonly terminalClosed: vscode.Disposable;

  /** newest first */
  get sessions(): readonly Session[] {
    return this.all;
  }

  get active(): Session | undefined {
    return this.activeSession;
  }

  find(id: string): Session | undefined {
    return this.all.find((s) => s.id === id);
  }

  setActive(session: Session | undefined): void {
    if (this.activeSession === session) return;
    this.activeSession = session;
    this.activeChanged.fire(session);
  }

  // ------------------------------------------------------------- starting
  /** "Run with Profiler": real terminal (TTY, stdin, colors) running our launcher. */
  async launch(spec: LaunchSpec): Promise<Session> {
    const session = this.add(new Session(spec.label, 'launch', spec.python));
    const options: CollectorOptions = { ...spec.options, stripLauncher: true };
    await this.guardStartup(session, async () => {
      const { info } = await this.startCollector(session, spec.python.executable, options);
      session.setState('waiting');
      session.terminal = vscode.window.createTerminal({
        name: `Profile: ${spec.label}`,
        shellPath: spec.python.executable,
        shellArgs: [
          '-c', LAUNCHER_BOOT, this.paths.python,
          ...(spec.kind === 'module' ? ['-m', spec.target] : [spec.target]),
          ...spec.args,
        ],
        cwd: spec.cwd,
        env: {
          ...spec.env,
          VSPYPROF_AGENT: info.agentAddress,
          VSPYPROF_OPTIONS: info.agentOptions,
          PYTHONUNBUFFERED: spec.env?.PYTHONUNBUFFERED ?? '1',
        },
        iconPath: new vscode.ThemeIcon('flame'),
        isTransient: true,
      });
      session.terminal.show(true);
      this.watchStartup(session);
    });
    return session;
  }

  async attach(pid: number, python: PythonInfo, label: string, overrides: AttachOptions = {}): Promise<Session> {
    const session = this.add(new Session(label, 'attach', python));
    session.pid = pid;
    const { inject = true, ...options } = overrides;
    await this.guardStartup(session, async () => {
      const { client } = await this.startCollector(session, python.executable, settings.collectorOptions(undefined, options));
      const result = await client.request('Attach', { pid, inject }, 30_000);
      session.pid = result.pid;
      if (result.injectError) {
        void vscode.window.showWarningMessage(
          `Profiling PID ${pid} (CPU + asyncio tasks). The in-process agent could not be injected, so memory tracing ` +
            `and asyncio debug are unavailable: ${result.injectError}`,
        );
      }
      if (session.state === 'starting') session.setState('running');
    });
    return session;
  }

  private async startCollector(
    session: Session,
    python: string,
    options: CollectorOptions,
  ): Promise<{ client: CollectorClient; info: InitializeResult }> {
    const client = new CollectorClient(python, this.paths.python, this.log);
    session.attachClient(client);
    client.start();
    const info = await client.request('Initialize', { options: { type: 'CollectorOptions', ...options }, label: session.label }, 30_000);
    session.updateCapabilities({ tracemalloc: !!options.tracemalloc, asyncioDebug: !!options.asyncioDebug });
    return { client, info };
  }

  /** Run a start-up sequence; on failure the session ends in the error state. */
  private async guardStartup<T>(session: Session, start: () => Promise<T>): Promise<T> {
    try {
      const result = await start();
      this.started.fire(session);
      return result;
    } catch (e) {
      session.setState('error', errorMessage(e));
      await session.client?.shutdown();
      throw e;
    }
  }

  /** The launched program must connect back in time; otherwise explain instead of waiting forever. */
  private watchStartup(session: Session): void {
    const timer = setTimeout(() => {
      this.startupTimers.delete(session);
      if (session.state !== 'waiting') return;
      session.setState('error', 'The program did not connect to the profiler. Check its terminal for errors.');
      void vscode.window.showErrorMessage(
        `Python Profiler: "${session.label}" did not start profiling within ${STARTUP_TIMEOUT_MS / 1000}s. Check the terminal output.`,
      );
      void session.client?.shutdown();
    }, STARTUP_TIMEOUT_MS);
    this.startupTimers.set(session, timer);
  }

  /**
   * A launched program whose terminal closes before its agent connected never will (a missing script, an
   * import error, an old interpreter): fail at once instead of after the start-up timeout.
   */
  private onTerminalClosed(terminal: vscode.Terminal): void {
    for (const session of this.all) {
      if (session.terminal !== terminal || session.state !== 'waiting') continue;
      const code = terminal.exitStatus?.code;
      const exited = code === undefined ? 'The program exited' : `The program exited with code ${code}`;
      session.setState('error', `${exited} before it connected to the profiler.`);
      void vscode.window.showErrorMessage(`Python Profiler: "${session.label}": ${exited.toLowerCase()} before profiling started.`);
      void session.client?.shutdown();
    }
  }

  // ------------------------------------------------------------- stopping
  async stop(session: Session, terminate = false): Promise<void> {
    try {
      await session.client?.request('Stop', { reason: 'user' }, 10_000);
    } catch (e) {
      this.log.warn(`stop failed: ${errorMessage(e)}`);
    }
    if (terminate) this.terminateTarget(session);
    if (session.live) session.setState('stopped');
  }

  private terminateTarget(session: Session): void {
    if (session.terminal) {
      session.terminal.dispose();
    } else if (session.pid) {
      try {
        process.kill(session.pid);
      } catch (e) {
        void vscode.window.showWarningMessage(`Could not terminate PID ${session.pid}: ${errorMessage(e)}`);
      }
    }
  }

  /** Remove a session from the list (stopping it first). Its saved profile, if any, stays on disk. */
  async remove(session: Session): Promise<void> {
    if (session.live) await this.stop(session);
    await this.finalize(session);
    this.forget(session);
  }

  /**
   * Auto-save and shut down the collector once a session has ended. A call while one is under way returns
   * the same promise, so a caller that disposes the session afterwards (`remove`) waits for the save.
   */
  private finalize(session: Session): Promise<void> {
    const running = this.finalizing.get(session);
    if (running) return running;
    const client = session.client;
    if (!client) return Promise.resolve();
    const done = this.saveAndShutdown(session, client).finally(() => this.finalizing.delete(session));
    this.finalizing.set(session, done);
    return done;
  }

  private async saveAndShutdown(session: Session, client: CollectorClient): Promise<void> {
    try {
      if (settings.autoSave() && session.model.stats.samples > 0 && !session.filePath) {
        const stamp = new Date(session.startedAt).toISOString().replace(/[:.]/g, '-');
        const file = path.join(this.storageDir, `${stamp}_${profileFileStem(session.label)}.${PROFILE_EXTENSION}`);
        await client.request('Save', { path: file }, 60_000);
        session.filePath = file;
      }
    } catch (e) {
      this.log.warn(`auto-save failed: ${errorMessage(e)}`);
    } finally {
      await client.shutdown();
      this.changed.fire();
    }
  }

  // ---------------------------------------------------------------- files
  async saveAs(session: Session, target: string): Promise<void> {
    const client = session.client;
    if (client) await client.request('Save', { path: target }, 60_000);
    else await writeProfile(target, session.model.toDelta());
  }

  /** Auto-saved profiles that are not open as a session, newest first. */
  savedProfiles(): SavedProfile[] {
    const open = new Set(this.all.map((s) => s.filePath));
    try {
      return fs
        .readdirSync(this.storageDir)
        .filter((name) => name.endsWith(`.${PROFILE_EXTENSION}`))
        .map((name) => path.join(this.storageDir, name))
        .filter((file) => !open.has(file))
        .map((file) => {
          const stat = fs.statSync(file);
          return { file, mtime: stat.mtimeMs, size: stat.size };
        })
        .sort((a, b) => b.mtime - a.mtime);
    } catch (e) {
      this.log.warn(`cannot list saved profiles: ${errorMessage(e)}`);
      return [];
    }
  }

  async openFile(file: string): Promise<Session> {
    const existing = this.all.find((s) => s.filePath === file && s.kind === 'file');
    if (existing) {
      this.setActive(existing);
      return existing;
    }
    const data = await readProfile(file);
    const label = data.meta?.label ?? path.basename(file, `.${PROFILE_EXTENSION}`);
    return this.add(Session.fromFile(label, file, data));
  }

  /** Delete a saved profile from disk and close any session showing it. */
  deleteSaved(file: string): void {
    fs.rmSync(file, { force: true });
    for (const session of this.all.filter((s) => s.filePath === file)) {
      if (session.kind === 'file') this.forget(session);
      else session.filePath = undefined;
    }
    this.changed.fire();
  }

  // ------------------------------------------------------------ internals
  private add(session: Session): Session {
    this.all.unshift(session);
    session.onDidChange(() => {
      if (session.state !== 'waiting') this.clearStartupTimer(session);
      this.refreshContext();
      this.changed.fire();
      if (session.state === 'exited' || session.state === 'stopped') void this.finalize(session);
    });
    this.setActive(session);
    this.refreshContext();
    this.changed.fire();
    return session;
  }

  private forget(session: Session): void {
    const index = this.all.indexOf(session);
    if (index < 0) return;
    this.all.splice(index, 1);
    this.clearStartupTimer(session);
    if (this.activeSession === session) this.setActive(this.all[0]);
    session.dispose();
    this.refreshContext();
    this.changed.fire();
  }

  private clearStartupTimer(session: Session): void {
    const timer = this.startupTimers.get(session);
    if (timer) clearTimeout(timer);
    this.startupTimers.delete(session);
  }

  private refreshContext(): void {
    void vscode.commands.executeCommand('setContext', LIVE_CONTEXT_KEY, this.all.some((s) => s.live));
  }

  dispose(): void {
    this.terminalClosed.dispose();
    for (const timer of this.startupTimers.values()) clearTimeout(timer);
    for (const session of this.all) {
      void session.client?.shutdown();
      session.dispose();
    }
    this.changed.dispose();
    this.activeChanged.dispose();
    this.started.dispose();
  }
}
