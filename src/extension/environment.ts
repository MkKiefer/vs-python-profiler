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
import { settings } from './settings';
import { errorMessage } from '../shared/errors';

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

/** What the probe script prints (see `PROBE_SCRIPT`). */
interface ProbeResult {
  version: string;
  major: number;
  minor: number;
  freeThreaded: boolean;
  executable: string;
  prefix: string;
  inVenv: boolean;
}

const PROBE_SCRIPT =
  'import sys,json,sysconfig;print(json.dumps({"version":sys.version.split()[0],"major":sys.version_info[0],' +
  '"minor":sys.version_info[1],"freeThreaded":bool(sysconfig.get_config_var("Py_GIL_DISABLED")),' +
  '"executable":sys.executable,"prefix":sys.prefix,"inVenv":sys.prefix!=sys.base_prefix}))';
const PROBE_TIMEOUT_MS = 15_000;
const MIN_VERSION = `${MIN_MAJOR}.${MIN_MINOR}`;

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
      this.log.warn(`Python extension API unavailable, falling back to settings/PATH: ${errorMessage(e)}`);
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
        this.log.warn(`resolveEnvironment failed: ${errorMessage(e)}`);
      }
    }
    const setting = settings.pythonPath(resource);
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
      p = this.runProbe(executable);
      this.probeCache.set(executable, p);
      // failures are not cached: the interpreter may be installed or repaired later
      void p.then((info) => {
        if (!info) this.probeCache.delete(executable);
      });
    }
    return p;
  }

  private runProbe(executable: string): Promise<PythonInfo | undefined> {
    return new Promise((resolve) => {
      const options = { timeout: PROBE_TIMEOUT_MS, windowsHide: true };
      execFile(executable, ['-I', '-c', PROBE_SCRIPT], options, (err, stdout) => {
        if (err) {
          resolve(undefined);
          return;
        }
        try {
          const r = JSON.parse(stdout.trim()) as ProbeResult;
          resolve({
            executable: path.isAbsolute(executable) ? executable : r.executable,
            version: r.version,
            major: r.major,
            minor: r.minor,
            freeThreaded: r.freeThreaded,
            label: `${r.inVenv ? path.basename(r.prefix) : 'Python'} ${r.version}${r.freeThreaded ? 't' : ''}`,
            envPath: r.inVenv ? r.prefix : undefined,
          });
        } catch {
          resolve(undefined);
        }
      });
    });
  }

  isSupported(info: PythonInfo): boolean {
    return info.major > MIN_MAJOR || (info.major === MIN_MAJOR && info.minor >= MIN_MINOR);
  }

  /**
   * Resolve + version gate. Shows actionable guidance instead of failing
   * silently when the selected interpreter is too old; after the user selects
   * another interpreter, checks again so the launch goes ahead with it.
   */
  async ensureSupported(resource?: vscode.Uri, explicit?: string): Promise<PythonInfo | undefined> {
    for (;;) {
      const info = explicit ? await this.probe(explicit) : await this.resolve(resource);
      if (info && this.isSupported(info)) return info;
      const selected = info ? await this.offerSupported(info, resource, explicit) : await this.offerInterpreter();
      if (!selected) return undefined;
    }
  }

  /** True when the user selected another interpreter, so it is worth checking again. */
  private async offerInterpreter(): Promise<boolean> {
    const pick = await vscode.window.showErrorMessage(
      'No Python interpreter found. Select one with the Python extension first.',
      'Select Interpreter',
    );
    if (!pick) return false;
    await vscode.commands.executeCommand('python.setInterpreter');
    return true;
  }

  /** True when the user selected another interpreter, so it is worth checking again. */
  private async offerSupported(info: PythonInfo, resource?: vscode.Uri, explicit?: string): Promise<boolean> {
    const problem = `Profiling needs Python ${MIN_VERSION}+ (Tachyon).`;
    const learnMore = 'Learn More';
    if (explicit) {
      // the launch configuration names the interpreter: selecting another one would not change it
      const pick = await vscode.window.showWarningMessage(
        `${problem} The launch configuration's "python" is ${info.label} (${info.executable}).`,
        learnMore,
      );
      if (pick) await this.openDocs();
      return false;
    }
    const select = 'Select Interpreter';
    const create = `Create ${MIN_VERSION} venv`;
    const pick = await vscode.window.showWarningMessage(
      `${problem} The selected interpreter is ${info.label} (${info.executable}).`,
      select,
      create,
      learnMore,
    );
    if (pick === select) {
      await vscode.commands.executeCommand('python.setInterpreter');
      return true;
    }
    if (pick === create) this.createVenv(resource);
    else if (pick === learnMore) await this.openDocs();
    return false;
  }

  private async openDocs(): Promise<void> {
    await vscode.env.openExternal(vscode.Uri.parse('https://docs.python.org/3.15/library/profiling.sampling.html'));
  }

  private createVenv(resource?: vscode.Uri): void {
    const folder = resource ? vscode.workspace.getWorkspaceFolder(resource) : vscode.workspace.workspaceFolders?.[0];
    const hasUv = findOnPath('uv') !== undefined;
    const terminal = vscode.window.createTerminal({ name: `Create Python ${MIN_VERSION} venv`, cwd: folder?.uri });
    terminal.show();
    if (hasUv) terminal.sendText(`uv venv -p ${MIN_VERSION} .venv`);
    else if (process.platform === 'win32') terminal.sendText(`py -${MIN_VERSION} -m venv .venv`);
    else terminal.sendText(`python${MIN_VERSION} -m venv .venv`);
    void vscode.window.showInformationMessage(
      `Creating .venv with Python ${MIN_VERSION}${hasUv ? ' via uv' : ''}. Select it afterwards with "Python: Select Interpreter".`,
    );
  }

  /** Environment variables the Python extension uses for this resource (.env included). */
  async environmentVariables(resource?: vscode.Uri): Promise<Record<string, string>> {
    const api = await this.getApi();
    const out: Record<string, string> = {};
    try {
      const vars = api?.environments.getEnvironmentVariables(resource);
      if (vars) for (const [k, v] of Object.entries(vars)) if (v !== undefined) out[k] = v;
    } catch (e) {
      this.log.warn(`reading environment variables failed: ${errorMessage(e)}`);
    }
    return out;
  }

  dispose(): void {
    for (const d of this.disposables) d.dispose();
    this.changed.dispose();
  }
}

/** Full path of an executable on PATH, like `which` / `where`. */
function findOnPath(command: string): string | undefined {
  const extensions = process.platform === 'win32' ? (process.env.PATHEXT ?? '.EXE;.CMD;.BAT').split(';') : [''];
  for (const dir of (process.env.PATH ?? '').split(path.delimiter)) {
    for (const extension of extensions) {
      const candidate = path.join(dir, command + extension.toLowerCase());
      try {
        fs.accessSync(candidate, fs.constants.X_OK);
        return candidate;
      } catch {
        /* not here: try the next location */
      }
    }
  }
  return undefined;
}
