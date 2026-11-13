/** Python process discovery + attach flow (QuickPick and the Processes view). */
import * as vscode from 'vscode';
import { execFile } from 'node:child_process';
import * as path from 'node:path';
import { MIN_MAJOR, MIN_MINOR, type EnvironmentResolver, type PythonInfo } from './environment';
import type { ExtPaths } from './paths';
import type { SessionManager } from './sessionManager';
import { errorMessage } from '../shared/errors';
import type { AttachOptions } from '../shared/protocol';

/** One record printed by `python/_vscode_pyprof/processes.py`. */
export interface ProcInfo {
  pid: number;
  ppid: number;
  executable: string;
  realExecutable: string;
  version: string | null;
  venv: string | null;
  argv: string[];
  title: string;
  cwd: string | null;
  /** Windows venv launcher stub: the real interpreter is its child */
  isLauncher?: boolean;
}

type ProcessItem = vscode.QuickPickItem & { process?: ProcInfo };

const OWN_PROCESS_MARKERS = ['_vscode_pyprof.cli', 'processes.py'];
const LIST_TIMEOUT_MS = 20_000;

export class ProcessPicker {
  constructor(
    private readonly paths: ExtPaths,
    private readonly env: EnvironmentResolver,
    private readonly sessions: SessionManager,
    private readonly log: vscode.LogOutputChannel,
  ) {}

  /** Python processes worth attaching to (not ours, not already profiled). */
  async list(): Promise<ProcInfo[]> {
    const python = (await this.env.resolve())?.executable ?? (process.platform === 'win32' ? 'python' : 'python3');
    const profiled = new Set(this.sessions.sessions.filter((s) => s.live).map((s) => s.pid));
    const all = await this.runListScript(python);
    return all.filter(
      (p) =>
        !p.isLauncher &&
        !profiled.has(p.pid) &&
        !p.argv.some((arg) => OWN_PROCESS_MARKERS.some((marker) => arg.includes(marker))),
    );
  }

  /** The script is stdlib-only and works with any Python ≥ 3.10. */
  private runListScript(python: string): Promise<ProcInfo[]> {
    return new Promise((resolve) => {
      const options = { timeout: LIST_TIMEOUT_MS, windowsHide: true, maxBuffer: 16 << 20 };
      execFile(python, ['-I', this.paths.processesScript], options, (err, stdout) => {
        if (err) {
          this.log.warn(`process listing failed: ${err.message}`);
          resolve([]);
          return;
        }
        try {
          resolve(JSON.parse(stdout) as ProcInfo[]);
        } catch (e) {
          this.log.warn(`bad process list: ${errorMessage(e)}`);
          resolve([]);
        }
      });
    });
  }

  /** Processes that belong to the open workspace first, then newest first. */
  rank(processes: ProcInfo[]): ProcInfo[] {
    const roots = (vscode.workspace.workspaceFolders ?? []).map((f) => f.uri.fsPath.toLowerCase());
    const inWorkspace = (p: ProcInfo): boolean =>
      [p.cwd ?? '', p.venv ?? '', ...p.argv].some((value) => roots.some((root) => value.toLowerCase().startsWith(root)));
    return [...processes].sort((a, b) => Number(inWorkspace(b)) - Number(inWorkspace(a)) || b.pid - a.pid);
  }

  async pick(): Promise<ProcInfo | undefined> {
    const quickPick = vscode.window.createQuickPick<ProcessItem>();
    quickPick.title = 'Attach profiler to a Python process';
    quickPick.placeholder = 'Filter by PID, command line or environment';
    quickPick.matchOnDescription = true;
    quickPick.matchOnDetail = true;
    quickPick.busy = true;
    quickPick.show();
    const processes = this.rank(await this.list());
    quickPick.busy = false;
    quickPick.items = processes.length
      ? processes.map((p) => ({
          label: `$(symbol-event) ${shortTitle(p)}`,
          description: [`PID ${p.pid}`, `Python ${p.version ?? ''}`.trim(), p.venv && path.basename(p.venv)]
            .filter(Boolean)
            .join(' · '),
          detail: p.title,
          process: p,
        }))
      : [{ label: 'No Python processes found', description: 'Start your program, then try again' }];
    return new Promise((resolve) => {
      quickPick.onDidAccept(() => {
        resolve(quickPick.selectedItems[0]?.process);
        quickPick.hide();
      });
      quickPick.onDidHide(() => {
        resolve(undefined);
        quickPick.dispose();
      });
    });
  }

  async pickAndAttach(): Promise<void> {
    const process = await this.pick();
    if (process) await this.attach(process);
  }

  /** For `${command:pyprof.pickProcess}` in launch configurations. */
  async pickPid(): Promise<string | undefined> {
    return (await this.pick())?.pid.toString();
  }

  /** Attach using the *target's* interpreter (Tachyon is version specific). */
  async attach(target: ProcInfo, options: AttachOptions = {}): Promise<void> {
    const python = await this.interpreterFor(target);
    if (python) await this.sessions.attach(target.pid, python, shortTitle(target), options);
  }

  async attachPid(pid: number, options: AttachOptions = {}): Promise<void> {
    const known = (await this.list()).find((p) => p.pid === pid);
    if (known) return this.attach(known, options);
    const python = await this.env.ensureSupported();
    if (python) await this.sessions.attach(pid, python, `PID ${pid}`, options);
  }

  private async interpreterFor(target: ProcInfo): Promise<PythonInfo | undefined> {
    for (const executable of [target.executable, target.realExecutable]) {
      if (!executable) continue;
      const info = await this.env.probe(executable);
      if (!info) continue;
      if (this.env.isSupported(info)) return info;
      void vscode.window.showErrorMessage(
        `PID ${target.pid} runs Python ${info.version}. Attaching needs Python ${MIN_MAJOR}.${MIN_MINOR}+ ` +
          `(the target and profiler must match).`,
      );
      return undefined;
    }
    // could not run the target's executable (container, deleted venv…): fall back to the selected one
    const selected = await this.env.ensureSupported();
    if (selected && target.version && !target.version.startsWith(`${selected.major}.${selected.minor}`)) {
      void vscode.window.showWarningMessage(
        `Using ${selected.label} to profile PID ${target.pid} (Python ${target.version}). ` +
          `Versions must match for Tachyon to read stacks.`,
      );
    }
    return selected;
  }
}

/** Short human name of a process: `uvicorn app:main`, `manage.py runserver`, … */
export function shortTitle(p: ProcInfo): string {
  const args = p.argv.slice(1).filter((a) => !a.startsWith('-') || a === '-m');
  const m = args.indexOf('-m');
  if (m >= 0 && args[m + 1]) return `${args[m + 1]} ${args.slice(m + 2, m + 4).join(' ')}`.trim();
  const script = args[0] ? path.basename(args[0]) : path.basename(p.executable || 'python');
  return `${script} ${args.slice(1, 3).join(' ')}`.trim();
}
