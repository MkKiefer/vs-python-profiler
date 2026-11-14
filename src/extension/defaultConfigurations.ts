/** Asks which ready-made profile configuration to use and for the one detail it needs, like the Python debugger. */
import * as vscode from 'vscode';
import {
  DEFAULT_CONFIGURATION_CHOICES,
  defaultConfiguration,
  uvicornTarget,
  type DefaultConfigurationChoice,
  type DefaultConfigurationKind,
} from './launchConfig';

const EXCLUDE = '**/{node_modules,.venv,venv,.git,site-packages}/**';

export class DefaultConfigurationPicker {
  /** Quick pick items for every default configuration. */
  items(): (vscode.QuickPickItem & DefaultConfigurationChoice)[] {
    return DEFAULT_CONFIGURATION_CHOICES.map((choice) => ({ ...choice, label: `$(play) ${choice.label}` }));
  }

  /** Show the defaults; undefined when the user cancels. */
  async pick(folder: vscode.WorkspaceFolder | undefined): Promise<vscode.DebugConfiguration | undefined> {
    const choice = await vscode.window.showQuickPick(this.items(), {
      title: 'Select a profile configuration',
      matchOnDescription: true,
    });
    return choice ? this.complete(choice.id, folder) : undefined;
  }

  /** Ask for whatever the kind needs and build the configuration; undefined when the user cancels. */
  async complete(
    kind: DefaultConfigurationKind,
    folder: vscode.WorkspaceFolder | undefined,
  ): Promise<vscode.DebugConfiguration | undefined> {
    const detail = await this.detail(kind, folder);
    if (detail === undefined) return undefined;
    const config = defaultConfiguration(kind, detail);
    return { name: String(config.name), type: String(config.type), request: String(config.request), ...config };
  }

  private async detail(kind: DefaultConfigurationKind, folder: vscode.WorkspaceFolder | undefined): Promise<string | undefined> {
    switch (kind) {
      case 'module':
        return this.ask('Module to profile', 'Run with python -m, e.g. mypackage.cli', '');
      case 'fastapi': {
        const main = await this.find(folder, 'main.py');
        return this.ask('FastAPI app', 'uvicorn target as module:variable', main ? uvicornTarget(main) : 'main:app');
      }
      case 'django':
        return this.ask(
          'Path to manage.py',
          'Relative to the workspace folder',
          (await this.find(folder, 'manage.py')) ?? 'manage.py',
        );
      default:
        return '';
    }
  }

  private async ask(title: string, prompt: string, value: string): Promise<string | undefined> {
    const answer = await vscode.window.showInputBox({
      title,
      prompt,
      value,
      validateInput: (text) => (text.trim() ? undefined : 'Enter a value'),
    });
    return answer?.trim();
  }

  /** The shallowest `name` in the folder, relative to it. */
  private async find(folder: vscode.WorkspaceFolder | undefined, name: string): Promise<string | undefined> {
    if (!folder) return undefined;
    const found = await vscode.workspace.findFiles(new vscode.RelativePattern(folder, `**/${name}`), EXCLUDE, 20);
    const paths = found.map((uri) => vscode.workspace.asRelativePath(uri, false));
    return paths.sort((a, b) => a.split('/').length - b.split('/').length || a.localeCompare(b))[0];
  }
}
