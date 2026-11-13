/** Sidebar "Sessions": live and finished sessions plus auto-saved profiles. */
import * as vscode from 'vscode';
import * as path from 'node:path';
import { ProfileEditorProvider } from '../profileEditorProvider';
import { PROFILE_EXTENSION } from '../profileFile';
import type { Session } from '../session';
import type { SavedProfile, SessionManager } from '../sessionManager';
import { fmtBytes, fmtCount } from '../../shared/format';
import type { SessionState } from '../../shared/protocol';

export type SessionNode =
  | { kind: 'session'; session: Session }
  | ({ kind: 'saved' } & SavedProfile)
  | { kind: 'savedGroup'; profiles: SavedProfile[] };

const STATE_ICON: Record<SessionState, { icon: string; color?: string }> = {
  starting: { icon: 'loading~spin' },
  waiting: { icon: 'loading~spin' },
  running: { icon: 'record', color: 'charts.red' },
  stopped: { icon: 'debug-stop' },
  exited: { icon: 'pass', color: 'charts.green' },
  error: { icon: 'error', color: 'errorForeground' },
  file: { icon: 'file' },
};
const LIVE_REFRESH_MS = 2000;
const TIMESTAMP_PREFIX = /^\d{4}-\d\d-\d\dT[\d-]+Z_/;

export class SessionsView implements vscode.TreeDataProvider<SessionNode>, vscode.Disposable {
  private readonly changed = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData = this.changed.event;
  private readonly disposables: vscode.Disposable[];
  private readonly timer: NodeJS.Timeout;

  constructor(private readonly sessions: SessionManager) {
    this.disposables = [
      sessions.onDidChange(() => this.changed.fire()),
      sessions.onDidChangeActive(() => this.changed.fire()),
    ];
    // live sample counts and memory in the descriptions
    this.timer = setInterval(() => {
      if (sessions.sessions.some((s) => s.live)) this.changed.fire();
    }, LIVE_REFRESH_MS);
  }

  getChildren(node?: SessionNode): SessionNode[] {
    if (node?.kind === 'savedGroup') return node.profiles.map((profile) => ({ kind: 'saved', ...profile }));
    if (node) return [];
    const nodes: SessionNode[] = this.sessions.sessions.map((session) => ({ kind: 'session', session }));
    const profiles = this.sessions.savedProfiles();
    if (profiles.length) nodes.push({ kind: 'savedGroup', profiles });
    return nodes;
  }

  getTreeItem(node: SessionNode): vscode.TreeItem {
    switch (node.kind) {
      case 'savedGroup':
        return this.savedGroupItem(node.profiles.length);
      case 'saved':
        return this.savedItem(node);
      case 'session':
        return this.sessionItem(node.session);
    }
  }

  private savedGroupItem(count: number): vscode.TreeItem {
    const item = new vscode.TreeItem(`Saved profiles (${count})`, vscode.TreeItemCollapsibleState.Collapsed);
    item.iconPath = new vscode.ThemeIcon('history');
    return item;
  }

  private savedItem(profile: SavedProfile): vscode.TreeItem {
    const uri = vscode.Uri.file(profile.file);
    const name = path.basename(profile.file, `.${PROFILE_EXTENSION}`).replace(TIMESTAMP_PREFIX, '');
    const item = new vscode.TreeItem(name);
    item.description = `${new Date(profile.mtime).toLocaleString()} · ${fmtBytes(profile.size)}`;
    item.iconPath = new vscode.ThemeIcon('file');
    item.contextValue = 'session.saved';
    item.resourceUri = uri;
    item.command = { command: 'vscode.openWith', title: 'Open', arguments: [uri, ProfileEditorProvider.viewType] };
    return item;
  }

  private sessionItem(session: Session): vscode.TreeItem {
    const item = new vscode.TreeItem(session.label);
    const { icon, color } = STATE_ICON[session.state];
    item.iconPath = new vscode.ThemeIcon(icon, color ? new vscode.ThemeColor(color) : undefined);
    item.description = this.describe(session);
    item.tooltip = this.tooltip(session);
    item.contextValue = session.live ? 'session.live' : 'session.done';
    item.command = { command: 'pyprof.selectSession', title: 'Show', arguments: [session.id] };
    return item;
  }

  private describe(session: Session): string {
    const parts: string[] = [];
    if (session === this.sessions.active) parts.push('●');
    if (session.pid) parts.push(`PID ${session.pid}`);
    parts.push(session.state === 'file' ? 'saved' : session.state);
    const samples = session.model.stats.samples;
    if (samples) parts.push(`${fmtCount(samples)} samples`);
    const rss = session.model.lastValue('rss');
    if (session.live && rss) parts.push(fmtBytes(rss));
    return parts.join(' · ');
  }

  private tooltip(session: Session): vscode.MarkdownString {
    const lines = [
      `**${session.label}**\n`,
      `- kind: ${session.kind}`,
      `- state: ${session.state}${session.error ? ` — ${session.error}` : ''}`,
    ];
    if (session.python) lines.push(`- interpreter: \`${session.python.executable}\` (${session.python.version})`);
    if (session.pid) lines.push(`- PID: ${session.pid}`);
    if (session.kind !== 'file') lines.push(`- agent: ${session.capabilities.agent ? 'connected' : 'not connected'}`);
    if (session.filePath) lines.push(`- file: \`${session.filePath}\``);
    return new vscode.MarkdownString(lines.join('\n'));
  }

  dispose(): void {
    clearInterval(this.timer);
    for (const d of this.disposables) d.dispose();
    this.changed.dispose();
  }
}
