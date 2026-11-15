/** Dashboard webview panels: at most one per session. */
import * as vscode from 'vscode';
import * as crypto from 'node:crypto';
import { openSource } from './openSource';
import type { Session } from './session';
import type { SessionActions } from './sessionActions';
import type { SessionManager } from './sessionManager';
import { errorMessage } from '../shared/errors';
import type { FromWebview, ToWebview, ViewState } from '../shared/protocol';

const PANEL_TYPE = 'vspyprof.dashboard';

export class Dashboards implements vscode.Disposable {
  private readonly panels = new Map<string, vscode.WebviewPanel>();
  private readonly viewStates = new Map<string, ViewState>();
  private readonly pendingReveal = new Map<string, number>();
  private readonly viewStateChanged = new vscode.EventEmitter<Session>();
  /** the user changed mode, time range or thread filter in a dashboard */
  readonly onDidChangeViewState = this.viewStateChanged.event;

  constructor(
    private readonly ctx: vscode.ExtensionContext,
    private readonly sessions: SessionManager,
    private readonly actions: SessionActions,
  ) {}

  /** What the session's dashboard currently shows (drives editor heat and hotspots). */
  viewState(session: Session): ViewState | undefined {
    return this.viewStates.get(session.id);
  }

  open(session: Session, column = vscode.ViewColumn.Active): void {
    const existing = this.panels.get(session.id);
    if (existing) {
      existing.reveal(undefined, true);
      return;
    }
    const panel = vscode.window.createWebviewPanel(PANEL_TYPE, panelTitle(session), column, {
      enableScripts: true,
      retainContextWhenHidden: true,
      localResourceRoots: [this.distUri],
    });
    panel.iconPath = new vscode.ThemeIcon('flame');
    this.bind(session, panel);
  }

  /** Show a function's callers and callees in the dashboard (from CodeLens / hotspots). */
  revealFunction(session: Session, fn: number): void {
    const panel = this.panels.get(session.id);
    if (panel) {
      panel.reveal(undefined, false);
      post(panel, { type: 'reveal', fn });
    } else {
      this.pendingReveal.set(session.id, fn);
      this.open(session, vscode.ViewColumn.Beside);
    }
  }

  /** Connect a panel (ours or a custom editor's) to a session. */
  bind(session: Session, panel: vscode.WebviewPanel): void {
    const webview = panel.webview;
    webview.options = { enableScripts: true, localResourceRoots: [this.distUri] };
    webview.html = this.html(webview);
    let ready = false; // deltas before `ready` are covered by the `init` message

    const disposables = [
      session.onDidDelta((data) => {
        if (ready) post(panel, { type: 'delta', data });
      }),
      session.onDidChange(() => {
        panel.title = panelTitle(session);
        if (ready) post(panel, { type: 'state', state: session.state, capabilities: session.capabilities });
      }),
      webview.onDidReceiveMessage((message: FromWebview) => {
        if (message.type === 'ready') ready = true;
        void this.onMessage(session, panel, message);
      }),
      panel.onDidChangeViewState(() => {
        if (panel.active) this.sessions.setActive(session);
      }),
    ];
    this.panels.set(session.id, panel);
    panel.onDidDispose(() => {
      for (const d of disposables) d.dispose();
      if (this.panels.get(session.id) === panel) this.panels.delete(session.id);
    });
  }

  private async onMessage(session: Session, panel: vscode.WebviewPanel, message: FromWebview): Promise<void> {
    switch (message.type) {
      case 'ready': {
        post(panel, {
          type: 'init',
          sessionId: session.id,
          label: session.label,
          state: session.state,
          data: session.model.toDelta(),
          capabilities: session.capabilities,
        });
        const fn = this.pendingReveal.get(session.id);
        if (fn !== undefined) {
          this.pendingReveal.delete(session.id);
          post(panel, { type: 'reveal', fn });
        }
        break;
      }
      case 'openSource':
        await openSource(message.file, message.line);
        break;
      case 'viewState':
        this.viewStates.set(session.id, message.state);
        this.viewStateChanged.fire(session);
        break;
      case 'command':
        try {
          await this.actions.run(message, session);
          post(panel, { type: 'commandResult', id: message.id });
        } catch (e) {
          post(panel, { type: 'commandResult', id: message.id, error: errorMessage(e) });
        }
        break;
    }
  }

  private get distUri(): vscode.Uri {
    return vscode.Uri.joinPath(this.ctx.extensionUri, 'dist');
  }

  private html(webview: vscode.Webview): string {
    const nonce = crypto.randomBytes(16).toString('base64');
    const script = webview.asWebviewUri(vscode.Uri.joinPath(this.distUri, 'webview.js')).toString();
    const style = webview.asWebviewUri(vscode.Uri.joinPath(this.distUri, 'webview.css')).toString();
    const csp = [
      `default-src 'none'`,
      `img-src ${webview.cspSource} data:`,
      `style-src ${webview.cspSource} 'unsafe-inline'`,
      `script-src 'nonce-${nonce}'`,
      `font-src ${webview.cspSource}`,
    ].join('; ');
    return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="${csp};">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Python Profile</title>
<link rel="stylesheet" href="${style}">
</head>
<body>
<div id="app"><div style="padding:24px;opacity:.7">Loading profile…</div></div>
<script nonce="${nonce}" src="${script}"></script>
</body>
</html>`;
  }

  dispose(): void {
    for (const panel of this.panels.values()) panel.dispose();
    this.viewStateChanged.dispose();
  }
}

function panelTitle(session: Session): string {
  return `${session.live ? '⚡' : '◼'} ${session.label}`;
}

function post(panel: vscode.WebviewPanel, message: ToWebview): void {
  void panel.webview.postMessage(message);
}
