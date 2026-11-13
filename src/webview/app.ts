/** Dashboard application state shared by all tabs. */
import { ProfileModel, type Filter, type Mode, type Source } from '../shared/model';
import type { Capabilities, FromWebview, SessionState, WebviewCommand } from '../shared/protocol';
import { fmtMs, isSyntheticFile } from '../shared/format';

declare function acquireVsCodeApi(): { postMessage(m: FromWebview): void; getState(): unknown; setState(s: PersistedState): void };
export const vscode = acquireVsCodeApi();

const TABS = ['overview', 'cpu', 'memory', 'async', 'timeline'] as const;
const CPU_VIEWS = ['flame', 'tree', 'inverted', 'top'] as const;
const MODES = ['wall', 'cpu', 'gil'] as const;
const SOURCES = ['threads', 'async'] as const;
export type TabId = (typeof TABS)[number];
export type CpuView = (typeof CPU_VIEWS)[number];

/** View settings that survive hiding and reloading the panel. */
interface PersistedState {
  tab: TabId;
  mode: Mode;
  cpuView: CpuView;
  hideLibs: boolean;
  byLine: boolean;
  source: Source;
}

function oneOf<T extends string>(allowed: readonly T[], value: unknown, fallback: T): T {
  return allowed.find((candidate) => candidate === value) ?? fallback;
}

export interface Tab {
  readonly el: HTMLElement;
  /** full = structural change (filters); otherwise just new live data */
  update(full: boolean): void;
  reveal?(fn: number): void;
}

export class App {
  model = new ProfileModel();
  label = '';
  state: SessionState = 'starting';
  caps: Capabilities = { agent: false, tracemalloc: false, asyncioDebug: false, live: false };

  // view state (persisted per panel)
  tab: TabId = 'overview';
  range: [number, number] | null = null;
  mode: Mode = 'wall';
  source: Source = 'threads';
  threads = new Set<number>();
  hideLibs = false;
  byLine = false;
  cpuView: CpuView = 'flame';
  focusFn: number | undefined;
  search = '';
  memSnap: number | undefined;
  memBase: number | undefined;

  private listeners = new Set<(full: boolean) => void>();

  constructor() {
    const saved = vscode.getState();
    if (typeof saved === 'object' && saved !== null) {
      const state = saved as Partial<Record<keyof PersistedState, unknown>>;
      this.tab = oneOf(TABS, state.tab, this.tab);
      this.mode = oneOf(MODES, state.mode, this.mode);
      this.cpuView = oneOf(CPU_VIEWS, state.cpuView, this.cpuView);
      this.source = oneOf(SOURCES, state.source, this.source);
      this.hideLibs = state.hideLibs === true;
      this.byLine = state.byLine === true;
    }
  }

  onChange(cb: (full: boolean) => void): void {
    this.listeners.add(cb);
  }

  /** Notify views; full=true for filter/structure changes. */
  changed(full = true): void {
    if (full) {
      vscode.setState({ tab: this.tab, mode: this.mode, cpuView: this.cpuView, hideLibs: this.hideLibs, byLine: this.byLine, source: this.source });
      vscode.postMessage({
        type: 'viewState',
        state: {
          mode: this.mode,
          source: this.source,
          t0: this.range?.[0],
          t1: this.range?.[1],
          threads: [...this.threads],
        },
      });
    }
    for (const l of this.listeners) l(full);
  }

  filter(): Filter {
    return {
      t0: this.range?.[0],
      t1: this.range?.[1],
      mode: this.mode,
      source: this.source,
      threads: this.threads.size ? this.threads : null,
    };
  }

  domain(): [number, number] {
    return [0, Math.max(1000, this.model.duration)];
  }

  setRange(t0: number, t1: number): void {
    this.range = [Math.max(0, t0), t1];
    this.changed(true);
  }

  clearRange(): void {
    this.range = null;
    this.changed(true);
  }

  /** sample count → approximate time, per thread */
  samplesToMs(n: number): number {
    return n * this.model.sampleIntervalMs;
  }

  fmtSamples = (n: number): string => fmtMs(this.samplesToMs(n));

  command(command: WebviewCommand, args?: Record<string, unknown>): void {
    vscode.postMessage({ type: 'command', command, args });
  }

  open(file: string, line: number): void {
    if (isSyntheticFile(file)) return;
    vscode.postMessage({ type: 'openSource', file, line });
  }

  focus(fn: number): void {
    this.focusFn = fn;
    this.tab = 'cpu';
    this.changed(true);
  }
}
