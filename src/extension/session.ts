/** One profiled process (live) or one opened `.pyprof` file. */
import * as vscode from 'vscode';
import type { CollectorClient } from './collectorClient';
import type { PythonInfo } from './environment';
import { ProfileModel, type Delta } from '../shared/model';
import type { Capabilities, CollectorNotification, SessionState } from '../shared/protocol';

export type SessionKind = 'launch' | 'attach' | 'terminal' | 'file';

const LIVE_STATES: ReadonlySet<SessionState> = new Set<SessionState>(['starting', 'waiting', 'running']);

let sequence = 0;

export class Session implements vscode.Disposable {
  readonly id = `s${++sequence}-${Date.now().toString(36)}`;
  readonly model = new ProfileModel();
  readonly startedAt = Date.now();
  pid: number | undefined;
  terminal: vscode.Terminal | undefined;
  /** where the profile is stored, once saved or when opened from a file */
  filePath: string | undefined;
  /** child processes already offered for profiling */
  readonly knownChildPids = new Set<number>();

  private currentState: SessionState;
  private currentCapabilities: Capabilities = { agent: false, tracemalloc: false, asyncioDebug: false, live: false };
  private lastError: string | undefined;
  private collector: CollectorClient | undefined;

  private readonly changed = new vscode.EventEmitter<Session>();
  readonly onDidChange = this.changed.event;
  private readonly delta = new vscode.EventEmitter<Delta>();
  readonly onDidDelta = this.delta.event;
  private readonly children = new vscode.EventEmitter<number[]>();
  /** fires with the pids of newly started Python child processes */
  readonly onDidDiscoverChildren = this.children.event;
  private readonly disposables: vscode.Disposable[] = [];

  constructor(
    public label: string,
    readonly kind: SessionKind,
    readonly python?: PythonInfo,
  ) {
    this.currentState = kind === 'file' ? 'file' : 'starting';
    this.currentCapabilities.live = this.live;
  }

  /** A profile loaded from disk. */
  static fromFile(label: string, filePath: string, data: Delta): Session {
    const session = new Session(label, 'file');
    session.filePath = filePath;
    session.model.applyDelta(data);
    return session;
  }

  get state(): SessionState {
    return this.currentState;
  }

  get capabilities(): Capabilities {
    return this.currentCapabilities;
  }

  get error(): string | undefined {
    return this.lastError;
  }

  get live(): boolean {
    return LIVE_STATES.has(this.currentState);
  }

  /** The collector, while its process is running. */
  get client(): CollectorClient | undefined {
    return this.collector?.alive ? this.collector : undefined;
  }

  setState(state: SessionState, error?: string): void {
    this.currentState = state;
    if (error) this.lastError = error;
    this.currentCapabilities = { ...this.currentCapabilities, live: this.live };
    this.changed.fire(this);
  }

  updateCapabilities(change: Partial<Omit<Capabilities, 'live'>>): void {
    this.currentCapabilities = { ...this.currentCapabilities, ...change };
    this.changed.fire(this);
  }

  attachClient(client: CollectorClient): void {
    this.collector = client;
    this.disposables.push(
      client.onNotification((notification) => this.onNotification(notification)),
      client.onExit(() => {
        if (this.live) this.setState('error', this.lastError ?? 'collector exited unexpectedly');
      }),
    );
  }

  private onNotification(notification: CollectorNotification): void {
    switch (notification.method) {
      case 'delta':
        this.model.applyDelta(notification.params);
        this.delta.fire(notification.params);
        break;
      case 'state':
        if (notification.params.pid) this.pid = notification.params.pid;
        // a finished session keeps its final state (the collector also reports
        // "stopped" when it is merely shut down after the target exited)
        if (this.live) this.setState(notification.params.state);
        break;
      case 'agent':
        this.updateCapabilities({ agent: notification.params.connected });
        break;
      case 'children':
        this.children.fire(notification.params.pids);
        break;
      case 'error':
        this.lastError = notification.params.message;
        void vscode.window.showErrorMessage(`Python Profiler: ${notification.params.message}`);
        break;
    }
  }

  dispose(): void {
    for (const d of this.disposables) d.dispose();
    this.collector?.dispose();
    this.changed.dispose();
    this.delta.dispose();
    this.children.dispose();
  }
}
