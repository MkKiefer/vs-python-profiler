/** Sidebar "Hotspots": the hottest functions of the active session, following the dashboard's filters. */
import * as vscode from 'vscode';
import type { Dashboards } from '../dashboards';
import type { Session } from '../session';
import type { SessionManager } from '../sessionManager';
import { fmtPct, isSyntheticFile, moduleLabel } from '../../shared/format';
import { Cat, type FnStat } from '../../shared/model';

interface HotspotNode extends FnStat {
  session: Session;
  /** weight of all samples in the selection */
  all: number;
}

const MAX_ROWS = 30;
const POLL_MS = 1500;
const CATEGORY_COLOR: Record<Cat, string> = {
  [Cat.User]: 'charts.orange',
  [Cat.Lib]: 'charts.blue',
  [Cat.Std]: 'descriptionForeground',
  [Cat.Synth]: 'descriptionForeground',
};

export class HotspotsView implements vscode.TreeDataProvider<HotspotNode>, vscode.Disposable {
  private readonly changed = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData = this.changed.event;
  private readonly disposables: vscode.Disposable[];
  private readonly timer: NodeJS.Timeout;
  private shown = '';

  constructor(
    private readonly sessions: SessionManager,
    private readonly dashboards: Dashboards,
  ) {
    this.disposables = [
      sessions.onDidChangeActive(() => this.changed.fire()),
      dashboards.onDidChangeViewState(() => this.changed.fire()),
    ];
    // live data arrives several times a second: refresh only when the model actually moved on
    this.timer = setInterval(() => {
      const session = sessions.active;
      const current = session ? `${session.id}:${session.model.version}` : '';
      if (current !== this.shown) {
        this.shown = current;
        this.changed.fire();
      }
    }, POLL_MS);
  }

  getChildren(node?: HotspotNode): HotspotNode[] {
    const session = this.sessions.active;
    if (node || !session) return [];
    const model = session.model;
    const view = this.dashboards.viewState(session);
    const counts = model.countStacks({
      mode: view?.mode ?? 'wall',
      t0: view?.t0,
      t1: view?.t1,
      threads: view?.threads?.length ? new Set(view.threads) : null,
    });
    const all = model.totalWeight(counts);
    return model
      .topFunctions(counts)
      .filter((stat) => model.fns[stat.fn].cat !== Cat.Synth || stat.self > 0)
      .slice(0, MAX_ROWS)
      .map((stat) => ({ ...stat, session, all }));
  }

  getTreeItem(node: HotspotNode): vscode.TreeItem {
    const fn = node.session.model.fns[node.fn];
    const item = new vscode.TreeItem(fn.func);
    item.description = `${fmtPct(node.self, node.all)} self · ${fmtPct(node.total, node.all)} total · ${moduleLabel(fn.file)}`;
    item.tooltip = `${fn.func}\n${fn.file}:${fn.minLine}\n\nself ${node.self} samples, total ${node.total} samples`;
    item.iconPath = new vscode.ThemeIcon('flame', new vscode.ThemeColor(CATEGORY_COLOR[fn.cat]));
    if (!isSyntheticFile(fn.file)) {
      item.command = { command: 'vspyprof.revealFunction', title: 'Show', arguments: [node.session.id, node.fn, true] };
    }
    return item;
  }

  dispose(): void {
    clearInterval(this.timer);
    for (const d of this.disposables) d.dispose();
    this.changed.dispose();
  }
}
