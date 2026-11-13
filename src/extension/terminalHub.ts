/**
 * Terminal integration: makes `pyprof run …` work in every VS Code terminal.
 *
 * - prepends our `bin/` (pyprof shims) to PATH via environmentVariableCollection
 * - exports PYPROF_HUB=host:port:token
 * - the launcher connects here, we start a collector with *the launcher's*
 *   interpreter (whatever venv is active in that terminal – uv, poetry, conda…)
 *   and reply with the agent address.
 */
import * as vscode from 'vscode';
import * as net from 'node:net';
import * as crypto from 'node:crypto';
import * as path from 'node:path';
import type { SessionManager } from './session';
import type { ProcessPicker } from './processes';
import type { ExtPaths } from './paths';

export class TerminalHub implements vscode.Disposable {
  private server: net.Server | undefined;
  private readonly token = crypto.randomBytes(16).toString('hex');

  constructor(
    private readonly ctx: vscode.ExtensionContext,
    private readonly paths: ExtPaths,
    private readonly sessions: SessionManager,
    private readonly picker: ProcessPicker,
    private readonly log: vscode.LogOutputChannel,
  ) {}

  async start(): Promise<void> {
    if (!vscode.workspace.getConfiguration('pyprof').get('terminalIntegration', true)) {
      this.ctx.environmentVariableCollection.clear();
      return;
    }
    this.server = net.createServer((sock) => this.onConnection(sock));
    await new Promise<void>((resolve, reject) => {
      this.server!.once('error', reject);
      this.server!.listen(0, '127.0.0.1', () => resolve());
    });
    const port = (this.server.address() as net.AddressInfo).port;
    const env = this.ctx.environmentVariableCollection;
    env.persistent = false;
    env.description = 'Adds the `pyprof` command (Python Profiler) to this terminal';
    env.replace('PYPROF_HUB', `127.0.0.1:${port}:${this.token}`);
    env.prepend('PATH', this.paths.bin + path.delimiter);
    this.log.info(`terminal hub on 127.0.0.1:${port}`);
  }

  private onConnection(sock: net.Socket): void {
    let buf = '';
    sock.setEncoding('utf8');
    sock.setTimeout(30_000, () => sock.destroy());
    sock.on('data', async (chunk) => {
      buf += chunk;
      const nl = buf.indexOf('\n');
      if (nl < 0) return;
      const line = buf.slice(0, nl);
      buf = '';
      let hello: any;
      try {
        hello = JSON.parse(line);
      } catch {
        sock.destroy();
        return;
      }
      if (hello.token !== this.token) {
        sock.end(JSON.stringify({ error: 'bad token' }) + '\n');
        return;
      }
      try {
        if (hello.kind === 'attach') {
          await this.picker.attachPid(Number(hello.target));
          sock.end(JSON.stringify({ ok: true }) + '\n');
        } else {
          const reply = await this.sessions.fromTerminal(hello);
          sock.end(JSON.stringify(reply) + '\n');
        }
      } catch (e) {
        sock.end(JSON.stringify({ error: String((e as Error).message ?? e) }) + '\n');
      }
    });
    sock.on('error', () => undefined);
  }

  dispose(): void {
    this.server?.close();
  }
}
