import type { FromWebview, ToWebview, ViewState, WebviewCommand, WebviewCommandArgs } from '../../shared/protocol';
import { parsePersistedState, type HostClient, type HostEvent, type PersistedState } from './hostClient';

/** The object VS Code injects into webviews (`acquireVsCodeApi()`). */
export interface VsCodeApi {
  postMessage(message: FromWebview): void;
  getState(): unknown;
  setState(state: PersistedState): void;
}

interface PendingCommand {
  resolve: () => void;
  reject: (error: Error) => void;
}

/** HostClient over the webview message channel. */
export class VsCodeHostClient implements HostClient {
  private readonly listeners = new Set<(event: HostEvent) => void>();
  private readonly pending = new Map<number, PendingCommand>();
  private nextId = 1;

  constructor(
    private readonly api: VsCodeApi,
    target: Window,
  ) {
    target.addEventListener('message', (event: MessageEvent<ToWebview>) => this.receive(event.data));
  }

  ready(): void {
    this.api.postMessage({ type: 'ready' });
  }

  onEvent(listener: (event: HostEvent) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  runCommand<C extends WebviewCommand>(command: C, args: WebviewCommandArgs[C]): Promise<void> {
    const id = this.nextId++;
    return new Promise<void>((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      // the union of per-command requests cannot be narrowed from a generic C
      this.api.postMessage({ type: 'command', id, command, args } as FromWebview);
    });
  }

  openSource(file: string, line: number): void {
    this.api.postMessage({ type: 'openSource', file, line });
  }

  sendViewState(state: ViewState): void {
    this.api.postMessage({ type: 'viewState', state });
  }

  loadState(): PersistedState | undefined {
    return parsePersistedState(this.api.getState());
  }

  saveState(state: PersistedState): void {
    this.api.setState(state);
  }

  private receive(message: ToWebview): void {
    if (message.type === 'commandResult') {
      const pending = this.pending.get(message.id);
      this.pending.delete(message.id);
      if (message.error === undefined) pending?.resolve();
      else pending?.reject(new Error(message.error));
      return;
    }
    for (const listener of this.listeners) listener(message);
  }
}
