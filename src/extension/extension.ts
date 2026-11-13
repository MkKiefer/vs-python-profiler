import * as vscode from 'vscode';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { EnvironmentResolver } from './environment';
import { ExtPaths } from './paths';
import { Session, SessionManager } from './session';
import { LaunchAdapter } from './launch';
import { ProcessPicker, type ProcInfo } from './processes';
import { TerminalHub } from './terminalHub';
import { Dashboards, ProfileEditorProvider, openSource } from './dashboard';
import { EditorHeat } from './editorHeat';
import { HotspotsView, ProcessesView, SessionsView, StatusBar, TasksView } from './views';
import { toCollapsed, toSpeedscope } from '../shared/exporters';

export async function activate(ctx: vscode.ExtensionContext): Promise<void> {
  const log = vscode.window.createOutputChannel('Python Profiler', { log: true });
  const paths = new ExtPaths(ctx.extensionPath);
  ensureShimsExecutable(paths);
  const storage = path.join((ctx.storageUri ?? ctx.globalStorageUri).fsPath, 'profiles');
  const env = new EnvironmentResolver(log);
  const sessions = new SessionManager(paths, log, storage);
  const picker = new ProcessPicker(paths, env, sessions, log);
  const launcher = new LaunchAdapter(env, sessions, picker);
  launcher.register(ctx);

  const dashboards: Dashboards = new Dashboards(ctx, sessions, (cmd, s, args) => runSessionCommand(cmd, s, args));
  const heat = new EditorHeat(sessions, dashboards);
  const hub = new TerminalHub(ctx, paths, sessions, picker, log);
  hub.start().catch((e) => log.error(`terminal integration failed: ${e}`));

  const sessionsView = new SessionsView(sessions);
  const processesView = new ProcessesView(picker);
  ctx.subscriptions.push(
    log, env, sessions, dashboards, heat, hub,
    new StatusBar(sessions),
    vscode.window.registerTreeDataProvider('pyprof.sessions', sessionsView),
    vscode.window.registerTreeDataProvider('pyprof.processes', processesView),
    vscode.window.registerTreeDataProvider('pyprof.hotspots', new HotspotsView(sessions, dashboards)),
    vscode.window.registerTreeDataProvider('pyprof.tasks', new TasksView(sessions)),
    vscode.window.registerCustomEditorProvider(
      ProfileEditorProvider.viewType,
      new ProfileEditorProvider(sessions, dashboards),
      { webviewOptions: { retainContextWhenHidden: true }, supportsMultipleEditorsPerDocument: false },
    ),
  );

  // -------------------------------------------------- session lifecycle
  sessions.onDidStart((s) => {
    if (vscode.workspace.getConfiguration('pyprof').get('openDashboardOnStart', true)) {
      dashboards.open(s, vscode.ViewColumn.Beside);
    }
    s.onCollector('children', (p: { pids: number[] }) => void onChildren(s, p.pids));
  });

  async function onChildren(parent: Session, pids: number[]): Promise<void> {
    const mode = vscode.workspace.getConfiguration('pyprof').get<string>('followChildren', 'ask');
    if (mode === 'never' || !parent.python) return;
    const fresh = pids.filter((p) => !parent.childPids.has(p));
    fresh.forEach((p) => parent.childPids.add(p));
    if (!fresh.length) return;
    if (mode === 'ask') {
      const pick = await vscode.window.showInformationMessage(
        `"${parent.label}" started ${fresh.length} Python child process${fresh.length > 1 ? 'es' : ''} (${fresh.join(', ')}).`,
        'Profile Children',
        'Always',
      );
      if (!pick) return;
      if (pick === 'Always') {
        await vscode.workspace.getConfiguration('pyprof').update('followChildren', 'always', vscode.ConfigurationTarget.Global);
      }
    }
    for (const pid of fresh) {
      sessions
        .attach(pid, parent.python, `${parent.label} › child ${pid}`)
        .catch((e) => log.warn(`child attach ${pid} failed: ${e}`));
    }
  }

  // --------------------------------------------------------- helpers
  function sessionFrom(arg: unknown): Session | undefined {
    if (typeof arg === 'string') return sessions.sessions.find((s) => s.id === arg);
    if (arg && typeof arg === 'object' && 'session' in arg) return (arg as { session: Session }).session;
    return sessions.active;
  }

  function liveSession(arg: unknown): Session | undefined {
    const s = sessionFrom(arg);
    if (s?.live) return s;
    const live = sessions.sessions.find((x) => x.live);
    if (!live) vscode.window.showInformationMessage('No live profiling session.');
    return live;
  }

  async function runSessionCommand(cmd: string, s: Session, args: Record<string, unknown> = {}): Promise<void> {
    const client = s.client;
    const needLive = () => {
      if (!client?.alive || !s.live) throw new Error('This session is not live any more.');
      return client;
    };
    switch (cmd) {
      case 'stop':
        await sessions.stop(s, !!args.terminate);
        break;
      case 'snapshot': {
        if (!s.capabilities.tracemalloc) {
          await needLive().request('tracemalloc', { enabled: true });
          s.capabilities = { ...s.capabilities, tracemalloc: true };
          s.setState(s.state);
          vscode.window.showInformationMessage(
            'Memory tracing started (tracemalloc). Allocations from now on are tracked; take another snapshot later to compare.',
          );
        }
        await vscode.window.withProgress(
          { location: vscode.ProgressLocation.Window, title: 'Taking memory snapshot…' },
          () => needLive().request('snapshot', { label: args.label }, 180_000),
        );
        break;
      }
      case 'tracemalloc': {
        const enabled = args.enabled ?? !s.capabilities.tracemalloc;
        await needLive().request('tracemalloc', { enabled });
        s.capabilities = { ...s.capabilities, tracemalloc: !!enabled };
        s.setState(s.state);
        break;
      }
      case 'asyncioDebug': {
        const enabled = args.enabled ?? !s.capabilities.asyncioDebug;
        await needLive().request('asyncioDebug', {
          enabled,
          slowMs: vscode.workspace.getConfiguration('pyprof').get('asyncio.slowCallbackMs', 100),
        });
        s.capabilities = { ...s.capabilities, asyncioDebug: !!enabled };
        s.setState(s.state);
        break;
      }
      case 'objectCounts':
        await vscode.window.withProgress({ location: vscode.ProgressLocation.Window, title: 'Counting objects…' }, () =>
          needLive().request('objectCounts', {}, 180_000),
        );
        break;
      case 'mark': {
        const name = (args.name as string) ?? (await vscode.window.showInputBox({ prompt: 'Marker name', value: 'marker' }));
        if (name) await needLive().request('mark', { name });
        break;
      }
      case 'save':
        await saveAs(s);
        break;
      case 'exportSpeedscope':
      case 'exportCollapsed':
        await exportProfile(s, cmd === 'exportSpeedscope' ? 'speedscope' : 'collapsed');
        break;
      default:
        throw new Error(`unknown command ${cmd}`);
    }
  }

  async function saveAs(s: Session): Promise<void> {
    const ws = vscode.workspace.workspaceFolders?.[0]?.uri;
    const uri = await vscode.window.showSaveDialog({
      defaultUri: ws ? vscode.Uri.joinPath(ws, `${s.label.replace(/[^\w.-]+/g, '_')}.pyprof`) : undefined,
      filters: { 'Python profile': ['pyprof'] },
    });
    if (!uri) return;
    await sessions.saveAs(s, uri.fsPath);
    vscode.window.showInformationMessage(`Saved profile to ${uri.fsPath}`);
  }

  async function exportProfile(s: Session, kind?: 'speedscope' | 'collapsed'): Promise<void> {
    if (!kind) {
      const pick = await vscode.window.showQuickPick(
        [
          { label: 'speedscope (.speedscope.json)', format: 'speedscope' as const, detail: 'Open at speedscope.app' },
          { label: 'Collapsed stacks (.txt)', format: 'collapsed' as const, detail: 'flamegraph.pl, inferno, speedscope' },
        ],
        { title: 'Export profile' },
      );
      if (!pick) return;
      kind = pick.format;
    }
    const ext = kind === 'speedscope' ? 'speedscope.json' : 'collapsed.txt';
    const uri = await vscode.window.showSaveDialog({
      defaultUri: vscode.workspace.workspaceFolders?.[0]
        ? vscode.Uri.joinPath(vscode.workspace.workspaceFolders[0].uri, `${s.label.replace(/[^\w.-]+/g, '_')}.${ext}`)
        : undefined,
    });
    if (!uri) return;
    const content = kind === 'speedscope' ? JSON.stringify(toSpeedscope(s.model, s.label)) : toCollapsed(s.model);
    await fs.promises.writeFile(uri.fsPath, content);
    vscode.window.showInformationMessage(`Exported ${kind} profile to ${uri.fsPath}`);
  }

  const wrap =
    (fn: (...a: any[]) => unknown) =>
    async (...a: any[]) => {
      try {
        await fn(...a);
      } catch (e) {
        log.error(String((e as Error).stack ?? e));
        vscode.window.showErrorMessage(`Python Profiler: ${(e as Error).message ?? e}`);
      }
    };

  const reg = (id: string, fn: (...a: any[]) => unknown) => ctx.subscriptions.push(vscode.commands.registerCommand(id, wrap(fn)));

  // ---------------------------------------------------------- commands
  reg('pyprof.profileFile', (uri?: vscode.Uri) => launcher.profileFile(uri));
  reg('pyprof.profileConfiguration', () => launcher.profileConfiguration());
  reg('pyprof.profileTest', () => launcher.profileTest());
  reg('pyprof.attach', () => picker.pickAndAttach());
  reg('pyprof.attachProcess', (p: ProcInfo) => picker.attach(p));
  ctx.subscriptions.push(vscode.commands.registerCommand('pyprof.pickProcess', () => picker.pickPid()));
  reg('pyprof.refreshProcesses', () => processesView.refresh());
  reg('pyprof.stop', (arg) => {
    const s = liveSession(arg);
    return s && sessions.stop(s);
  });
  reg('pyprof.stopAndTerminate', (arg) => {
    const s = liveSession(arg);
    return s && sessions.stop(s, true);
  });
  reg('pyprof.openDashboard', (arg) => {
    const s = sessionFrom(arg) ?? sessions.sessions[0];
    if (!s) return vscode.window.showInformationMessage('No profiling session yet. Use "Profile Python File" first.');
    dashboards.open(s);
  });
  reg('pyprof.selectSession', (id: string) => {
    const s = sessionFrom(id);
    if (!s) return;
    sessions.setActive(s);
    dashboards.open(s);
  });
  reg('pyprof.snapshot', (arg) => {
    const s = liveSession(arg);
    return s && runSessionCommand('snapshot', s);
  });
  reg('pyprof.toggleTracemalloc', (arg) => {
    const s = liveSession(arg);
    return s && runSessionCommand('tracemalloc', s);
  });
  reg('pyprof.toggleAsyncioDebug', (arg) => {
    const s = liveSession(arg);
    return s && runSessionCommand('asyncioDebug', s);
  });
  reg('pyprof.mark', (arg) => {
    const s = liveSession(arg);
    return s && runSessionCommand('mark', s);
  });
  reg('pyprof.toggleHeat', () => heat.toggle());
  reg('pyprof.openProfile', async () => {
    const uris = await vscode.window.showOpenDialog({ filters: { 'Python profile': ['pyprof'] }, canSelectMany: false });
    if (uris?.[0]) await vscode.commands.executeCommand('vscode.openWith', uris[0], ProfileEditorProvider.viewType);
  });
  reg('pyprof.saveProfile', (arg) => {
    const s = sessionFrom(arg);
    return s && saveAs(s);
  });
  reg('pyprof.export', (arg) => {
    const s = sessionFrom(arg);
    return s && exportProfile(s);
  });
  reg('pyprof.deleteSession', async (node: { file?: string; session?: Session }) => {
    const file = node?.file ?? node?.session?.filePath;
    if (!file) return;
    const ok = await vscode.window.showWarningMessage(`Delete ${path.basename(file)}?`, { modal: true }, 'Delete');
    if (ok) sessions.deleteSaved(file);
  });
  reg('pyprof.revealFunction', async (id: string, fn: number, openFile?: boolean) => {
    const s = sessionFrom(id);
    if (!s) return;
    if (openFile) {
      const f = s.model.fns[fn];
      if (f) await openSource(f.file, f.minLine);
    }
    dashboards.revealFunction(s, fn);
  });

  vscode.commands.executeCommand('setContext', 'pyprof.hasLiveSession', false);
  log.info('Python Profiler activated');
}

export function deactivate(): void {
  /* disposables handle cleanup */
}

/** VSIX packaging may drop the executable bit on the POSIX shim. */
function ensureShimsExecutable(paths: ExtPaths): void {
  if (process.platform === 'win32') return;
  try {
    fs.chmodSync(path.join(paths.bin, 'pyprof'), 0o755);
  } catch {
    /* read-only install */
  }
}
