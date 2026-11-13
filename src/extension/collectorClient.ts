/** JSON-lines RPC client for the Python collector process. */
import * as vscode from 'vscode';
import { spawn, type ChildProcess } from 'node:child_process';
import * as readline from 'node:readline';
import { COLLECTOR_BOOT } from './paths';

export class RpcFailure extends Error {}

export class CollectorClient implements vscode.Disposable {
  private proc: ChildProcess | undefined;
  private nextId = 1;
  private pending = new Map<number, { resolve: (v: unknown) => void; reject: (e: Error) => void; timer: NodeJS.Timeout }>();
  private readonly notifications = new vscode.EventEmitter<{ method: string; params: any }>();
  readonly onNotification = this.notifications.event;
  private readonly exited = new vscode.EventEmitter<number | null>();
  readonly onExit = this.exited.event;
  private stderrTail: string[] = [];
  alive = false;

  constructor(
    readonly python: string,
    private readonly pythonDir: string,
    private readonly log: vscode.LogOutputChannel,
  ) {}

  start(): void {
    this.log.info(`starting collector: ${this.python}`);
    const proc = spawn(this.python, ['-I', '-c', COLLECTOR_BOOT, this.pythonDir, 'serve'], {
      stdio: ['pipe', 'pipe', 'pipe'],
      windowsHide: true,
      env: { ...process.env, PYTHONUNBUFFERED: '1', PYTHONIOENCODING: 'utf-8' },
    });
    this.proc = proc;
    this.alive = true;
    const rl = readline.createInterface({ input: proc.stdout! });
    rl.on('line', (line) => this.onLine(line));
    proc.stderr!.on('data', (b: Buffer) => {
      const text = b.toString('utf8');
      for (const l of text.split(/\r?\n/)) {
        if (!l) continue;
        this.log.warn(`[collector] ${l}`);
        this.stderrTail.push(l);
        if (this.stderrTail.length > 30) this.stderrTail.shift();
      }
    });
    proc.on('error', (e) => this.fail(new RpcFailure(`cannot start ${this.python}: ${e.message}`)));
    proc.on('exit', (code) => {
      this.alive = false;
      this.fail(new RpcFailure(`collector exited (${code}). ${this.stderrTail.slice(-5).join(' ')}`));
      this.exited.fire(code);
    });
  }

  private onLine(line: string): void {
    if (!line.trim()) return;
    let msg: any;
    try {
      msg = JSON.parse(line);
    } catch {
      this.log.warn(`bad collector line: ${line.slice(0, 200)}`);
      return;
    }
    if (msg.id !== undefined) {
      const p = this.pending.get(msg.id);
      if (!p) return;
      this.pending.delete(msg.id);
      clearTimeout(p.timer);
      if (msg.error) p.reject(new RpcFailure(msg.error.message));
      else p.resolve(msg.result);
    } else if (msg.method) {
      this.notifications.fire({ method: msg.method, params: msg.params });
    }
  }

  request<T = any>(method: string, params: unknown = {}, timeoutMs = 60_000): Promise<T> {
    if (!this.proc || !this.alive) return Promise.reject(new RpcFailure('collector is not running'));
    const id = this.nextId++;
    return new Promise<T>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new RpcFailure(`collector timed out on ${method}`));
      }, timeoutMs);
      this.pending.set(id, { resolve: resolve as (v: unknown) => void, reject, timer });
      this.proc!.stdin!.write(JSON.stringify({ id, method, params }) + '\n');
    });
  }

  private fail(err: Error): void {
    for (const p of this.pending.values()) {
      clearTimeout(p.timer);
      p.reject(err);
    }
    this.pending.clear();
  }

  async shutdown(): Promise<void> {
    if (!this.alive) return;
    try {
      await this.request('shutdown', {}, 5000);
    } catch {
      /* ignore */
    }
    setTimeout(() => this.proc?.kill(), 1000);
  }

  dispose(): void {
    this.alive = false;
    this.proc?.kill();
    this.notifications.dispose();
    this.exited.dispose();
  }
}
