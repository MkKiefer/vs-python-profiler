/**
 * Wire contracts between the three parts of the extension:
 *
 *   webview  ⇄  extension host  ⇄  collector (Python, JSON lines over stdio)
 *
 * Everything that crosses a process boundary is declared here so both ends
 * are checked against the same types.
 */
import type { Delta, Mode, Source } from './model';

// ───────────────────────────────────────────────────── extension ⇄ webview

export type SessionState = 'starting' | 'waiting' | 'running' | 'stopped' | 'exited' | 'error' | 'file';

export interface Capabilities {
  /** the in-process agent is connected (memory + asyncio debug features) */
  agent: boolean;
  tracemalloc: boolean;
  asyncioDebug: boolean;
  live: boolean;
}

/** What the dashboard currently shows; drives editor heat and the Hotspots view. */
export interface ViewState {
  mode: Mode;
  source: Source;
  t0?: number;
  t1?: number;
  threads?: number[];
}

/** Messages extension → webview */
export type ToWebview =
  | { type: 'init'; sessionId: string; label: string; state: SessionState; data: Delta; capabilities: Capabilities }
  | { type: 'delta'; data: Delta }
  | { type: 'state'; state: SessionState; capabilities: Capabilities }
  | { type: 'reveal'; fn: number }
  /** Answer to one `command` request; `error` is set when it failed. */
  | { type: 'commandResult'; id: number; error?: string };

/** Messages webview → extension */
export type FromWebview =
  | { type: 'ready' }
  | { type: 'openSource'; file: string; line: number }
  | { type: 'viewState'; state: ViewState }
  | CommandRequest;

/** Arguments of every dashboard command. */
export interface WebviewCommandArgs {
  stop: { terminate?: boolean };
  snapshot: { label?: string };
  /** omitted `enabled` toggles */
  tracemalloc: { enabled?: boolean };
  asyncioDebug: { enabled?: boolean };
  objectCounts: Record<string, never>;
  /** omitted `name` asks the user */
  mark: { name?: string };
  save: Record<string, never>;
  exportSpeedscope: Record<string, never>;
  exportCollapsed: Record<string, never>;
}

export type WebviewCommand = keyof WebviewCommandArgs;

/** A command the dashboard asks the extension to run; answered by `commandResult` with the same `id`. */
export type CommandRequest = {
  [C in WebviewCommand]: { type: 'command'; id: number; command: C; args: WebviewCommandArgs[C] };
}[WebviewCommand];

// ──────────────────────────────────────────────────── extension ⇄ collector

export interface CollectorOptions {
  rateHz?: number;
  native?: boolean;
  gc?: boolean;
  asyncAware?: boolean;
  tracemalloc?: boolean;
  tracemallocFrames?: number;
  asyncioDebug?: boolean;
  slowCallbackMs?: number;
  stripLauncher?: boolean;
  blocking?: boolean;
}

/** Options accepted when attaching; `inject` controls the in-process agent. */
export type AttachOptions = CollectorOptions & { inject?: boolean };

export interface InitializeResult {
  protocol: number;
  python: string;
  executable: string;
  platform: string;
  pid: number;
  /** `host:port:token` the in-process agent connects back to */
  agentAddress: string;
  packageDir: string;
  features: { gcStats: boolean; remoteExec: boolean; asyncAware: boolean };
}

export interface AttachResult {
  pid: number;
  injected: boolean;
  injectError: string | null;
}

/** Request/response pairs of the collector RPC (see `python/_vscode_pyprof/collector/session.py`; names mirrored in `collector/protocol.py`). */
export interface CollectorRequests {
  initialize: { params: { options: CollectorOptions; label?: string }; result: InitializeResult };
  attach: { params: { pid: number; inject: boolean }; result: AttachResult };
  stop: { params: { reason?: string }; result: { ok: true } };
  tracemalloc: { params: { enabled: boolean; frames?: number }; result: unknown };
  snapshot: { params: { label?: string; limit?: number }; result: { id: number; totalSize: number; entries: number } };
  objectCounts: { params: { limit?: number }; result: { t: number; counts: [string, number][] } };
  asyncioDebug: { params: { enabled: boolean; slowMs?: number }; result: unknown };
  mark: { params: { name: string }; result: { ok: true } };
  save: { params: { path: string }; result: { path: string; bytes: number } };
  shutdown: { params: Record<string, never>; result: { ok: true } };
}

/** Notifications the collector pushes without being asked. */
export type CollectorNotification =
  | { method: 'delta'; params: Delta }
  | { method: 'state'; params: { state: 'running' | 'exited' | 'stopped'; pid?: number; reason?: string } }
  | { method: 'agent'; params: { connected: boolean; pid?: number; argv?: string[]; cwd?: string } }
  | { method: 'children'; params: { pids: number[] } }
  | { method: 'error'; params: { message: string } };
