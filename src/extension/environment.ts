/**
 * EnvironmentResolver – we never manage environments ourselves.
 *
 * Interpreter selection, venv/uv/poetry/conda discovery and `.env` files are
 * owned by the Python extension; we read its choice per resource (multi-root
 * aware) and only add a version gate (Tachyon needs 3.15+).
 */
import * as vscode from 'vscode';
import { execFile } from 'node:child_process';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { PythonExtension } from '@vscode/python-extension';

export const MIN_MAJOR = 3;
export const MIN_MINOR = 15;

export interface PythonInfo {
  executable: string;
  version: string;
  major: number;
  minor: number;
  freeThreaded: boolean;
  /** human label, e.g. ".venv (3.15.2)" */
  label: string;
  envPath?: string;
}

export class EnvironmentResolver implements vscode.Disposable {
  private api: PythonExtension | undefined;
  private apiTried = false;
  private probeCache = new Map<string, Promise<PythonInfo | undefined>>();
  private readonly changed = new vscode.EventEmitter<void>();
  readonly onDidChange = this.changed.event;
  private disposables: vscode.Disposable[] = [];

  constructor(private readonly log: vscode.LogOutputChannel) {}

  private async getApi(): Promise<PythonExtension | undefined> {
    if (this.apiTried) return this.api;
    this.apiTried = true;
    try {
      this.api = await PythonExtension.api();
      this.disposables.push(
        this.api.environments.onDidChangeActiveEnvironmentPath(() => this.changed.fire()),
      );
    } catch (e) {
      this.log.warn(`Python extension API unavailable, falling back to settings/PATH: ${e}`);
    }
    return this.api;
  }

  /** The interpreter the user selected for this file/folder. */
  async resolve(resource?: vscode.Uri): Promise<PythonInfo | undefined> {
    const api = await this.getApi();
    const candidates: string[] = [];
    if (api) {
      try {
        const envPath = api.environments.getActiveEnvironmentPath(resource);
        const env = await api.environments.resolveEnvironment(envPath);
        const exe = env?.executable.uri?.fsPath ?? envPath.path;
        if (exe) candidates.push(exe);
      } catch (e) {
        this.log.warn(`resolveEnvironment failed: ${e}`);
      }
    }
    const setting = vscode.workspace.getConfiguration('pyprof', resource).get<string>('pythonPath');
    if (setting) candidates.push(setting);
    candidates.push(process.platform === 'win32' ? 'python' : 'python3', 'python');
    for (const c of candidates) {
      const info = await this.probe(c);
      if (info) return info;
    }
    return undefined;
  }

  /** Run the interpreter once to learn its exact version/build (cached). */
  probe(executable: string): Promise<PythonInfo | undefined> {
    let p = this.probeCache.get(executable);
    if (!p) {
      p = new Promise((resolve) => {
        const code =
          'import sys,json,sysconfig;print(json.dumps({"v":sys.version.split()[0],"M":sys.version_info[0],' +
          '"m":sys.version_info[1],"ft":bool(sysconfig.get_config_var("Py_GIL_DISABLED")),"exe":sys.executable,' +
          '"prefix":sys.prefix,"venv":sys.prefix!=sys.base_prefix}))';
        execFile(executable, ['-I', '-c', code], { timeout: 15000, windowsHide: true }, (err, stdout) => {
          if (err) {
            resolve(undefined);
            return;
          }
          try {
            const r = JSON.parse(stdout.trim());
            const envName = r.venv ? path.basename(r.prefix) : undefined;
            resolve({
              executable: isAbsolute(executable) ? executable : r.exe,
              version: r.v,
              major: r.M,
              minor: r.m,
              freeThreaded: r.ft,
              label: `${envName ?? 'Python'} ${r.v}${r.ft ? 't' : ''}`,
              envPath: r.venv ? r.prefix : undefined,
            });
          } catch {
            resolve(undefined);
          }
        });
      });
      this.probeCache.set(executable, p);
      p.then((v) => {
        if (!v) this.probeCache.delete(executable);
      });
    }
    return p;
  }

  isSupported(info: PythonInfo): boolean {
    return info.major > MIN_MAJOR || (info.major === MIN_MAJOR && info.minor >= MIN_MINOR);
  }

  /**
   * Resolve + version gate. Shows actionable guidance instead of failing
   * silently when the selected interpreter is too old.
   */
  async ensureSupported(resource?: vscode.Uri, explicit?: string): Promise<PythonInfo | undefined> {
    const info = explicit ? await this.probe(explicit) : await this.resolve(resource);
    if (!info) {
      const pick = await vscode.window.showErrorMessage(
        'No Python interpreter found. Select one with the Python extension first.',
        'Select Interpreter',
      );
      if (pick) await vscode.commands.executeCommand('python.setInterpreter');
      return undefined;
    }
    if (this.isSupported(info)) return info;
    const want = `${MIN_MAJOR}.${MIN_MINOR}`;
    const actions = ['Select Interpreter', `Create ${want} venv`, 'Learn More'];
    const pick = await vscode.window.showWarningMessage(
      `Profiling needs Python ${want}+ (Tachyon). The selected interpreter is ${info.label} (${info.executable}).`,
      ...actions,
    );
    if (pick === actions[0]) await vscode.commands.executeCommand('python.setInterpreter');
    else if (pick === actions[1]) await this.createVenv(resource);
    else if (pick === actions[2])
      vscode.env.openExternal(vscode.Uri.parse('https://docs.python.org/3.15/library/profiling.sampling.html'));
    return undefined;
  }

  private async createVenv(resource?: vscode.Uri): Promise<void> {
    const folder = resource ? vscode.workspace.getWorkspaceFolder(resource) : vscode.workspace.workspaceFolders?.[0];
    const want = `${MIN_MAJOR}.${MIN_MINOR}`;
    const hasUv = await which('uv');
    const term = vscode.window.createTerminal({ name: `Create Python ${want} venv`, cwd: folder?.uri });
    term.show();
    if (hasUv) {
      term.sendText(`uv venv -p ${want} .venv`);
    } else if (process.platform === 'win32') {
      term.sendText(`py -${want} -m venv .venv`);
    } else {
      term.sendText(`python${want} -m venv .venv`);
    }
    vscode.window.showInformationMessage(
      `Creating .venv with Python ${want}${hasUv ? ' via uv' : ''}. Select it afterwards with "Python: Select Interpreter".`,
    );
  }

  /** Environment variables the Python extension uses for this resource (.env included). */
  async environmentVariables(resource?: vscode.Uri): Promise<Record<string, string>> {
    const api = await this.getApi();
    const out: Record<string, string> = {};
    try {
      const vars = api?.environments.getEnvironmentVariables(resource);
      if (vars) for (const [k, v] of Object.entries(vars)) if (v !== undefined) out[k] = v;
    } catch {
      /* ignore */
    }
    return out;
  }

  dispose(): void {
    this.disposables.forEach((d) => d.dispose());
    this.changed.dispose();
  }
}

function isAbsolute(p: string): boolean {
  return path.isAbsolute(p);
}

export function which(cmd: string): Promise<string | undefined> {
  const exts = process.platform === 'win32' ? (process.env.PATHEXT ?? '.EXE;.CMD;.BAT').split(';') : [''];
  for (const dir of (process.env.PATH ?? '').split(path.delimiter)) {
    for (const ext of exts) {
      const full = path.join(dir, cmd + ext.toLowerCase());
      try {
        fs.accessSync(full, fs.constants.X_OK);
        return Promise.resolve(full);
      } catch {
        /* next */
      }
    }
  }
  return Promise.resolve(undefined);
}

export { parseDotEnv } from './dotenv';
