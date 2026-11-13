/** Sidebar "Python Processes": running interpreters the profiler can attach to. */
import * as vscode from 'vscode';
import * as path from 'node:path';
import { shortTitle, type ProcessPicker, type ProcInfo } from '../processes';

type ProcessNode = ProcInfo | { empty: string };

export class ProcessesView implements vscode.TreeDataProvider<ProcessNode>, vscode.Disposable {
  private readonly changed = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData = this.changed.event;

  constructor(private readonly picker: ProcessPicker) {}

  refresh(): void {
    this.changed.fire();
  }

  async getChildren(node?: ProcessNode): Promise<ProcessNode[]> {
    if (node) return [];
    const processes = this.picker.rank(await this.picker.list());
    return processes.length ? processes : [{ empty: 'No Python processes running' }];
  }

  getTreeItem(node: ProcessNode): vscode.TreeItem {
    if ('empty' in node) return new vscode.TreeItem(node.empty);
    const item = new vscode.TreeItem(shortTitle(node));
    item.description = [String(node.pid), node.version, node.venv && path.basename(node.venv)].filter(Boolean).join(' · ');
    item.tooltip = [
      node.title,
      '',
      `PID ${node.pid} (parent ${node.ppid})`,
      node.executable,
      ...(node.cwd ? [`cwd: ${node.cwd}`] : []),
    ].join('\n');
    item.iconPath = new vscode.ThemeIcon('terminal');
    item.contextValue = 'process';
    return item;
  }

  dispose(): void {
    this.changed.dispose();
  }
}
