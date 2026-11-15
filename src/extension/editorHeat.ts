/**
 * Editor integration: gutter/line heat, inline timings and CodeLens for the
 * active session. Follows the dashboard's current mode, time range and thread
 * filter so brushing a chart updates the code view.
 */
import * as vscode from 'vscode';
import * as path from 'node:path';
import type { Dashboards } from './dashboards';
import type { Session } from './session';
import type { SessionManager } from './sessionManager';
import { settings } from './settings';
import { fmtMs, fmtPct } from '../shared/format';
import type { Filter, LineHeat } from '../shared/model';

const LEVELS = 6;
/** lines below this share of the selection are not decorated at all */
const MIN_HEAT_SHARE = 0.002;
/** lines and functions below this share get no inline text / CodeLens */
const MIN_LABEL_SHARE = 0.005;
const LIVE_REFRESH_MS = 1000;

interface HeatData {
  heat: Map<string, Map<number, LineHeat>>;
  counts: Map<number, number>;
  total: number;
}

export class EditorHeat implements vscode.Disposable, vscode.CodeLensProvider {
  private decorations: vscode.TextEditorDecorationType[] = [];
  private inline: vscode.TextEditorDecorationType;
  private enabled: boolean;
  private timer: NodeJS.Timeout | undefined;
  private lastVersion = '';
  private viewEpoch = 0;
  private interval: NodeJS.Timeout;
  private cache: HeatData | undefined;
  private readonly lensChanged = new vscode.EventEmitter<void>();
  readonly onDidChangeCodeLenses = this.lensChanged.event;
  private disposables: vscode.Disposable[] = [];

  constructor(
    private readonly sessions: SessionManager,
    private readonly dashboards: Dashboards,
  ) {
    this.enabled = settings.heatMapEnabled();
    for (let i = 0; i < LEVELS; i++) {
      const alpha = 0.06 + (i / (LEVELS - 1)) * 0.3;
      this.decorations.push(
        vscode.window.createTextEditorDecorationType({
          isWholeLine: true,
          backgroundColor: `rgba(255, ${Math.round(140 - i * 22)}, 40, ${alpha.toFixed(2)})`,
          overviewRulerColor: `rgba(255, ${Math.round(140 - i * 22)}, 40, ${Math.min(1, alpha * 2.5).toFixed(2)})`,
          overviewRulerLane: vscode.OverviewRulerLane.Right,
          borderWidth: '0 0 0 3px',
          borderStyle: 'solid',
          borderColor: `rgba(255, ${Math.round(140 - i * 22)}, 40, ${Math.min(1, alpha * 3).toFixed(2)})`,
        }),
      );
    }
    this.inline = vscode.window.createTextEditorDecorationType({
      after: { margin: '0 0 0 2em', color: new vscode.ThemeColor('editorCodeLens.foreground'), fontStyle: 'italic' },
    });
    this.disposables.push(
      vscode.window.onDidChangeVisibleTextEditors(() => this.schedule(0)),
      sessions.onDidChangeActive(() => this.schedule(0)),
      dashboards.onDidChangeViewState(() => {
        this.viewEpoch++;
        this.schedule(50);
      }),
      vscode.workspace.onDidChangeConfiguration((e) => {
        if (settings.changedBy(e)) {
          this.enabled = settings.heatMapEnabled();
          this.lastVersion = '';
          this.schedule(0);
        }
      }),
      vscode.languages.registerCodeLensProvider({ language: 'python' }, this),
    );
    // live sessions: refresh at most once per second
    this.interval = setInterval(() => {
      const s = this.sessions.active;
      if (s && this.key(s) !== this.lastVersion) this.schedule(0);
    }, LIVE_REFRESH_MS);
  }

  async toggle(): Promise<void> {
    this.enabled = !this.enabled;
    this.lastVersion = '';
    this.schedule(0);
    await settings.setHeatMapEnabled(this.enabled);
  }

  private key(s: Session): string {
    return `${s.id}:${s.model.version}:${this.viewEpoch}`;
  }

  private schedule(ms: number): void {
    if (this.timer) clearTimeout(this.timer);
    this.timer = setTimeout(() => this.render(), ms);
  }

  private filterFor(s: Session): Filter {
    const v = this.dashboards.viewState(s);
    return {
      mode: v?.mode ?? 'wall',
      source: 'threads',
      t0: v?.t0,
      t1: v?.t1,
      threads: v?.threads?.length ? new Set(v.threads) : null,
    };
  }

  private compute(s: Session): HeatData {
    const key = this.key(s);
    if (this.cache && this.lastVersion === key) return this.cache;
    const counts = s.model.countStacks(this.filterFor(s));
    const total = s.model.totalWeight(counts);
    this.cache = { heat: s.model.lineHeat(counts), counts, total };
    this.lastVersion = key;
    this.lensChanged.fire();
    return this.cache;
  }

  private render(): void {
    const s = this.sessions.active;
    const editors = vscode.window.visibleTextEditors.filter((e) => e.document.languageId === 'python');
    if (!s || !this.enabled) {
      for (const e of editors) {
        this.decorations.forEach((d) => e.setDecorations(d, []));
        e.setDecorations(this.inline, []);
      }
      this.lensChanged.fire();
      return;
    }
    const { heat, total } = this.compute(s);
    const metric = settings.heatMapMetric();
    const msPerSample = s.model.sampleIntervalMs;
    for (const e of editors) {
      const lines = lookupFile(heat, e.document.uri.fsPath);
      const buckets: vscode.DecorationOptions[][] = Array.from({ length: LEVELS }, () => []);
      const inline: vscode.DecorationOptions[] = [];
      if (lines && total) {
        let max = 0;
        for (const r of lines.values()) max = Math.max(max, r[metric]);
        for (const [line, r] of lines) {
          if (line < 1 || line > e.document.lineCount) continue;
          const v = r[metric];
          const share = v / total;
          if (share < MIN_HEAT_SHARE) continue;
          const level = Math.min(LEVELS - 1, Math.floor(Math.sqrt(v / max) * LEVELS));
          const range = e.document.lineAt(line - 1).range;
          const hover = new vscode.MarkdownString(
            `**Python Profiler** — line ${line}\n\n` +
              `| | samples | share | ≈ time |\n|---|---:|---:|---:|\n` +
              `| total | ${r.total} | ${fmtPct(r.total, total)} | ${fmtMs(r.total * msPerSample)} |\n` +
              `| self | ${r.self} | ${fmtPct(r.self, total)} | ${fmtMs(r.self * msPerSample)} |`,
          );
          buckets[level].push({ range, hoverMessage: hover });
          if (share >= MIN_LABEL_SHARE) {
            inline.push({
              range,
              renderOptions: {
                after: {
                  contentText: `${fmtPct(r.total, total)} total${r.self ? ` · ${fmtPct(r.self, total)} self` : ''} · ${fmtMs(r.total * msPerSample)}`,
                },
              },
            });
          }
        }
      }
      this.decorations.forEach((d, i) => e.setDecorations(d, buckets[i]));
      e.setDecorations(this.inline, inline);
    }
  }

  // ------------------------------------------------------------ CodeLens
  provideCodeLenses(doc: vscode.TextDocument): vscode.CodeLens[] {
    const s = this.sessions.active;
    if (!s || !this.enabled || !settings.codeLensEnabled()) return [];
    const { counts, total } = this.compute(s);
    if (!total) return [];
    const file = normalize(doc.uri.fsPath);
    const msPerSample = s.model.sampleIntervalMs;
    const stats = s.model
      .topFunctions(counts)
      .filter((st) => normalize(s.model.fns[st.fn].file) === file && st.total / total >= MIN_LABEL_SHARE);
    const lenses: vscode.CodeLens[] = [];
    for (const st of stats) {
      const fn = s.model.fns[st.fn];
      const line = findDefLine(doc, fn.func, fn.minLine);
      if (line === undefined) continue;
      lenses.push(
        new vscode.CodeLens(doc.lineAt(line).range, {
          title: `$(flame) ${fmtPct(st.total, total)} total · ${fmtPct(st.self, total)} self · ≈${fmtMs(st.total * msPerSample)}`,
          tooltip: 'Show callers and callees in the profile dashboard',
          command: 'vspyprof.revealFunction',
          arguments: [s.id, st.fn],
        }),
      );
    }
    return lenses;
  }

  dispose(): void {
    clearInterval(this.interval);
    for (const d of this.decorations) d.dispose();
    this.inline.dispose();
    for (const d of this.disposables) d.dispose();
  }
}

function normalize(p: string): string {
  const n = path.normalize(p);
  return process.platform === 'win32' || process.platform === 'darwin' ? n.toLowerCase() : n;
}

function lookupFile<T>(heat: Map<string, T>, file: string): T | undefined {
  const direct = heat.get(file);
  if (direct) return direct;
  const want = normalize(file);
  for (const [k, v] of heat) if (normalize(k) === want) return v;
  return undefined;
}

/** CPython 3.15 reports qualnames (Class.method); find the `def` line at/above the first sampled line. */
function findDefLine(doc: vscode.TextDocument, qualname: string, minLine: number): number | undefined {
  if (qualname === '<module>' || qualname.startsWith('<')) return undefined;
  const name = qualname.slice(qualname.lastIndexOf('.') + 1);
  const re = new RegExp(`^\\s*(?:async\\s+)?def\\s+${name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s*[\\(\\[]`);
  const start = Math.min(doc.lineCount - 1, Math.max(0, (minLine || 1) - 1));
  for (let i = start; i >= 0 && i >= start - 2000; i--) {
    if (re.test(doc.lineAt(i).text)) return i;
  }
  for (let i = 0; i < doc.lineCount; i++) if (re.test(doc.lineAt(i).text)) return i;
  return undefined;
}
