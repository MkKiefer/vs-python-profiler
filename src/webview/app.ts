/** Dashboard application state shared by all tabs. */
import { ProfileModel, type Filter, type Mode, type Source } from '../shared/model';
import type { Capabilities, SessionState, WebviewCommand } from '../shared/protocol';
import { fmtMs } from '../shared/format';

declare function acquireVsCodeApi(): { postMessage(m: unknown): void; getState(): any; setState(s: any): void };
export const vscode = acquireVsCodeApi();

export type TabId = 'overview' | 'cpu' | 'memory' | 'async' | 'timeline';
export type CpuView = 'flame' | 'tree' | 'inverted' | 'top';

export interface Tab {
  readonly el: HTMLElement;
  /** full = structural change (filters); otherwise just new live data */
  update(full: boolean): void;
  reveal?(fn: number): void;
}

export class App {
  model = new ProfileModel();
  label = '';
  live = false;
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
    if (saved) {
      Object.assign(this, {
        tab: saved.tab ?? this.tab,
        mode: saved.mode ?? this.mode,
        cpuView: saved.cpuView ?? this.cpuView,
        hideLibs: saved.hideLibs ?? false,
        byLine: saved.byLine ?? false,
        source: saved.source ?? 'threads',
      });
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

  get rateHz(): number {
    return Number((this.model.meta.options as any)?.rateHz ?? 1000);
  }

  /** sample count → approximate time, per thread */
  samplesToMs(n: number): number {
    return (n * 1000) / this.rateHz;
  }

  fmtSamples = (n: number): string => fmtMs(this.samplesToMs(n));

  command(command: WebviewCommand, args?: Record<string, unknown>): void {
    vscode.postMessage({ type: 'command', command, args });
  }

  open(file: string, line: number): void {
    if (!file || file.startsWith('<') || file === '~') return;
    vscode.postMessage({ type: 'openSource', file, line });
  }

  focus(fn: number): void {
    this.focusFn = fn;
    this.tab = 'cpu';
    this.changed(true);
  }
}
