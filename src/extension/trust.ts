/**
 * Workspace Trust. Profiling runs the workspace's interpreter, so every command
 * that starts a process needs a trusted workspace. Opening saved profiles and
 * browsing sessions only read data and work in Restricted Mode too
 * (`capabilities.untrustedWorkspaces` in package.json).
 */
import * as vscode from 'vscode';

const MANAGE = 'Manage Workspace Trust';

export const workspaceTrust = {
  get trusted(): boolean {
    return vscode.workspace.isTrusted;
  },

  /** True when the workspace is trusted; otherwise tells the user why `action` is unavailable. */
  require(action: string): boolean {
    if (vscode.workspace.isTrusted) return true;
    void vscode.window
      .showWarningMessage(`Python Profiler: ${action} runs Python from this workspace, which needs a trusted workspace.`, MANAGE)
      .then((choice) => {
        if (choice === MANAGE) void vscode.commands.executeCommand('workbench.trust.manage');
      });
    return false;
  },

  onDidGrant(listener: () => void): vscode.Disposable {
    return vscode.workspace.onDidGrantWorkspaceTrust(listener);
  },
};
