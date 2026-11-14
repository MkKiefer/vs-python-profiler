/** Registers every `pyprof.*` command and maps it to the object that implements it. */
import * as vscode from 'vscode';
import * as path from 'node:path';
import type { Dashboards } from './dashboards';
import type { EditorHeat } from './editorHeat';
import type { LaunchAdapter } from './launch';
import { openSource } from './openSource';
import type { ProcessPicker, ProcInfo } from './processes';
import { ProfileEditorProvider } from './profileEditorProvider';
import { PROFILE_EXTENSION } from './profileFile';
import { Session } from './session';
import type { SessionActions } from './sessionActions';
import type { SessionManager } from './sessionManager';
import type { ProcessesView } from './views/processesView';
import type { SessionNode } from './views/sessionsView';
import { errorDetail, errorMessage } from '../shared/errors';

export interface CommandDependencies {
  log: vscode.LogOutputChannel;
  sessions: SessionManager;
  actions: SessionActions;
  launcher: LaunchAdapter;
  picker: ProcessPicker;
  dashboards: Dashboards;
  heat: EditorHeat;
  processesView: ProcessesView;
}

/** What a command receives: a session id (links), a tree node (context menus) or nothing (palette). */
type SessionArgument = string | SessionNode | undefined;

export class Commands {
  constructor(private readonly deps: CommandDependencies) {}

  register(ctx: vscode.ExtensionContext): void {
    const { sessions, actions, launcher, picker, heat, processesView } = this.deps;
    const handlers: Record<string, (...args: never[]) => unknown> = {
      'pyprof.profileFile': (arg?: unknown) => launcher.profileFile(arg),
      'pyprof.profileConfiguration': () => launcher.profileConfiguration(),
      'pyprof.profileTest': () => launcher.profileTest(),
      'pyprof.attach': () => picker.pickAndAttach(),
      'pyprof.attachProcess': (process: ProcInfo) => picker.attach(process),
      'pyprof.refreshProcesses': () => processesView.refresh(),
      'pyprof.stop': (arg: SessionArgument) => this.withLiveSession(arg, (s) => sessions.stop(s)),
      'pyprof.stopAndTerminate': (arg: SessionArgument) => this.withLiveSession(arg, (s) => sessions.stop(s, true)),
      'pyprof.snapshot': (arg: SessionArgument) => this.withLiveSession(arg, (s) => actions.snapshot(s)),
      'pyprof.toggleTracemalloc': (arg: SessionArgument) => this.withLiveSession(arg, (s) => actions.setTracemalloc(s)),
      'pyprof.toggleAsyncioDebug': (arg: SessionArgument) => this.withLiveSession(arg, (s) => actions.setAsyncioDebug(s)),
      'pyprof.mark': (arg: SessionArgument) => this.withLiveSession(arg, (s) => actions.mark(s)),
      'pyprof.openDashboard': (arg: SessionArgument) => this.openDashboard(arg),
      'pyprof.selectSession': (id: string) => this.selectSession(id),
      'pyprof.saveProfile': (arg: SessionArgument) => this.withSession(arg, (s) => actions.saveAs(s)),
      'pyprof.export': (arg: SessionArgument) => this.withSession(arg, (s) => actions.export(s)),
      'pyprof.removeSession': (arg: SessionArgument) => this.withSession(arg, (s) => sessions.remove(s)),
      'pyprof.deleteSession': (node: SessionNode) => this.deleteSavedProfile(node),
      'pyprof.openProfile': () => this.openProfile(),
      'pyprof.toggleHeat': () => heat.toggle(),
      'pyprof.revealFunction': (id: string, fn: number, openFile?: boolean) => this.revealFunction(id, fn, openFile),
    };
    for (const [id, handler] of Object.entries(handlers)) {
      ctx.subscriptions.push(vscode.commands.registerCommand(id, this.reportingErrors(handler)));
    }
    // used as `${command:pyprof.pickProcess}`: its return value is the result, errors go to the caller
    ctx.subscriptions.push(vscode.commands.registerCommand('pyprof.pickProcess', () => picker.pickPid()));
  }

  /** Commands never fail silently: log the stack, tell the user. */
  private reportingErrors(handler: (...args: never[]) => unknown): (...args: never[]) => Promise<void> {
    return async (...args) => {
      try {
        await handler(...args);
      } catch (e) {
        this.deps.log.error(errorDetail(e));
        void vscode.window.showErrorMessage(`Python Profiler: ${errorMessage(e)}`);
      }
    };
  }

  private resolve(arg: SessionArgument): Session | undefined {
    if (typeof arg === 'string') return this.deps.sessions.find(arg);
    if (arg?.kind === 'session') return arg.session;
    return this.deps.sessions.active;
  }

  private async withSession(arg: SessionArgument, action: (session: Session) => Promise<void>): Promise<void> {
    const session = this.resolve(arg);
    if (session) await action(session);
    else void vscode.window.showInformationMessage('No profiling session yet. Use "Profile Python File" first.');
  }

  /** Like `withSession`, falling back to any live session when the given one has ended. */
  private async withLiveSession(arg: SessionArgument, action: (session: Session) => Promise<void>): Promise<void> {
    const given = this.resolve(arg);
    const live = given?.live ? given : this.deps.sessions.sessions.find((s) => s.live);
    if (live) await action(live);
    else void vscode.window.showInformationMessage('No live profiling session.');
  }

  private async openDashboard(arg: SessionArgument): Promise<void> {
    await this.withSession(arg, (session) => {
      this.deps.dashboards.open(session);
      return Promise.resolve();
    });
  }

  private selectSession(id: string): void {
    const session = this.deps.sessions.find(id);
    if (!session) return;
    this.deps.sessions.setActive(session);
    this.deps.dashboards.open(session);
  }

  private async deleteSavedProfile(node: SessionNode | undefined): Promise<void> {
    const file = node?.kind === 'saved' ? node.file : node?.kind === 'session' ? node.session.filePath : undefined;
    if (!file) return;
    const confirmed = await vscode.window.showWarningMessage(`Delete ${path.basename(file)}?`, { modal: true }, 'Delete');
    if (confirmed) this.deps.sessions.deleteSaved(file);
  }

  private async openProfile(): Promise<void> {
    const uris = await vscode.window.showOpenDialog({
      filters: { 'Python profile': [PROFILE_EXTENSION] },
      canSelectMany: false,
    });
    if (uris?.[0]) await vscode.commands.executeCommand('vscode.openWith', uris[0], ProfileEditorProvider.viewType);
  }

  private async revealFunction(id: string, fn: number, openFile = false): Promise<void> {
    const session = this.deps.sessions.find(id);
    if (!session) return;
    const target = session.model.fns[fn];
    if (openFile && target) await openSource(target.file, target.minLine);
    this.deps.dashboards.revealFunction(session, fn);
  }
}
