/** Dashboard webview panels (one per session) and the .pyprof custom editor. */
import * as vscode from 'vscode';
import * as crypto from 'node:crypto';
import type { Session, SessionManager } from './session';
import type { FromWebview, ToWebview } from '../shared/protocol';
import type { Mode, Source } from '../shared/model';

export interface ViewState {
  mode: Mode;
  source: Source;
  t0?: number;
  t1?: number;
  threads?: number[];
}

export class Dashboards implements vscode.Disposable {
  private panels = new Map<string, { panel: vscode.WebviewPanel; disposables: vscode.Disposable[] }>();
  /** last view state reported by any dashboard, used by editor heat + hotspots */
  viewState = new Map<string, ViewState>();
  private readonly viewStateChanged = new vscode.EventEmitter<Session>();
  readonly onDidChangeViewState = this.viewStateChanged.event;
  private pendingReveal = new Map<string, number>();

  constructor(
    private readonly ctx: vscode.ExtensionContext,
    private readonly sessions: SessionManager,
    private readonly run: (cmd: string, s: Session, args?: Record<string, unknown>) => Promise<void>,
  ) {}

  open(s: Session, column = vscode.ViewColumn.Active): vscode.WebviewPanel {
    const existing = this.panels.get(s.id);
    if (existing) {
      existing.panel.reveal(undefined, true);
      return existing.panel;
    }
    const panel = vscode.window.createWebviewPanel('pyprof.dashboard', `⚡ ${s.label}`, column, {
      enableScripts: true,
      retainContextWhenHidden: true,
      localResourceRoots: [vscode.Uri.joinPath(this.ctx.extensionUri, 'dist')],
    });
    panel.iconPath = new vscode.ThemeIcon('flame');
    this.bind(s, panel);
    return panel;
  }

  /** Reveal a function in the dashboard (from CodeLens / hotspots). */
  revealFunction(s: Session, fn: number): void {
    const p = this.panels.get(s.id);
    if (p) {
      p.panel.reveal(undefined, false);
      void p.panel.webview.postMessage({ type: 'reveal', fn });
    } else {
      this.pendingReveal.set(s.id, fn);
      this.open(s, vscode.ViewColumn.Beside);
    }
  }

  bind(s: Session, panel: vscode.WebviewPanel): void {
    const webview = panel.webview;
    webview.options = { enableScripts: true, localResourceRoots: [vscode.Uri.joinPath(this.ctx.extensionUri, 'dist')] };
    webview.html = this.html(webview);
    const post = (m: ToWebview | Record<string, unknown>) => void webview.postMessage(m);
    const disposables: vscode.Disposable[] = [];
    let ready = false;
    const queued: unknown[] = [];

    disposables.push(
      s.onDidDelta((d) => (ready ? post({ type: 'delta', data: d }) : queued.push(d))),
      s.onDidChange(() => {
        panel.title = `${s.live ? '⚡' : '◼'} ${s.label}`;
        if (ready) post({ type: 'state', state: s.state, capabilities: s.capabilities });
      }),
      webview.onDidReceiveMessage(async (msg: FromWebview | any) => {
        switch (msg.type) {
          case 'ready': {
            ready = true;
            queued.length = 0; // init carries everything
            post({
              type: 'init',
              sessionId: s.id,
              label: s.label,
              live: s.live,
              state: s.state,
              data: s.model.toDelta(),
              capabilities: s.capabilities,
            });
            const fn = this.pendingReveal.get(s.id);
            if (fn !== undefined) {
              this.pendingReveal.delete(s.id);
              post({ type: 'reveal', fn });
            }
            break;
          }
          case 'openSource':
            await openSource(msg.file, msg.line);
            break;
          case 'viewState':
            this.viewState.set(s.id, msg.state as ViewState);
            this.viewStateChanged.fire(s);
            break;
          case 'command':
            try {
              await this.run(msg.command, s, msg.args);
            } catch (e) {
              post({ type: 'error', message: String((e as Error).message ?? e) });
            }
            break;
        }
      }),
      panel.onDidChangeViewState(() => {
        if (panel.active) this.sessions.setActive(s);
      }),
    );
    this.panels.set(s.id, { panel, disposables });
    panel.onDidDispose(() => {
      disposables.forEach((d) => d.dispose());
      this.panels.delete(s.id);
    });
  }

  post(s: Session, msg: ToWebview): void {
    void this.panels.get(s.id)?.panel.webview.postMessage(msg);
  }

  private html(webview: vscode.Webview): string {
    const nonce = crypto.randomBytes(16).toString('base64');
    const script = webview.asWebviewUri(vscode.Uri.joinPath(this.ctx.extensionUri, 'dist', 'webview.js'));
    return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src ${webview.cspSource} data:; style-src ${webview.cspSource} 'unsafe-inline'; script-src 'nonce-${nonce}'; font-src ${webview.cspSource};">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Python Profile</title>
</head>
<body>
<div id="app"><div class="loading">Loading profile…</div></div>
<script nonce="${nonce}" src="${script}"></script>
</body>
</html>`;
  }

  dispose(): void {
    for (const { panel } of this.panels.values()) panel.dispose();
    this.viewStateChanged.dispose();
  }
}

export async function openSource(file: string, line: number): Promise<void> {
  try {
    const doc = await vscode.workspace.openTextDocument(vscode.Uri.file(file));
    const pos = new vscode.Position(Math.max(0, line - 1), 0);
    await vscode.window.showTextDocument(doc, {
      viewColumn: vscode.ViewColumn.One,
      selection: new vscode.Range(pos, pos),
      preserveFocus: false,
    });
  } catch {
    vscode.window.showWarningMessage(`Source not available: ${file}`);
  }
}

/** Opens .pyprof files in the dashboard (double-click in the explorer). */
export class ProfileEditorProvider implements vscode.CustomReadonlyEditorProvider {
  static readonly viewType = 'pyprof.profileViewer';

  constructor(
    private readonly sessions: SessionManager,
    private readonly dashboards: Dashboards,
  ) {}

  openCustomDocument(uri: vscode.Uri): vscode.CustomDocument {
    return { uri, dispose: () => undefined };
  }

  async resolveCustomEditor(document: vscode.CustomDocument, panel: vscode.WebviewPanel): Promise<void> {
    try {
      const s = await this.sessions.openFile(document.uri.fsPath);
      this.dashboards.bind(s, panel);
    } catch (e) {
      panel.webview.html = `<body style="padding:20px;font-family:var(--vscode-font-family)"><h3>Cannot open profile</h3><p>${escapeHtml(String((e as Error).message ?? e))}</p></body>`;
    }
  }
}

function escapeHtml(s: string): string {
  return s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]!);
}
