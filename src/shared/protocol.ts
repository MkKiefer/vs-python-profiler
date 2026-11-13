import type { Delta } from './model';

/** Messages extension → webview */
export type ToWebview =
  | { type: 'init'; sessionId: string; label: string; live: boolean; state: SessionState; data: Delta; capabilities: Capabilities }
  | { type: 'delta'; data: Delta }
  | { type: 'state'; state: SessionState; capabilities: Capabilities }
  | { type: 'diffResult'; a: number; b: number }
  | { type: 'error'; message: string }
  | { type: 'info'; message: string };

/** Messages webview → extension */
export type FromWebview =
  | { type: 'ready' }
  | { type: 'openSource'; file: string; line: number }
  | { type: 'command'; command: WebviewCommand; args?: Record<string, unknown> };

export type WebviewCommand =
  | 'stop'
  | 'snapshot'
  | 'tracemalloc'
  | 'asyncioDebug'
  | 'objectCounts'
  | 'mark'
  | 'save'
  | 'exportSpeedscope'
  | 'exportCollapsed'
  | 'compareWith';

export type SessionState = 'starting' | 'waiting' | 'running' | 'stopped' | 'exited' | 'error' | 'file';

export interface Capabilities {
  agent: boolean;
  tracemalloc: boolean;
  asyncioDebug: boolean;
  live: boolean;
}

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
