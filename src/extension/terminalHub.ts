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
import type { ExtPaths } from './paths';
import type { ProcessPicker } from './processes';
import type { SessionManager } from './sessionManager';
import { settings } from './settings';
import { errorMessage } from '../shared/errors';
import type { TerminalHello } from '../shared/protocol';

const HELLO_TIMEOUT_MS = 30_000;

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
    const terminalEnv = this.ctx.environmentVariableCollection;
    if (!settings.terminalIntegration()) {
      terminalEnv.clear();
      return;
    }
    const server = net.createServer((socket) => this.onConnection(socket));
    this.server = server;
    await new Promise<void>((resolve, reject) => {
      server.once('error', reject);
      server.listen(0, '127.0.0.1', resolve);
    });
    const { port } = server.address() as net.AddressInfo;
    terminalEnv.persistent = false;
    terminalEnv.description = 'Adds the `pyprof` command (Python Profiler) to this terminal';
    terminalEnv.replace('PYPROF_HUB', `127.0.0.1:${port}:${this.token}`);
    terminalEnv.prepend('PATH', this.paths.bin + path.delimiter);
    this.log.info(`terminal hub on 127.0.0.1:${port}`);
  }

  /** One line in (the launcher's hello), one line out (our reply). */
  private onConnection(socket: net.Socket): void {
    let buffer = '';
    let answered = false;
    socket.setEncoding('utf8');
    socket.setTimeout(HELLO_TIMEOUT_MS, () => socket.destroy());
    socket.on('error', () => undefined); // the launcher went away: nothing to clean up
    socket.on('data', (chunk: string) => {
      if (answered) return;
      buffer += chunk;
      const newline = buffer.indexOf('\n');
      if (newline < 0) return;
      answered = true;
      void this.reply(buffer.slice(0, newline)).then((reply) => socket.end(JSON.stringify(reply) + '\n'));
    });
  }

  private async reply(line: string): Promise<Record<string, unknown>> {
    try {
      const hello = parseHello(line);
      if (hello.token !== this.token) return { error: 'bad token' };
      if (hello.kind === 'attach') {
        await this.picker.attachPid(Number(hello.target));
        return { ok: true };
      }
      return await this.sessions.fromTerminal(hello);
    } catch (e) {
      return { error: errorMessage(e) };
    }
  }

  dispose(): void {
    this.server?.close();
  }
}

function parseHello(line: string): TerminalHello {
  const data: unknown = JSON.parse(line);
  if (typeof data !== 'object' || data === null) throw new Error('malformed hello');
  const hello = data as Partial<TerminalHello>;
  if (
    typeof hello.token !== 'string' ||
    typeof hello.executable !== 'string' ||
    typeof hello.version !== 'string' ||
    typeof hello.target !== 'string' ||
    typeof hello.kind !== 'string' ||
    !Array.isArray(hello.args)
  ) {
    throw new Error('malformed hello');
  }
  return { ...(hello as TerminalHello), args: hello.args.map(String) };
}
