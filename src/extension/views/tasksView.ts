/** Sidebar "Async Tasks": the asyncio task tree of the active session. */
import * as vscode from 'vscode';
import type { Session } from '../session';
import type { SessionManager } from '../sessionManager';
import { fmtMs, isSyntheticFile } from '../../shared/format';
import type { TaskRec } from '../../shared/model';

interface TaskNode {
  session: Session;
  task: TaskRec;
  /** tasks awaited by this one, among the tasks shown */
  children: TaskRec[];
}

const POLL_MS = 1000;
const MAX_FINISHED = 200;
const MAX_SIBLINGS = 500;
const STATE_ICON: Record<TaskRec['state'], { icon: string; color: string }> = {
  running: { icon: 'play-circle', color: 'charts.green' },
  waiting: { icon: 'watch', color: 'charts.yellow' },
  done: { icon: 'pass', color: 'descriptionForeground' },
};

export class TasksView implements vscode.TreeDataProvider<TaskNode>, vscode.Disposable {
  private readonly changed = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData = this.changed.event;
  private readonly disposables: vscode.Disposable[];
  private readonly timer: NodeJS.Timeout;
  private shown = '';

  constructor(private readonly sessions: SessionManager) {
    this.disposables = [sessions.onDidChangeActive(() => this.changed.fire())];
    this.timer = setInterval(() => {
      const model = sessions.active?.model;
      const current = model ? `${sessions.active?.id}:${model.tasks.size}:${model.taskEvents.length}` : '';
      if (current !== this.shown) {
        this.shown = current;
        this.changed.fire();
      }
    }, POLL_MS);
  }

  getChildren(node?: TaskNode): TaskNode[] {
    const session = node?.session ?? this.sessions.active;
    if (!session) return [];
    const shown = this.shownTasks(session);
    const byParent = new Map<number | null, TaskRec[]>();
    const ids = new Set(shown.map((t) => t.id));
    for (const task of shown) {
      // a task whose parent is not shown becomes a root
      const parent = task.parent !== null && ids.has(task.parent) ? task.parent : null;
      const siblings = byParent.get(parent);
      if (siblings) siblings.push(task);
      else byParent.set(parent, [task]);
    }
    return (byParent.get(node ? node.task.id : null) ?? [])
      .sort((a, b) => a.start - b.start)
      .slice(0, MAX_SIBLINGS)
      .map((task) => ({ session, task, children: byParent.get(task.id) ?? [] }));
  }

  getTreeItem(node: TaskNode): vscode.TreeItem {
    const { session, task } = node;
    const item = new vscode.TreeItem(
      task.name,
      node.children.length ? vscode.TreeItemCollapsibleState.Expanded : vscode.TreeItemCollapsibleState.None,
    );
    const age = (task.end ?? session.model.now) - task.start;
    const where = task.stack >= 0 ? session.model.userLeaf(task.stack) : undefined;
    item.description = [task.state, fmtMs(age), where && `${where.func}:${where.line}`].filter(Boolean).join(' · ');
    const { icon, color } = STATE_ICON[task.state];
    item.iconPath = new vscode.ThemeIcon(icon, new vscode.ThemeColor(color));
    if (where && !isSyntheticFile(where.file)) {
      const line = Math.max(0, where.line - 1);
      item.command = {
        command: 'vscode.open',
        title: 'Open',
        arguments: [vscode.Uri.file(where.file), { selection: new vscode.Range(line, 0, line, 0) }],
      };
    }
    return item;
  }

  /** Running tasks while there are any; otherwise the most recent finished ones. */
  private shownTasks(session: Session): TaskRec[] {
    const all = [...session.model.tasks.values()];
    const alive = all.filter((t) => t.end === null);
    return alive.length ? alive : all.slice(-MAX_FINISHED);
  }

  dispose(): void {
    clearInterval(this.timer);
    for (const d of this.disposables) d.dispose();
    this.changed.dispose();
  }
}
