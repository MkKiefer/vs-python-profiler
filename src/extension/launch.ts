/**
 * LaunchAdapter: turns everything users already have into a LaunchSpec.
 *
 * - "Profile Python File"            → active interpreter + ${file}
 * - existing debugpy launch configs → same program/module/args/env/envFile/cwd/python
 * - our own `python-profiler` type  → same fields + `profile` options
 * - "Profile Test at Cursor"        → python -m pytest <nodeid>
 *
 * Variable substitution (${workspaceFolder}, ${file}, ${command:…}) is done by
 * VS Code itself: we route every config through `startDebugging` and pick it
 * up in `resolveDebugConfigurationWithSubstitutedVariables`, returning
 * `undefined` so no debug adapter is ever started.
 */
import * as vscode from 'vscode';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { DefaultConfigurationPicker } from './defaultConfigurations';
import { parseDotEnv } from './dotenv';
import type { EnvironmentResolver } from './environment';
import { parseLaunchConfig, pytestNodeId, type DefaultConfigurationKind, type LaunchConfig } from './launchConfig';
import type { ProcessPicker } from './processes';
import type { SessionManager } from './sessionManager';
import { settings } from './settings';
import { errorMessage } from '../shared/errors';

export const DEBUG_TYPE = 'python-profiler';
const PYTHON_DEBUG_TYPES: ReadonlySet<string> = new Set(['debugpy', 'python', DEBUG_TYPE]);

const CURRENT_FILE_CONFIG: vscode.DebugConfiguration = {
  name: 'Profile: Current File',
  type: DEBUG_TYPE,
  request: 'launch',
  program: '${file}',
};

/** A quick pick entry that knows what to do when chosen. */
type ActionItem = vscode.QuickPickItem & { run?: () => Promise<void> };

const isPythonFile = (uri: vscode.Uri): boolean => uri.scheme === 'file' && uri.fsPath.endsWith('.py');

/**
 * The Python file the user means by "current file". A dashboard or a saved .pyprof
 * opened from the Sessions view takes focus, leaving no active text editor, so fall
 * back to a Python file that is still visible, then to the open Python tabs.
 */
function currentPythonFile(): vscode.Uri | undefined {
  const active = vscode.window.activeTextEditor?.document.uri;
  if (active && isPythonFile(active)) return active;
  const visible = vscode.window.visibleTextEditors.find((e) => isPythonFile(e.document.uri));
  if (visible) return visible.document.uri;
  const groups = vscode.window.tabGroups;
  const ordered = [groups.activeTabGroup, ...groups.all.filter((g) => g !== groups.activeTabGroup)];
  for (const group of ordered) {
    const tabs = [group.activeTab, ...group.tabs].filter((t): t is vscode.Tab => t !== undefined);
    for (const tab of tabs) {
      if (tab.input instanceof vscode.TabInputText && isPythonFile(tab.input.uri)) return tab.input.uri;
    }
  }
  return undefined;
}

export class LaunchAdapter implements vscode.DebugConfigurationProvider {
  constructor(
    private readonly env: EnvironmentResolver,
    private readonly sessions: SessionManager,
    private readonly picker: ProcessPicker,
    private readonly defaults = new DefaultConfigurationPicker(),
  ) {}

  register(ctx: vscode.ExtensionContext): void {
    ctx.subscriptions.push(
      vscode.debug.registerDebugConfigurationProvider(DEBUG_TYPE, this),
      vscode.debug.registerDebugConfigurationProvider(
        DEBUG_TYPE,
        { provideDebugConfigurations: () => [CURRENT_FILE_CONFIG] },
        vscode.DebugConfigurationProviderTriggerKind.Dynamic,
      ),
    );
  }

  /** Creating launch.json: ask which default to start with, like the Python debugger does. */
  async provideDebugConfigurations(folder: vscode.WorkspaceFolder | undefined): Promise<vscode.DebugConfiguration[]> {
    const config = await this.defaults.pick(folder);
    return config ? [config] : [];
  }

  resolveDebugConfiguration(
    _folder: vscode.WorkspaceFolder | undefined,
    config: vscode.DebugConfiguration,
  ): vscode.DebugConfiguration | undefined {
    // F5 with no launch.json: VS Code passes an empty configuration
    if (!config.type && !config.request && !config.name) {
      return vscode.window.activeTextEditor?.document.languageId === 'python' ? CURRENT_FILE_CONFIG : undefined;
    }
    return config;
  }

  async resolveDebugConfigurationWithSubstitutedVariables(
    folder: vscode.WorkspaceFolder | undefined,
    config: vscode.DebugConfiguration,
  ): Promise<undefined> {
    try {
      const parsed = parseLaunchConfig(config);
      if (parsed.request === 'attach') await this.attachFromConfig(parsed);
      else await this.launchFromConfig(folder, parsed);
    } catch (e) {
      void vscode.window.showErrorMessage(`Python Profiler: ${errorMessage(e)}`);
    }
    return undefined; // never start a debug adapter
  }

  private async attachFromConfig(config: LaunchConfig): Promise<void> {
    if (config.processId) await this.picker.attachPid(config.processId, config.profile);
    else await this.picker.pickAndAttach();
  }

  private async launchFromConfig(folder: vscode.WorkspaceFolder | undefined, config: LaunchConfig): Promise<void> {
    const target = config.module ?? config.program;
    if (!target) throw new Error('launch configuration needs "program" or "module"');
    const resource = config.program ? vscode.Uri.file(config.program) : folder?.uri;
    const python = await this.env.ensureSupported(resource, config.python);
    if (!python) return;
    const { inject: _attachOnly, ...profile } = config.profile;
    await this.sessions.launch({
      python,
      kind: config.module ? 'module' : 'path',
      target,
      args: config.args,
      cwd: config.cwd ?? folder?.uri.fsPath ?? (config.program ? path.dirname(config.program) : undefined),
      env: await this.environment(resource, config),
      label: config.label ?? (config.module ? `-m ${config.module}` : path.basename(target)),
      options: settings.collectorOptions(resource, profile),
    });
  }

  /** Python extension variables (.env included) < the config's envFile < the config's env. */
  private async environment(resource: vscode.Uri | undefined, config: LaunchConfig): Promise<Record<string, string>> {
    let env = await this.env.environmentVariables(resource);
    if (config.envFile && fs.existsSync(config.envFile)) {
      const content = await fs.promises.readFile(config.envFile, 'utf8');
      env = { ...env, ...parseDotEnv(content, { ...process.env, ...env }) };
    }
    return { ...env, ...config.env };
  }

  // ------------------------------------------------------------- commands
  /**
   * `arg` is whatever the invoking menu passes: a file Uri from the explorer or an editor, but a tree node from
   * the Sessions view toolbar and nothing (or a non-file Uri) from other places, so only a Python file Uri counts.
   */
  async profileFile(arg?: unknown): Promise<void> {
    const target = arg instanceof vscode.Uri && isPythonFile(arg) ? arg : currentPythonFile();
    if (!target) {
      void vscode.window.showWarningMessage('Open a Python file to profile.');
      return;
    }
    const document = vscode.workspace.textDocuments.find((d) => d.uri.toString() === target.toString());
    if (document?.isDirty) await document.save();
    const folder = vscode.workspace.getWorkspaceFolder(target);
    await vscode.debug.startDebugging(folder, {
      name: `Profile: ${path.basename(target.fsPath)}`,
      type: DEBUG_TYPE,
      request: 'launch',
      program: target.fsPath,
      cwd: folder?.uri.fsPath ?? path.dirname(target.fsPath),
    });
  }

  /**
   * Pick one of the user's existing launch.json configurations, or a default one (Python file, module, FastAPI,
   * Django, pytest, attach), and run it under the profiler.
   */
  async profileConfiguration(): Promise<void> {
    const existing = this.launchConfigurationItems();
    const items: ActionItem[] = [
      ...(existing.length ? [{ label: 'launch.json', kind: vscode.QuickPickItemKind.Separator }, ...existing] : []),
      { label: 'Default configurations', kind: vscode.QuickPickItemKind.Separator },
      ...this.defaults.items().map((choice) => ({ ...choice, run: () => this.profileDefault(choice.id) })),
      { label: '', kind: vscode.QuickPickItemKind.Separator },
      {
        label: '$(add) Add Configuration…',
        description: 'Save a profile configuration to launch.json',
        run: async () => {
          await vscode.commands.executeCommand('debug.addConfiguration');
        },
      },
    ];
    const pick = await vscode.window.showQuickPick(items, {
      title: 'Profile a launch configuration',
      placeHolder: existing.length
        ? 'Your existing debug configurations run unchanged, with the profiler instead of the debugger'
        : 'No Python launch configurations in launch.json yet: pick a default one',
      matchOnDescription: true,
    });
    await pick?.run?.();
  }

  private async profileDefault(kind: DefaultConfigurationKind): Promise<void> {
    if (kind === 'file') return this.profileFile();
    const editorUri = vscode.window.activeTextEditor?.document.uri;
    const folder = (editorUri && vscode.workspace.getWorkspaceFolder(editorUri)) ?? vscode.workspace.workspaceFolders?.[0];
    const config = await this.defaults.complete(kind, folder);
    if (config) await vscode.debug.startDebugging(folder, config);
  }

  private async profileExisting(folder: vscode.WorkspaceFolder, config: vscode.DebugConfiguration): Promise<void> {
    const parsed = parseLaunchConfig(config);
    if (parsed.request === 'attach' && !parsed.processId) {
      void vscode.window.showWarningMessage(
        `"${config.name}" attaches via debugpy (host/port); use "Attach Profiler to Process…" to pick the process instead.`,
      );
      return;
    }
    await vscode.debug.startDebugging(folder, {
      ...config,
      type: DEBUG_TYPE,
      name: `Profile: ${config.name}`,
      __label: config.name,
    });
  }

  private launchConfigurationItems(): ActionItem[] {
    const folders = vscode.workspace.workspaceFolders ?? [];
    const items: ActionItem[] = [];
    for (const folder of folders) {
      const configs =
        vscode.workspace.getConfiguration('launch', folder).get<vscode.DebugConfiguration[]>('configurations') ?? [];
      for (const config of configs) {
        if (!PYTHON_DEBUG_TYPES.has(config.type)) continue;
        const parsed = parseLaunchConfig(config);
        const what = parsed.module ? `-m ${parsed.module}` : (parsed.program ?? parsed.request);
        items.push({
          label: `$(debug-alt) ${config.name}`,
          description: [config.type, [what, ...parsed.args].join(' ')].join(' · '),
          detail: folders.length > 1 ? folder.name : undefined,
          run: () => this.profileExisting(folder, config),
        });
      }
    }
    return items;
  }

  async profileTest(): Promise<void> {
    const editor = vscode.window.activeTextEditor;
    if (editor?.document.languageId !== 'python') return;
    const document = editor.document;
    const folder = vscode.workspace.getWorkspaceFolder(document.uri);
    const file = folder ? path.relative(folder.uri.fsPath, document.uri.fsPath) : document.uri.fsPath;
    const test = pytestNodeId(document, editor.selection.active.line);
    const nodeId = (test ? `${file}::${test}` : file).split(path.sep).join('/');
    if (document.isDirty) await document.save();
    await vscode.debug.startDebugging(folder, {
      name: `Profile: ${nodeId}`,
      type: DEBUG_TYPE,
      request: 'launch',
      module: 'pytest',
      args: [nodeId, '-q', '-p', 'no:cacheprovider'],
      cwd: folder?.uri.fsPath,
      __label: `pytest ${test ?? file}`,
    });
  }
}
