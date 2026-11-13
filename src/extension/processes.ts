/** Python process discovery + attach flow (QuickPick and the Processes view). */
import * as vscode from 'vscode';
import { execFile } from 'node:child_process';
import * as path from 'node:path';
import type { EnvironmentResolver, PythonInfo } from './environment';
import type { ExtPaths } from './paths';
import type { SessionManager } from './session';
import type { CollectorOptions } from '../shared/protocol';

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
  isLauncher?: boolean;
}

export class ProcessPicker {
  constructor(
    private readonly paths: ExtPaths,
    private readonly env: EnvironmentResolver,
    private readonly sessions: SessionManager,
    private readonly log: vscode.LogOutputChannel,
  ) {}

  /** List Python processes. Works with any Python ≥3.8 (stdlib-only script). */
  async list(): Promise<ProcInfo[]> {
    const py = (await this.env.resolve())?.executable ?? (process.platform === 'win32' ? 'python' : 'python3');
    return new Promise((resolve) => {
      execFile(py, ['-I', this.paths.processesScript], { timeout: 20_000, windowsHide: true, maxBuffer: 16 << 20 }, (err, stdout) => {
        if (err) {
          this.log.warn(`process listing failed: ${err.message}`);
          resolve([]);
          return;
        }
        try {
          const all = JSON.parse(stdout) as ProcInfo[];
          const own = new Set(this.sessions.sessions.filter((s) => s.live).map((s) => s.client && s.pid));
          // hide our own collectors and Windows venv launcher stubs (the real interpreter is the child)
          resolve(
            all.filter(
              (p) =>
                !p.argv.some((a) => a.includes('_vscode_pyprof.cli')) &&
                !p.isLauncher &&
                !p.argv.some((a) => a.includes('processes.py')) &&
                !own.has(p.pid as never),
            ),
          );
        } catch (e) {
          this.log.warn(`bad process list: ${e}`);
          resolve([]);
        }
      });
    });
  }

  rank(procs: ProcInfo[]): ProcInfo[] {
    const roots = (vscode.workspace.workspaceFolders ?? []).map((f) => f.uri.fsPath.toLowerCase());
    const inWs = (p: ProcInfo) =>
      roots.some((r) => (p.cwd ?? '').toLowerCase().startsWith(r) || (p.venv ?? '').toLowerCase().startsWith(r) || p.argv.some((a) => a.toLowerCase().startsWith(r)));
    return procs.sort((a, b) => Number(inWs(b)) - Number(inWs(a)) || b.pid - a.pid);
  }

  async pick(): Promise<ProcInfo | undefined> {
    const qp = vscode.window.createQuickPick<vscode.QuickPickItem & { proc?: ProcInfo }>();
    qp.title = 'Attach profiler to a Python process';
    qp.placeholder = 'Filter by PID, command line or environment';
    qp.matchOnDescription = true;
    qp.matchOnDetail = true;
    qp.busy = true;
    qp.show();
    const procs = this.rank(await this.list());
    qp.busy = false;
    qp.items = procs.length
      ? procs.map((p) => ({
          label: `$(symbol-event) ${shortTitle(p)}`,
          description: `PID ${p.pid} · ${p.version ? 'Python ' + p.version : 'Python'}${p.venv ? ' · ' + path.basename(p.venv) : ''}`,
          detail: p.title,
          proc: p,
        }))
      : [{ label: 'No Python processes found', description: 'Start your program, then refresh' }];
    return new Promise((resolve) => {
      qp.onDidAccept(() => {
        resolve(qp.selectedItems[0]?.proc);
        qp.hide();
      });
      qp.onDidHide(() => {
        resolve(undefined);
        qp.dispose();
      });
    });
  }

  async pickAndAttach(): Promise<void> {
    const p = await this.pick();
    if (p) await this.attach(p);
  }

  async pickPid(): Promise<string | undefined> {
    return (await this.pick())?.pid.toString();
  }

  /** Attach using the *target's* interpreter (Tachyon is version specific). */
  async attach(p: ProcInfo, options: CollectorOptions & { inject?: boolean } = {}): Promise<void> {
    const python = await this.interpreterFor(p);
    if (!python) return;
    await this.sessions.attach(p.pid, python, shortTitle(p), options);
  }

  async attachPid(pid: number, options: CollectorOptions & { inject?: boolean } = {}): Promise<void> {
    const procs = await this.list();
    const p = procs.find((x) => x.pid === pid);
    if (p) return this.attach(p, options);
    const py = await this.env.ensureSupported();
    if (py) await this.sessions.attach(pid, py, `PID ${pid}`, options);
  }

  private async interpreterFor(p: ProcInfo): Promise<PythonInfo | undefined> {
    for (const exe of [p.executable, p.realExecutable]) {
      if (!exe) continue;
      const info = await this.env.probe(exe);
      if (info && this.env.isSupported(info)) return info;
      if (info) {
        vscode.window.showErrorMessage(
          `PID ${p.pid} runs Python ${info.version}. Attaching needs Python 3.15+ (the target and profiler must match).`,
        );
        return undefined;
      }
    }
    // could not run the target's executable (container, deleted venv…): fall back to the selected one
    const sel = await this.env.ensureSupported();
    if (sel && p.version && !p.version.startsWith(`${sel.major}.${sel.minor}`)) {
      vscode.window.showWarningMessage(
        `Using ${sel.label} to profile PID ${p.pid} (Python ${p.version}). Versions must match for Tachyon to read stacks.`,
      );
    }
    return sel;
  }
}

export function shortTitle(p: ProcInfo): string {
  const args = p.argv.slice(1).filter((a) => !a.startsWith('-') || a === '-m');
  const m = args.indexOf('-m');
  if (m >= 0 && args[m + 1]) return `${args[m + 1]} ${args.slice(m + 2, m + 4).join(' ')}`.trim();
  const script = args[0] ? path.basename(args[0]) : path.basename(p.executable || 'python');
  return `${script} ${args.slice(1, 3).join(' ')}`.trim();
}
