/**
 * Minimal stand-in for the `vscode` module, aliased in by esbuild for tests.
 * It implements just enough for `activate()` to run outside VS Code and records
 * what the extension registers.
 */

type Listener<T> = (event: T) => unknown;

export class Disposable {
  constructor(private readonly callOnDispose: () => unknown = () => undefined) {}
  static from(...items: { dispose(): unknown }[]): Disposable {
    return new Disposable(() => items.forEach((item) => item.dispose()));
  }
  dispose(): void {
    this.callOnDispose();
  }
}

export class EventEmitter<T> {
  private listeners = new Set<Listener<T>>();
  readonly event = (listener: Listener<T>): Disposable => {
    this.listeners.add(listener);
    return new Disposable(() => this.listeners.delete(listener));
  };
  fire(event: T): void {
    for (const listener of [...this.listeners]) listener(event);
  }
  dispose(): void {
    this.listeners.clear();
  }
}

export class Uri {
  private constructor(
    readonly scheme: string,
    readonly fsPath: string,
  ) {}
  static file(path: string): Uri {
    return new Uri('file', path);
  }
  static parse(value: string): Uri {
    return new Uri('parsed', value);
  }
  static joinPath(base: Uri, ...segments: string[]): Uri {
    return new Uri(base.scheme, [base.fsPath, ...segments].join('/'));
  }
  toString(): string {
    return `${this.scheme}://${this.fsPath}`;
  }
}

export class ThemeIcon {
  constructor(
    readonly id: string,
    readonly color?: ThemeColor,
  ) {}
}
export class ThemeColor {
  constructor(readonly id: string) {}
}
export class MarkdownString {
  constructor(readonly value = '') {}
}
export class TreeItem {
  constructor(
    readonly label: string,
    readonly collapsibleState = TreeItemCollapsibleState.None,
  ) {}
}
export class Position {
  constructor(
    readonly line: number,
    readonly character: number,
  ) {}
}
export class Range {
  constructor(...readonly_args: unknown[]) {
    void readonly_args;
  }
}
export class CodeLens {
  constructor(
    readonly range: Range,
    readonly command?: unknown,
  ) {}
}

export enum TreeItemCollapsibleState {
  None,
  Collapsed,
  Expanded,
}
export enum StatusBarAlignment {
  Left = 1,
  Right,
}
export enum ViewColumn {
  Active = -1,
  Beside = -2,
  One = 1,
}
export enum OverviewRulerLane {
  Right = 4,
}
export enum ConfigurationTarget {
  Global = 1,
}
export enum ProgressLocation {
  Window = 10,
}
export enum DebugConfigurationProviderTriggerKind {
  Initial = 1,
  Dynamic,
}
export enum QuickPickItemKind {
  Separator = -1,
  Default = 0,
}
export class RelativePattern {
  constructor(
    readonly base: unknown,
    readonly pattern: string,
  ) {}
}

/** Everything the extension registered, for assertions. */
export const recorded = {
  commands: new Map<string, (...args: unknown[]) => unknown>(),
  treeViews: [] as string[],
  customEditors: [] as string[],
  debugTypes: [] as string[],
  contexts: new Map<string, unknown>(),
};

const registration = (undo: () => void = () => undefined): Disposable => new Disposable(undo);

function passiveItem(): Record<string, unknown> {
  return { show: () => undefined, hide: () => undefined, dispose: () => undefined };
}

export const window = {
  activeTextEditor: undefined,
  visibleTextEditors: [] as unknown[],
  createOutputChannel: () => ({
    info: () => undefined,
    warn: () => undefined,
    error: () => undefined,
    debug: () => undefined,
    dispose: () => undefined,
  }),
  createStatusBarItem: passiveItem,
  createTextEditorDecorationType: passiveItem,
  registerTreeDataProvider: (id: string) => {
    recorded.treeViews.push(id);
    return registration();
  },
  registerCustomEditorProvider: (viewType: string) => {
    recorded.customEditors.push(viewType);
    return registration();
  },
  onDidChangeVisibleTextEditors: () => registration(),
  showInformationMessage: () => Promise.resolve(undefined),
  showWarningMessage: () => Promise.resolve(undefined),
  showErrorMessage: () => Promise.resolve(undefined),
};

export const workspace = {
  workspaceFolders: undefined,
  textDocuments: [] as unknown[],
  getConfiguration: () => ({
    get: (_key: string, fallback?: unknown) => fallback,
    update: () => Promise.resolve(),
  }),
  onDidChangeConfiguration: () => registration(),
  getWorkspaceFolder: () => undefined,
};

export const commands = {
  registerCommand: (id: string, handler: (...args: unknown[]) => unknown) => {
    recorded.commands.set(id, handler);
    return registration(() => recorded.commands.delete(id));
  },
  executeCommand: (id: string, ...args: unknown[]) => {
    if (id === 'setContext') recorded.contexts.set(String(args[0]), args[1]);
    return Promise.resolve(undefined);
  },
};

export const debug = {
  registerDebugConfigurationProvider: (type: string) => {
    recorded.debugTypes.push(type);
    return registration();
  },
};

export const languages = {
  registerCodeLensProvider: () => registration(),
};

export const env = {
  openExternal: () => Promise.resolve(true),
};

export const extensions = {
  getExtension: () => undefined,
};
