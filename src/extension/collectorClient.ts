/** JSON-lines RPC client for the Python collector process. */
import * as vscode from 'vscode';
import { spawn, type ChildProcess } from 'node:child_process';
import * as readline from 'node:readline';
import { COLLECTOR_BOOT } from './paths';
import type { CollectorNotification, CollectorRequests } from '../shared/protocol';

export class RpcFailure extends Error {}

interface Pending {
  resolve: (value: unknown) => void;
  reject: (error: Error) => void;
  timer: NodeJS.Timeout;
}

const NOTIFICATION_METHODS: ReadonlySet<string> = new Set<CollectorNotification['method']>([
  'delta',
  'state',
  'agent',
  'children',
  'error',
]);
const STDERR_TAIL_LINES = 30;
const KILL_GRACE_MS = 1000;

export class CollectorClient implements vscode.Disposable {
  private proc: ChildProcess | undefined;
  private nextId = 1;
  private readonly pending = new Map<number, Pending>();
  private readonly notifications = new vscode.EventEmitter<CollectorNotification>();
  readonly onNotification = this.notifications.event;
  private readonly exited = new vscode.EventEmitter<number | null>();
  readonly onExit = this.exited.event;
  private stderrTail: string[] = [];
  private running = false;

  constructor(
    readonly python: string,
    private readonly pythonDir: string,
    private readonly log: vscode.LogOutputChannel,
  ) {}

  get alive(): boolean {
    return this.running;
  }

  start(): void {
    this.log.info(`starting collector: ${this.python}`);
    const proc = spawn(this.python, ['-I', '-c', COLLECTOR_BOOT, this.pythonDir, 'serve'], {
      stdio: ['pipe', 'pipe', 'pipe'],
      windowsHide: true,
      env: { ...process.env, PYTHONUNBUFFERED: '1', PYTHONIOENCODING: 'utf-8' },
    });
    this.proc = proc;
    this.running = true;
    readline.createInterface({ input: proc.stdout }).on('line', (line) => this.onLine(line));
    proc.stderr.on('data', (chunk: Buffer) => this.onStderr(chunk.toString('utf8')));
    // a write to a collector that just died must not surface as an uncaught 'error' event
    proc.stdin.on('error', (e) => this.log.debug(`collector stdin: ${e.message}`));
    proc.on('error', (e) => {
      this.running = false;
      this.failAll(new RpcFailure(`cannot start ${this.python}: ${e.message}`));
    });
    proc.on('exit', (code) => {
      this.running = false;
      this.failAll(new RpcFailure(`collector exited (${code}). ${this.stderrTail.slice(-5).join(' ')}`));
      this.exited.fire(code);
    });
  }

  request<M extends keyof CollectorRequests>(
    method: M,
    params: CollectorRequests[M]['params'],
    timeoutMs = 60_000,
  ): Promise<CollectorRequests[M]['result']> {
    const stdin = this.proc?.stdin;
    if (!stdin || !this.running) return Promise.reject(new RpcFailure('collector is not running'));
    const id = this.nextId++;
    return new Promise<CollectorRequests[M]['result']>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new RpcFailure(`collector timed out on ${method}`));
      }, timeoutMs);
      this.pending.set(id, { resolve, reject, timer });
      stdin.write(JSON.stringify({ id, method, params }) + '\n');
    });
  }

  /** Ask the collector to exit; kill it if it does not. */
  async shutdown(): Promise<void> {
    if (!this.running) return;
    try {
      await this.request('shutdown', {}, 5000);
    } catch {
      /* it is going away either way */
    }
    const proc = this.proc;
    setTimeout(() => proc?.kill(), KILL_GRACE_MS).unref();
  }

  dispose(): void {
    this.running = false;
    this.failAll(new RpcFailure('collector client disposed'));
    this.proc?.kill();
    this.notifications.dispose();
    this.exited.dispose();
  }

  private onLine(line: string): void {
    if (!line.trim()) return;
    let message: unknown;
    try {
      message = JSON.parse(line);
    } catch {
      this.log.warn(`bad collector line: ${line.slice(0, 200)}`);
      return;
    }
    if (!isRecord(message)) return;
    if (typeof message.id === 'number') {
      this.onResponse(message.id, message);
    } else if (typeof message.method === 'string' && NOTIFICATION_METHODS.has(message.method)) {
      // shape is the collector's side of the contract in shared/protocol.ts
      this.notifications.fire(message as unknown as CollectorNotification);
    }
  }

  private onResponse(id: number, message: Record<string, unknown>): void {
    const pending = this.pending.get(id);
    if (!pending) return;
    this.pending.delete(id);
    clearTimeout(pending.timer);
    if (isRecord(message.error)) pending.reject(new RpcFailure(String(message.error.message)));
    else pending.resolve(message.result);
  }

  private onStderr(text: string): void {
    for (const line of text.split(/\r?\n/)) {
      if (!line) continue;
      this.log.warn(`[collector] ${line}`);
      this.stderrTail.push(line);
      if (this.stderrTail.length > STDERR_TAIL_LINES) this.stderrTail.shift();
    }
  }

  private failAll(error: Error): void {
    for (const pending of this.pending.values()) {
      clearTimeout(pending.timer);
      pending.reject(error);
    }
    this.pending.clear();
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
