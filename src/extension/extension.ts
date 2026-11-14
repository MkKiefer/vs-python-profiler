/** Composition root: builds the extension's objects and wires them together. */
import * as vscode from 'vscode';
import * as path from 'node:path';
import { Commands } from './commands';
import { Dashboards } from './dashboards';
import { EditorHeat } from './editorHeat';
import { EnvironmentResolver } from './environment';
import { LaunchAdapter } from './launch';
import { ExtPaths } from './paths';
import { ProcessPicker } from './processes';
import { ProfileEditorProvider } from './profileEditorProvider';
import type { Session } from './session';
import { SessionActions } from './sessionActions';
import { SessionManager } from './sessionManager';
import { settings } from './settings';
import { HotspotsView } from './views/hotspotsView';
import { ProcessesView } from './views/processesView';
import { SessionsView } from './views/sessionsView';
import { StatusBar } from './views/statusBar';
import { TasksView } from './views/tasksView';
import { errorMessage } from '../shared/errors';

export function activate(ctx: vscode.ExtensionContext): void {
  const log = vscode.window.createOutputChannel('Python Profiler', { log: true });
  const paths = new ExtPaths(ctx.extensionPath);

  const env = new EnvironmentResolver(log);
  const storage = path.join((ctx.storageUri ?? ctx.globalStorageUri).fsPath, 'profiles');
  const sessions = new SessionManager(paths, log, storage);
  const picker = new ProcessPicker(paths, env, sessions, log);
  const launcher = new LaunchAdapter(env, sessions, picker);
  const actions = new SessionActions(sessions);
  const dashboards = new Dashboards(ctx, sessions, actions);
  const heat = new EditorHeat(sessions, dashboards);
  const sessionsView = new SessionsView(sessions);
  const processesView = new ProcessesView(picker);
  const hotspotsView = new HotspotsView(sessions, dashboards);
  const tasksView = new TasksView(sessions);

  launcher.register(ctx);
  new Commands({ log, sessions, actions, launcher, picker, dashboards, heat, processesView }).register(ctx);
  ctx.subscriptions.push(
    log, env, sessions, dashboards, heat, sessionsView, processesView, hotspotsView, tasksView,
    new StatusBar(sessions),
    vscode.window.registerTreeDataProvider('pyprof.sessions', sessionsView),
    vscode.window.registerTreeDataProvider('pyprof.processes', processesView),
    vscode.window.registerTreeDataProvider('pyprof.hotspots', hotspotsView),
    vscode.window.registerTreeDataProvider('pyprof.tasks', tasksView),
    vscode.window.registerCustomEditorProvider(ProfileEditorProvider.viewType, new ProfileEditorProvider(sessions, dashboards), {
      webviewOptions: { retainContextWhenHidden: true },
      supportsMultipleEditorsPerDocument: false,
    }),
    sessions.onDidStart((session) => {
      if (settings.openDashboardOnStart()) dashboards.open(session, vscode.ViewColumn.Beside);
      session.onDidDiscoverChildren((pids) => void followChildren(sessions, log, session, pids));
    }),
  );

  log.info('Python Profiler activated');
}

export function deactivate(): void {
  /* everything is disposed through ctx.subscriptions */
}

/** Offer to profile Python child processes (multiprocessing, workers) of a profiled program. */
async function followChildren(
  sessions: SessionManager,
  log: vscode.LogOutputChannel,
  parent: Session,
  pids: number[],
): Promise<void> {
  const python = parent.python;
  const mode = settings.followChildren();
  const fresh = pids.filter((pid) => !parent.knownChildPids.has(pid));
  if (mode === 'never' || !python || !fresh.length) return;
  fresh.forEach((pid) => parent.knownChildPids.add(pid));
  if (mode === 'ask') {
    const plural = fresh.length > 1 ? 'es' : '';
    const pick = await vscode.window.showInformationMessage(
      `"${parent.label}" started ${fresh.length} Python child process${plural} (${fresh.join(', ')}).`,
      'Profile Children',
      'Always',
    );
    if (!pick) return;
    if (pick === 'Always') await settings.alwaysFollowChildren();
  }
  for (const pid of fresh) {
    sessions
      .attach(pid, python, `${parent.label} › child ${pid}`)
      .catch((e) => log.warn(`child attach ${pid} failed: ${errorMessage(e)}`));
  }
}
