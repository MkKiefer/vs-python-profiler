/**
 * The dashboard's only way to talk to the extension host.
 *
 * `VsCodeHostClient` is the real implementation (webview `postMessage`);
 * `MockHostClient` is an in-memory extension host for tests. A new message is
 * added to this interface and to both implementations together.
 */
import type { ToWebview, ViewState, WebviewCommand, WebviewCommandArgs } from '../../shared/protocol';
import type { Mode, Source } from '../../shared/model';

/** Pushed by the extension: profile data, session state and reveal requests. */
export type HostEvent = Exclude<ToWebview, { type: 'commandResult' }>;

/** What survives hiding, moving and reloading the panel (the webview has no address bar). */
export interface PersistedState {
  /** full path of the current route */
  route: string;
  mode: Mode;
  source: Source;
  hideLibs: boolean;
  byLine: boolean;
}

export interface HostClient {
  /** Tell the extension the dashboard is listening; it answers with `init`. */
  ready(): void;
  /** Subscribe to pushed events; returns the unsubscribe function. */
  onEvent(listener: (event: HostEvent) => void): () => void;
  /** Run a command in the extension; rejects with the extension's error message. */
  runCommand<C extends WebviewCommand>(command: C, args: WebviewCommandArgs[C]): Promise<void>;
  /** Show a source location in the editor. */
  openSource(file: string, line: number): void;
  /** Report what the dashboard shows (drives editor heat and the Hotspots view). */
  sendViewState(state: ViewState): void;
  loadState(): PersistedState | undefined;
  saveState(state: PersistedState): void;
}

const MODES: readonly Mode[] = ['wall', 'cpu', 'gil'];
const SOURCES: readonly Source[] = ['threads', 'async'];

/** Validate state saved by an earlier version of the dashboard; unknown fields fall back to defaults. */
export function parsePersistedState(raw: unknown): PersistedState | undefined {
  if (typeof raw !== 'object' || raw === null) return undefined;
  const state = raw as Partial<Record<keyof PersistedState, unknown>>;
  return {
    route: typeof state.route === 'string' ? state.route : '',
    mode: MODES.find((mode) => mode === state.mode) ?? 'wall',
    source: SOURCES.find((source) => source === state.source) ?? 'threads',
    hideLibs: state.hideLibs === true,
    byLine: state.byLine === true,
  };
}
