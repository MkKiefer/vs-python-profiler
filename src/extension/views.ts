/** Sidebar tree views: Sessions, Python Processes, Hotspots, Async Tasks. */
import * as vscode from 'vscode';
import * as path from 'node:path';
import type { Session, SessionManager } from './session';
import type { ProcessPicker, ProcInfo } from './processes';
import { shortTitle } from './processes';
import type { Dashboards } from './dashboard';
import { fmtBytes, fmtCount, fmtMs, fmtPct, moduleLabel } from '../shared/format';
import { Cat, type TaskRec } from '../shared/model';

const STATE_ICON: Record<string, [string, string?]> = {
  starting: ['loading~spin'],
  waiting: ['loading~spin'],
  running: ['record', 'charts.red'],
  stopped: ['debug-stop'],
  exited: ['pass', 'charts.green'],
  error: ['error', 'errorForeground'],
  file: ['file'],
};

type SessionNode = { kind: 'session'; session: Session } | { kind: 'saved'; file: string; mtime: number; size: number } | { kind: 'group'; label: string };

export class SessionsView implements vscode.TreeDataProvider<SessionNode> {
  private readonly changed = new vscode.EventEmitter<SessionNode | void>();
  readonly onDidChangeTreeData = this.changed.event;

  constructor(private readonly sessions: SessionManager) {
    sessions.onDidChange(() => this.changed.fire());
    sessions.onDidChangeActive(() => this.changed.fire());
    // live stats in descriptions
    setInterval(() => {
      if (sessions.sessions.some((s) => s.live)) this.changed.fire();
    }, 2000);
  }

  getChildren(node?: SessionNode): SessionNode[] {
    if (!node) {
      const out: SessionNode[] = this.sessions.sessions.map((session) => ({ kind: 'session', session }));
      const saved = this.sessions.savedFiles();
      if (saved.length) out.push({ kind: 'group', label: `Saved profiles (${saved.length})` });
      return out;
    }
    if (node.kind === 'group') return this.sessions.savedFiles().map((f) => ({ kind: 'saved', ...f }));
    return [];
  }

  getTreeItem(node: SessionNode): vscode.TreeItem {
    if (node.kind === 'group') {
      const it = new vscode.TreeItem(node.label, vscode.TreeItemCollapsibleState.Collapsed);
      it.iconPath = new vscode.ThemeIcon('history');
      return it;
    }
    if (node.kind === 'saved') {
      const name = path.basename(node.file, '.pyprof').replace(/^\d{4}-\d\d-\d\dT[\d-]+Z_/, '');
      const it = new vscode.TreeItem(name);
      it.description = `${new Date(node.mtime).toLocaleString()} · ${fmtBytes(node.size)}`;
      it.iconPath = new vscode.ThemeIcon('file');
      it.contextValue = 'session.saved';
      it.resourceUri = vscode.Uri.file(node.file);
      it.command = { command: 'vscode.openWith', title: 'Open', arguments: [vscode.Uri.file(node.file), 'pyprof.profileViewer'] };
      return it;
    }
    const s = node.session;
    const it = new vscode.TreeItem(s.label);
    const [icon, color] = STATE_ICON[s.state] ?? ['circle-outline'];
    it.iconPath = new vscode.ThemeIcon(icon, color ? new vscode.ThemeColor(color) : undefined);
    const parts: string[] = [];
    if (s.pid) parts.push(`PID ${s.pid}`);
    parts.push(s.state === 'file' ? 'saved' : s.state);
    if (s.model.stats.samples) parts.push(`${fmtCount(s.model.stats.samples)} samples`);
    const rss = s.model.lastValue('rss');
    if (s.live && rss) parts.push(fmtBytes(rss));
    if (s === this.sessions.active) parts.unshift('●');
    it.description = parts.join(' · ');
    it.tooltip = new vscode.MarkdownString(
      `**${s.label}**\n\n` +
        `- kind: ${s.kind}\n- state: ${s.state}${s.error ? ` — ${s.error}` : ''}\n` +
        (s.python ? `- interpreter: \`${s.python.executable}\` (${s.python.version})\n` : '') +
        (s.pid ? `- PID: ${s.pid}\n` : '') +
        `- agent: ${s.capabilities.agent ? 'connected' : 'not connected'}\n` +
        (s.filePath ? `- file: \`${s.filePath}\`\n` : ''),
    );
    it.contextValue = s.live ? 'session.live' : 'session.done';
    it.command = { command: 'pyprof.selectSession', title: 'Show', arguments: [s.id] };
    return it;
  }
}

// ------------------------------------------------------------------ processes
type ProcNode = ProcInfo | { empty: string };

export class ProcessesView implements vscode.TreeDataProvider<ProcNode> {
  private readonly changed = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData = this.changed.event;

  constructor(private readonly picker: ProcessPicker) {}

  refresh(): void {
    this.changed.fire();
  }

  async getChildren(node?: ProcNode): Promise<ProcNode[]> {
    if (node) return [];
    const procs = this.picker.rank(await this.picker.list());
    return procs.length ? procs : [{ empty: 'No Python processes running' }];
  }

  getTreeItem(p: ProcNode): vscode.TreeItem {
    if ('empty' in p) return new vscode.TreeItem(p.empty);
    const it = new vscode.TreeItem(shortTitle(p));
    it.description = `${p.pid}${p.version ? ' · ' + p.version : ''}${p.venv ? ' · ' + path.basename(p.venv) : ''}`;
    it.tooltip = `${p.title}\n\nPID ${p.pid} (parent ${p.ppid})\n${p.executable}${p.cwd ? '\ncwd: ' + p.cwd : ''}`;
    it.iconPath = new vscode.ThemeIcon('terminal');
    it.contextValue = 'process';
    return it;
  }
}

// ------------------------------------------------------------------- hotspots
interface HotNode {
  fn: number;
  self: number;
  total: number;
  all: number;
}

export class HotspotsView implements vscode.TreeDataProvider<HotNode> {
  private readonly changed = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData = this.changed.event;
  private lastKey = '';

  constructor(
    private readonly sessions: SessionManager,
    private readonly dashboards: Dashboards,
  ) {
    sessions.onDidChangeActive(() => this.changed.fire());
    dashboards.onDidChangeViewState(() => this.changed.fire());
    setInterval(() => {
      const s = sessions.active;
      const key = s ? `${s.id}:${s.model.version}` : '';
      if (key !== this.lastKey) {
        this.lastKey = key;
        this.changed.fire();
      }
    }, 1500);
  }

  getChildren(node?: HotNode): HotNode[] {
    if (node) return [];
    const s = this.sessions.active;
    if (!s) return [];
    const v = this.dashboards.viewState.get(s.id);
    const counts = s.model.countStacks({
      mode: v?.mode ?? 'wall',
      t0: v?.t0,
      t1: v?.t1,
      threads: v?.threads?.length ? new Set(v.threads) : null,
    });
    const all = s.model.totalWeight(counts);
    return s.model
      .topFunctions(counts)
      .filter((f) => s.model.fns[f.fn].cat !== Cat.Synth || f.self > 0)
      .slice(0, 30)
      .map((f) => ({ ...f, all }));
  }

  getTreeItem(n: HotNode): vscode.TreeItem {
    const s = this.sessions.active!;
    const fn = s.model.fns[n.fn];
    const it = new vscode.TreeItem(fn.func);
    it.description = `${fmtPct(n.self, n.all)} self · ${fmtPct(n.total, n.all)} total · ${moduleLabel(fn.file)}`;
    it.tooltip = `${fn.func}\n${fn.file}:${fn.minLine}\n\nself ${n.self} samples, total ${n.total} samples`;
    it.iconPath = new vscode.ThemeIcon(
      'flame',
      new vscode.ThemeColor(fn.cat === Cat.User ? 'charts.orange' : fn.cat === Cat.Lib ? 'charts.blue' : 'descriptionForeground'),
    );
    if (fn.file && !fn.file.startsWith('<') && !fn.file.startsWith('~')) {
      it.command = { command: 'pyprof.revealFunction', title: 'Show', arguments: [s.id, n.fn, true] };
    }
    return it;
  }
}

// --------------------------------------------------------------------- tasks
export class TasksView implements vscode.TreeDataProvider<TaskRec> {
  private readonly changed = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData = this.changed.event;
  private lastKey = '';

  constructor(private readonly sessions: SessionManager) {
    sessions.onDidChangeActive(() => this.changed.fire());
    setInterval(() => {
      const s = sessions.active;
      const key = s ? `${s.id}:${s.model.tasks.size}:${s.model.taskEvents.length}` : '';
      if (key !== this.lastKey) {
        this.lastKey = key;
        this.changed.fire();
      }
    }, 1000);
  }

  getChildren(node?: TaskRec): TaskRec[] {
    const s = this.sessions.active;
    if (!s) return [];
    const all = [...s.model.tasks.values()];
    const live = all.filter((t) => t.end === null);
    const pool = live.length ? live : all.slice(-200);
    const ids = new Set(pool.map((t) => t.id));
    const kids = pool.filter((t) => (node ? t.parent === node.id : t.parent === null || !ids.has(t.parent)));
    return kids.sort((a, b) => a.start - b.start).slice(0, 500);
  }

  getTreeItem(t: TaskRec): vscode.TreeItem {
    const s = this.sessions.active!;
    const hasKids = [...s.model.tasks.values()].some((x) => x.parent === t.id && (x.end === null || t.end !== null));
    const it = new vscode.TreeItem(t.name, hasKids ? vscode.TreeItemCollapsibleState.Expanded : vscode.TreeItemCollapsibleState.None);
    const age = (t.end ?? s.model.now) - t.start;
    const where = t.stack >= 0 ? s.model.userLeaf(t.stack) : undefined;
    it.description = `${t.state} · ${fmtMs(age)}${where ? ` · ${where.func}:${where.line}` : ''}`;
    it.iconPath = new vscode.ThemeIcon(
      t.state === 'running' ? 'play-circle' : t.state === 'done' ? 'pass' : 'watch',
      new vscode.ThemeColor(t.state === 'running' ? 'charts.green' : t.state === 'done' ? 'descriptionForeground' : 'charts.yellow'),
    );
    if (where && !where.file.startsWith('<')) {
      it.command = { command: 'vscode.open', title: 'Open', arguments: [vscode.Uri.file(where.file), { selection: new vscode.Range(where.line - 1, 0, where.line - 1, 0) }] };
    }
    return it;
  }
}

// ----------------------------------------------------------------- status bar
export class StatusBar implements vscode.Disposable {
  private item = vscode.window.createStatusBarItem('pyprof.status', vscode.StatusBarAlignment.Left, 50);
  private stop = vscode.window.createStatusBarItem('pyprof.stop', vscode.StatusBarAlignment.Left, 49);
  private timer: NodeJS.Timeout;

  constructor(private readonly sessions: SessionManager) {
    this.item.name = 'Python Profiler';
    this.item.command = 'pyprof.openDashboard';
    this.stop.name = 'Python Profiler: Stop';
    this.stop.text = '$(debug-stop)';
    this.stop.tooltip = 'Stop profiling';
    this.stop.command = 'pyprof.stop';
    this.timer = setInterval(() => this.update(), 1000);
    sessions.onDidChange(() => this.update());
    sessions.onDidChangeActive(() => this.update());
  }

  private update(): void {
    const s = this.sessions.active;
    if (!s || !s.live) {
      this.item.hide();
      this.stop.hide();
      return;
    }
    const m = s.model;
    const parts = [s.state === 'running' ? '$(flame)' : '$(loading~spin)'];
    parts.push(s.pid ? `PID ${s.pid}` : s.label);
    if (m.stats.samples) parts.push(`${fmtCount(m.stats.samples)} samples`);
    const cpu = m.lastValue('cpu');
    if (cpu !== undefined) parts.push(`CPU ${cpu.toFixed(0)}%`);
    const rss = m.lastValue('rss');
    if (rss !== undefined) parts.push(fmtBytes(rss));
    const lag = m.lastValue('loopLag');
    if (lag !== undefined) parts.push(`lag ${fmtMs(lag)}`);
    this.item.text = parts.join(' · ');
    this.item.tooltip = new vscode.MarkdownString(
      `**Profiling ${s.label}**\n\n${s.python ? `\`${s.python.label}\`\n\n` : ''}Sampling at ${m.stats.rateHz || '…'} Hz · ${m.stats.errors} errors\n\nClick to open the dashboard`,
    );
    this.item.backgroundColor = lag !== undefined && lag > 100 ? new vscode.ThemeColor('statusBarItem.warningBackground') : undefined;
    this.item.show();
    this.stop.show();
  }

  dispose(): void {
    clearInterval(this.timer);
    this.item.dispose();
    this.stop.dispose();
  }
}
