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
import { EnvironmentResolver } from './environment';
import { parseDotEnv } from './dotenv';
import { pytestNodeId, splitArgs } from './launch.pure';
import type { SessionManager, LaunchSpec } from './session';
import type { ProcessPicker } from './processes';
import type { CollectorOptions } from '../shared/protocol';

export const DEBUG_TYPE = 'python-profiler';
const PYTHON_DEBUG_TYPES = new Set(['debugpy', 'python']);

export class LaunchAdapter implements vscode.DebugConfigurationProvider {
  constructor(
    private readonly env: EnvironmentResolver,
    private readonly sessions: SessionManager,
    private readonly picker: ProcessPicker,
  ) {}

  register(ctx: vscode.ExtensionContext): void {
    ctx.subscriptions.push(
      vscode.debug.registerDebugConfigurationProvider(DEBUG_TYPE, this),
      vscode.debug.registerDebugConfigurationProvider(
        DEBUG_TYPE,
        {
          provideDebugConfigurations: () => [
            { name: 'Profile: Current File', type: DEBUG_TYPE, request: 'launch', program: '${file}' },
          ],
        },
        vscode.DebugConfigurationProviderTriggerKind.Dynamic,
      ),
    );
  }

  provideDebugConfigurations(): vscode.DebugConfiguration[] {
    return [{ name: 'Profile: Current File', type: DEBUG_TYPE, request: 'launch', program: '${file}' }];
  }

  resolveDebugConfiguration(
    _folder: vscode.WorkspaceFolder | undefined,
    config: vscode.DebugConfiguration,
  ): vscode.DebugConfiguration | undefined {
    // F5 with no launch.json
    if (!config.type && !config.request && !config.name) {
      const editor = vscode.window.activeTextEditor;
      if (editor?.document.languageId !== 'python') return undefined;
      return { name: 'Profile: Current File', type: DEBUG_TYPE, request: 'launch', program: '${file}' };
    }
    return config;
  }

  async resolveDebugConfigurationWithSubstitutedVariables(
    folder: vscode.WorkspaceFolder | undefined,
    config: vscode.DebugConfiguration,
  ): Promise<undefined> {
    try {
      if (config.request === 'attach') await this.attachFromConfig(config);
      else await this.launchFromConfig(folder, config);
    } catch (e) {
      vscode.window.showErrorMessage(`Python Profiler: ${(e as Error).message ?? e}`);
    }
    return undefined; // never start a debug adapter
  }

  private async attachFromConfig(config: vscode.DebugConfiguration): Promise<void> {
    const pid = Number(config.processId ?? config.pid);
    if (!pid) {
      await this.picker.pickAndAttach();
      return;
    }
    await this.picker.attachPid(pid, profileOptions(config.profile));
  }

  private async launchFromConfig(folder: vscode.WorkspaceFolder | undefined, config: vscode.DebugConfiguration): Promise<void> {
    const resource = config.program ? vscode.Uri.file(config.program) : folder?.uri;
    const python = await this.env.ensureSupported(resource, config.python || config.pythonPath || undefined);
    if (!python) return;
    if (!config.program && !config.module) throw new Error('launch configuration needs "program" or "module"');
    const cwd = config.cwd || folder?.uri.fsPath || (config.program ? path.dirname(config.program) : undefined);

    const base = await this.env.environmentVariables(resource);
    let env: Record<string, string> = { ...base };
    if (config.envFile && fs.existsSync(config.envFile)) {
      env = { ...env, ...parseDotEnv(fs.readFileSync(config.envFile, 'utf8'), { ...process.env, ...env }) };
    }
    if (config.env) for (const [k, v] of Object.entries(config.env)) if (v !== null) env[k] = String(v);

    const args = Array.isArray(config.args) ? config.args.map(String) : config.args ? splitArgs(String(config.args)) : [];
    const spec: LaunchSpec = {
      python,
      kind: config.module ? 'module' : 'path',
      target: config.module || config.program,
      args,
      cwd,
      env,
      label: config.__label || (config.module ? `-m ${config.module}` : path.basename(config.program)),
      options: this.sessions.defaultOptions(resource, profileOptions(config.profile)),
    };
    await this.sessions.launch(spec);
  }

  // ------------------------------------------------------------- commands
  async profileFile(uri?: vscode.Uri): Promise<void> {
    const target = uri ?? vscode.window.activeTextEditor?.document.uri;
    if (!target || !target.fsPath.endsWith('.py')) {
      vscode.window.showWarningMessage('Open a Python file to profile.');
      return;
    }
    const doc = vscode.workspace.textDocuments.find((d) => d.uri.toString() === target.toString());
    if (doc?.isDirty) await doc.save();
    const folder = vscode.workspace.getWorkspaceFolder(target);
    await vscode.debug.startDebugging(folder, {
      name: `Profile: ${path.basename(target.fsPath)}`,
      type: DEBUG_TYPE,
      request: 'launch',
      program: target.fsPath,
      cwd: folder?.uri.fsPath ?? path.dirname(target.fsPath),
    });
  }

  async profileConfiguration(): Promise<void> {
    type Item = vscode.QuickPickItem & { folder?: vscode.WorkspaceFolder; config: vscode.DebugConfiguration };
    const items: Item[] = [];
    const folders = vscode.workspace.workspaceFolders ?? [];
    for (const folder of folders) {
      const configs = vscode.workspace.getConfiguration('launch', folder).get<vscode.DebugConfiguration[]>('configurations') ?? [];
      for (const config of configs) {
        if (!PYTHON_DEBUG_TYPES.has(config.type) && config.type !== DEBUG_TYPE) continue;
        const what = config.module ? `-m ${config.module}` : config.program ?? (config.request === 'attach' ? 'attach' : '');
        items.push({
          label: `$(debug-alt) ${config.name}`,
          description: `${config.type} · ${what} ${Array.isArray(config.args) ? config.args.join(' ') : config.args ?? ''}`,
          detail: folders.length > 1 ? folder.name : undefined,
          folder,
          config,
        });
      }
    }
    if (!items.length) {
      const pick = await vscode.window.showInformationMessage(
        'No Python launch configurations found in launch.json.',
        'Profile Current File',
        'Add Configuration',
      );
      if (pick === 'Profile Current File') await this.profileFile();
      else if (pick) await vscode.commands.executeCommand('debug.addConfiguration');
      return;
    }
    const pick = await vscode.window.showQuickPick(items, {
      title: 'Profile a launch configuration',
      placeHolder: 'Your existing debug configurations run unchanged, with the profiler instead of the debugger',
      matchOnDescription: true,
    });
    if (!pick) return;
    const { config, folder } = pick;
    if (config.request === 'attach' && !config.processId) {
      vscode.window.showWarningMessage(
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

  async profileTest(): Promise<void> {
    const editor = vscode.window.activeTextEditor;
    if (!editor || editor.document.languageId !== 'python') return;
    const nodeId = pytestNodeId(editor.document, editor.selection.active.line);
    const folder = vscode.workspace.getWorkspaceFolder(editor.document.uri);
    const rel = folder ? path.relative(folder.uri.fsPath, editor.document.uri.fsPath) : editor.document.uri.fsPath;
    const id = nodeId ? `${rel}::${nodeId}` : rel;
    if (editor.document.isDirty) await editor.document.save();
    await vscode.debug.startDebugging(folder, {
      name: `Profile: ${id}`,
      type: DEBUG_TYPE,
      request: 'launch',
      module: 'pytest',
      args: [id.split(path.sep).join('/'), '-q', '-p', 'no:cacheprovider'],
      cwd: folder?.uri.fsPath,
      __label: `pytest ${nodeId ?? rel}`,
    });
  }
}

function profileOptions(p: any): CollectorOptions & { inject?: boolean } {
  if (!p) return {};
  return {
    rateHz: p.rateHz,
    tracemalloc: p.memory,
    asyncioDebug: p.asyncioDebug,
    native: p.native,
    inject: p.inject,
  };
}
