/** Status bar summary of the active live session, with a stop button. */
import * as vscode from 'vscode';
import type { SessionManager } from '../sessionManager';
import { fmtBytes, fmtCount, fmtMs } from '../../shared/format';

const REFRESH_MS = 1000;
const LAG_WARNING_MS = 100;

export class StatusBar implements vscode.Disposable {
  private readonly summary = vscode.window.createStatusBarItem('vspyprof.status', vscode.StatusBarAlignment.Left, 50);
  private readonly stop = vscode.window.createStatusBarItem('vspyprof.stop', vscode.StatusBarAlignment.Left, 49);
  private readonly disposables: vscode.Disposable[];
  private readonly timer: NodeJS.Timeout;

  constructor(private readonly sessions: SessionManager) {
    this.summary.name = 'Python Profiler';
    this.summary.command = 'vspyprof.openDashboard';
    this.stop.name = 'Python Profiler: Stop';
    this.stop.text = '$(debug-stop)';
    this.stop.tooltip = 'Stop profiling';
    this.stop.command = 'vspyprof.stop';
    this.disposables = [
      sessions.onDidChange(() => this.update()),
      sessions.onDidChangeActive(() => this.update()),
    ];
    this.timer = setInterval(() => this.update(), REFRESH_MS);
  }

  private update(): void {
    const session = this.sessions.active;
    if (!session?.live) {
      this.summary.hide();
      this.stop.hide();
      return;
    }
    const model = session.model;
    const parts = [session.state === 'running' ? '$(flame)' : '$(loading~spin)'];
    parts.push(session.pid ? `PID ${session.pid}` : session.label);
    if (model.stats.samples) parts.push(`${fmtCount(model.stats.samples)} samples`);
    const cpu = model.lastValue('cpu');
    if (cpu !== undefined) parts.push(`CPU ${cpu.toFixed(0)}%`);
    const rss = model.lastValue('rss');
    if (rss !== undefined) parts.push(fmtBytes(rss));
    const lag = model.lastValue('loopLag');
    if (lag !== undefined) parts.push(`lag ${fmtMs(lag)}`);
    this.summary.text = parts.join(' · ');
    this.summary.tooltip = new vscode.MarkdownString(
      [
        `**Profiling ${session.label}**`,
        ...(session.python ? [`\`${session.python.label}\``] : []),
        `Sampling at ${model.stats.rateHz || '…'} Hz · ${model.stats.errors} discarded samples`,
        'Click to open the dashboard',
      ].join('\n\n'),
    );
    this.summary.backgroundColor =
      lag !== undefined && lag > LAG_WARNING_MS ? new vscode.ThemeColor('statusBarItem.warningBackground') : undefined;
    this.summary.show();
    this.stop.show();
  }

  dispose(): void {
    clearInterval(this.timer);
    for (const d of this.disposables) d.dispose();
    this.summary.dispose();
    this.stop.dispose();
  }
}
