import * as vscode from 'vscode';
import type { Dashboards } from './dashboards';
import type { SessionManager } from './sessionManager';
import { errorMessage } from '../shared/errors';

/** Opens `.pyprof` files in the dashboard (double-click in the explorer). */
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
      this.dashboards.bind(await this.sessions.openFile(document.uri.fsPath), panel);
    } catch (e) {
      panel.webview.html =
        `<body style="padding:20px;font-family:var(--vscode-font-family)">` +
        `<h3>Cannot open profile</h3><p>${escapeHtml(errorMessage(e))}</p></body>`;
    }
  }
}

const HTML_ESCAPES: Record<string, string> = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' };

function escapeHtml(text: string): string {
  return text.replace(/[&<>"]/g, (c) => HTML_ESCAPES[c]);
}
