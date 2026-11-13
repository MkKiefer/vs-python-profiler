/** What a user can do with a session – shared by the command palette, tree views and the dashboard. */
import * as vscode from 'vscode';
import * as fs from 'node:fs';
import type { CollectorClient } from './collectorClient';
import { PROFILE_EXTENSION, profileFileStem } from './profileFile';
import type { Session } from './session';
import type { SessionManager } from './sessionManager';
import { settings } from './settings';
import { toCollapsed, toSpeedscope } from '../shared/exporters';
import type { CommandRequest } from '../shared/protocol';

export type ExportFormat = 'speedscope' | 'collapsed';

const EXPORT_FILE_SUFFIX: Record<ExportFormat, string> = {
  speedscope: 'speedscope.json',
  collapsed: 'collapsed.txt',
};
const SLOW_REQUEST_TIMEOUT_MS = 180_000;

export class SessionActions {
  constructor(private readonly sessions: SessionManager) {}

  /** Run a command sent by the dashboard. */
  async run(request: CommandRequest, session: Session): Promise<void> {
    switch (request.command) {
      case 'stop':
        return this.sessions.stop(session, request.args.terminate === true);
      case 'snapshot':
        return this.snapshot(session, request.args.label);
      case 'tracemalloc':
        return this.setTracemalloc(session, request.args.enabled);
      case 'asyncioDebug':
        return this.setAsyncioDebug(session, request.args.enabled);
      case 'objectCounts':
        return this.countObjects(session);
      case 'mark':
        return this.mark(session, request.args.name);
      case 'save':
        return this.saveAs(session);
      case 'exportSpeedscope':
        return this.export(session, 'speedscope');
      case 'exportCollapsed':
        return this.export(session, 'collapsed');
    }
  }

  /** Take a memory snapshot, starting tracemalloc first if needed. */
  async snapshot(session: Session, label?: string): Promise<void> {
    const client = this.liveClient(session);
    if (!session.capabilities.tracemalloc) {
      await this.setTracemalloc(session, true);
      void vscode.window.showInformationMessage(
        'Memory tracing started (tracemalloc). Allocations from now on are tracked; take another snapshot later to compare.',
      );
    }
    await vscode.window.withProgress({ location: vscode.ProgressLocation.Window, title: 'Taking memory snapshot…' }, () =>
      client.request('snapshot', { label }, SLOW_REQUEST_TIMEOUT_MS),
    );
  }

  /** Switch tracemalloc on or off (toggles when `enabled` is omitted). */
  async setTracemalloc(session: Session, enabled = !session.capabilities.tracemalloc): Promise<void> {
    await this.liveClient(session).request('tracemalloc', { enabled });
    session.updateCapabilities({ tracemalloc: enabled });
  }

  /** Switch asyncio debug mode on or off (toggles when `enabled` is omitted). */
  async setAsyncioDebug(session: Session, enabled = !session.capabilities.asyncioDebug): Promise<void> {
    await this.liveClient(session).request('asyncioDebug', { enabled, slowMs: settings.slowCallbackMs() });
    session.updateCapabilities({ asyncioDebug: enabled });
  }

  async countObjects(session: Session): Promise<void> {
    const client = this.liveClient(session);
    await vscode.window.withProgress({ location: vscode.ProgressLocation.Window, title: 'Counting objects…' }, () =>
      client.request('objectCounts', {}, SLOW_REQUEST_TIMEOUT_MS),
    );
  }

  /** Drop a named marker on the timeline (asks for the name when none is given). */
  async mark(session: Session, name?: string): Promise<void> {
    const client = this.liveClient(session);
    const marker = name ?? (await vscode.window.showInputBox({ prompt: 'Marker name', value: 'marker' }));
    if (marker) await client.request('mark', { name: marker });
  }

  async saveAs(session: Session): Promise<void> {
    const uri = await vscode.window.showSaveDialog({
      defaultUri: this.defaultUri(session, PROFILE_EXTENSION),
      filters: { 'Python profile': [PROFILE_EXTENSION] },
    });
    if (!uri) return;
    await this.sessions.saveAs(session, uri.fsPath);
    void vscode.window.showInformationMessage(`Saved profile to ${uri.fsPath}`);
  }

  /** Export for other tools (asks for the format when none is given). */
  async export(session: Session, format?: ExportFormat): Promise<void> {
    const chosen = format ?? (await this.pickExportFormat());
    if (!chosen) return;
    const uri = await vscode.window.showSaveDialog({ defaultUri: this.defaultUri(session, EXPORT_FILE_SUFFIX[chosen]) });
    if (!uri) return;
    const content =
      chosen === 'speedscope' ? JSON.stringify(toSpeedscope(session.model, session.label)) : toCollapsed(session.model);
    await fs.promises.writeFile(uri.fsPath, content);
    void vscode.window.showInformationMessage(`Exported ${chosen} profile to ${uri.fsPath}`);
  }

  private async pickExportFormat(): Promise<ExportFormat | undefined> {
    const items: (vscode.QuickPickItem & { format: ExportFormat })[] = [
      { label: 'speedscope (.speedscope.json)', format: 'speedscope', detail: 'Open at speedscope.app' },
      { label: 'Collapsed stacks (.txt)', format: 'collapsed', detail: 'flamegraph.pl, inferno, speedscope' },
    ];
    return (await vscode.window.showQuickPick(items, { title: 'Export profile' }))?.format;
  }

  private defaultUri(session: Session, suffix: string): vscode.Uri | undefined {
    const folder = vscode.workspace.workspaceFolders?.[0]?.uri;
    return folder ? vscode.Uri.joinPath(folder, `${profileFileStem(session.label)}.${suffix}`) : undefined;
  }

  private liveClient(session: Session): CollectorClient {
    const client = session.client;
    if (!client || !session.live) throw new Error('This session is not live any more.');
    return client;
  }
}
