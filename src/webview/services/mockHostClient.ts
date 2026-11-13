import type { Delta } from '../../shared/model';
import type { Capabilities, SessionState, ViewState, WebviewCommand, WebviewCommandArgs } from '../../shared/protocol';
import type { HostClient, HostEvent, PersistedState } from './hostClient';

export interface MockSession {
  label: string;
  state: SessionState;
  capabilities: Capabilities;
  data: Delta;
}

/** One recorded command; a union per command so `args` narrows on `command`. */
export type CommandCall = { [C in WebviewCommand]: { command: C; args: WebviewCommandArgs[C] } }[WebviewCommand];

/** Commands that need a running program, like `SessionActions.liveClient`. */
const LIVE_ONLY: ReadonlySet<WebviewCommand> = new Set(['snapshot', 'tracemalloc', 'asyncioDebug', 'objectCounts', 'mark']);

/**
 * In-memory extension host: the test backend of the dashboard.
 *
 * It behaves like `Dashboards` + `SessionActions`: `ready` is answered with
 * `init`, live-only commands fail on a finished session, toggles flip the
 * capabilities and push a `state` event, and events arrive asynchronously.
 */
export class MockHostClient implements HostClient {
  readonly commands: CommandCall[] = [];
  readonly openedSources: { file: string; line: number }[] = [];
  readonly viewStates: ViewState[] = [];
  private readonly listeners = new Set<(event: HostEvent) => void>();
  private readonly failures = new Map<WebviewCommand, string>();
  private state: PersistedState | undefined;

  constructor(
    readonly session: MockSession,
    savedState?: PersistedState,
  ) {
    this.state = savedState;
  }

  ready(): void {
    const { label, state, capabilities, data } = this.session;
    this.emit({ type: 'init', sessionId: 'mock', label, state, capabilities: { ...capabilities }, data });
  }

  onEvent(listener: (event: HostEvent) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  async runCommand<C extends WebviewCommand>(command: C, args: WebviewCommandArgs[C]): Promise<void> {
    // a generic C cannot be narrowed to one member of the union
    const call = { command, args } as CommandCall;
    this.commands.push(call);
    await Promise.resolve();
    const failure = this.failures.get(command);
    if (failure !== undefined) {
      this.failures.delete(command);
      throw new Error(failure);
    }
    const caps = this.session.capabilities;
    if (LIVE_ONLY.has(command) && !caps.live) throw new Error('This session is not live any more.');
    switch (call.command) {
      case 'stop':
        this.setState('stopped', { live: false, agent: false });
        break;
      case 'tracemalloc':
        this.setState(this.session.state, { tracemalloc: call.args.enabled ?? !caps.tracemalloc });
        break;
      case 'asyncioDebug':
        this.setState(this.session.state, { asyncioDebug: call.args.enabled ?? !caps.asyncioDebug });
        break;
      case 'snapshot':
        if (!caps.tracemalloc) this.setState(this.session.state, { tracemalloc: true });
        break;
      default:
        break;
    }
  }

  openSource(file: string, line: number): void {
    this.openedSources.push({ file, line });
  }

  sendViewState(state: ViewState): void {
    this.viewStates.push(state);
  }

  loadState(): PersistedState | undefined {
    return this.state;
  }

  saveState(state: PersistedState): void {
    this.state = state;
  }

  // ───────────────────────────────────────────── test controls

  /** The next `command` fails with `message`, as the extension would report it. */
  failNext(command: WebviewCommand, message: string): void {
    this.failures.set(command, message);
  }

  /** Push an event as the extension would (delivered asynchronously). */
  emit(event: HostEvent): void {
    queueMicrotask(() => {
      for (const listener of this.listeners) listener(event);
    });
  }

  private setState(state: SessionState, capabilities: Partial<Capabilities>): void {
    this.session.state = state;
    Object.assign(this.session.capabilities, capabilities);
    this.emit({ type: 'state', state, capabilities: { ...this.session.capabilities } });
  }
}
