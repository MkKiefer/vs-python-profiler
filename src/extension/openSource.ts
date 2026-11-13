import * as vscode from 'vscode';

/** Show `file` at a 1-based `line` in the main editor column. */
export async function openSource(file: string, line: number): Promise<void> {
  try {
    const document = await vscode.workspace.openTextDocument(vscode.Uri.file(file));
    const position = new vscode.Position(Math.max(0, line - 1), 0);
    await vscode.window.showTextDocument(document, {
      viewColumn: vscode.ViewColumn.One,
      selection: new vscode.Range(position, position),
      preserveFocus: false,
    });
  } catch {
    void vscode.window.showWarningMessage(`Source not available: ${file}`);
  }
}
