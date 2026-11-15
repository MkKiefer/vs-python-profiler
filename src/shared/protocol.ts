/**
 * Wire contracts between the three parts of the extension:
 *
 *   webview  ⇄  extension host  ⇄  collector (Python, one JSON object per line over stdio)
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
//
// Every message is one JSON object per line whose `type` is the name of the
// Python dataclass it is read into (`python/_vscode_pyprof/wire.py`); nested
// dataclasses carry their `type` too. The collector writes `None` as `null`.

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
  type: 'InitializeResult';
  protocol: number;
  python: string;
  executable: string;
  platform: string;
  pid: number;
  /** `host:port:token` the in-process agent connects back to */
  agentAddress: string;
  /** the agent's start options as one JSON line; passed to a launched program as `PYPROF_OPTIONS` */
  agentOptions: string;
  packageDir: string;
  features: { type: 'Features'; gcStats: boolean; remoteExec: boolean; asyncAware: boolean };
}

export interface AttachResult {
  type: 'AttachResult';
  pid: number;
  injected: boolean;
  injectError: string | null;
}

/**
 * The requests of the collector (`python/_vscode_pyprof/collector/requests.py`): the key is
 * the request's `type`, `params` its fields and `result` what the `Response` carries.
 */
export interface CollectorRequests {
  Initialize: { params: { options: CollectorOptions & { type: 'CollectorOptions' }; label?: string }; result: InitializeResult };
  Attach: { params: { pid: number; inject: boolean }; result: AttachResult };
  Stop: { params: { reason?: string }; result: null };
  GetStatus: { params: Record<string, never>; result: { type: 'StatusResult'; state: string; pid: number | null; agent: boolean } };
  SetTracemalloc: { params: { enabled: boolean; frames?: number }; result: { type: 'TracingStatus'; tracing: boolean } };
  TakeSnapshot: {
    params: { label?: string; limit?: number };
    result: { type: 'SnapshotResult'; snapshotId: number; totalSize: number; entries: number };
  };
  CountObjects: { params: { limit?: number }; result: { type: 'ObjectCounts'; t: number } };
  SetAsyncioDebug: { params: { enabled: boolean; slowMs?: number }; result: { type: 'AsyncioDebugStatus'; enabled: boolean } };
  Mark: { params: { name: string }; result: null };
  Save: { params: { path: string }; result: { type: 'SaveResult'; path: string; sizeBytes: number } };
  Shutdown: { params: Record<string, never>; result: null };
}

export type CollectorRequestType = keyof CollectorRequests;

/** What the extension writes: one request, answered by the `CollectorResponse` with the same `id`. */
export interface CollectorRequest<T extends CollectorRequestType = CollectorRequestType> {
  type: 'Request';
  id: number;
  body: { type: T } & CollectorRequests[T]['params'];
}

export interface CollectorResponse {
  type: 'Response';
  id: number;
  result: unknown;
  error: string | null;
}

/** Notifications the collector pushes without being asked (`python/_vscode_pyprof/collector/notifications.py`). */
export type CollectorNotification =
  | { type: 'Delta'; data: Delta }
  | { type: 'StateChanged'; state: 'running' | 'exited' | 'stopped'; pid: number | null; reason: string | null }
  | { type: 'AgentConnected'; pid: number; argv: string[]; cwd: string | null }
  | { type: 'AgentDisconnected' }
  | { type: 'ChildrenFound'; pids: number[] }
  | { type: 'ErrorOccurred'; message: string };

/** Everything the collector writes. */
export type CollectorMessage = CollectorResponse | CollectorNotification;
