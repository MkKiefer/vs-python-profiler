/**
 * The profiled session: its data model, state and capabilities, and the
 * commands that act on it.
 *
 * `ProfileModel` is large and mutated in place by deltas, so it is kept raw
 * (never deep-reactive) in a shallow ref; every change triggers that ref once,
 * and computeds that read `model` re-run.
 */
import { defineStore } from 'pinia';
import { computed, markRaw, ref, shallowRef, triggerRef } from 'vue';
import { ProfileModel, type Delta } from '../../shared/model';
import type { Capabilities, SessionState, WebviewCommand, WebviewCommandArgs } from '../../shared/protocol';
import { errorMessage } from '../../shared/errors';
import { fmtMs, isSyntheticFile } from '../../shared/format';
import type { HostEvent } from '../services/hostClient';
import { useHostClient } from '../services/hostClientKey';
import { useNotificationsStore } from './notifications';

/** Live deltas arrive several times a second; redraw at most this often. */
const LIVE_REDRAW_MS = 500;

export const useSessionStore = defineStore('session', () => {
  const host = useHostClient();
  const notifications = useNotificationsStore();

  const model = shallowRef(markRaw(new ProfileModel()));
  const loaded = ref(false);
  const label = ref('');
  const state = ref<SessionState>('starting');
  const capabilities = ref<Capabilities>({ agent: false, tracemalloc: false, asyncioDebug: false, live: false });
  /** commands sent to the extension and not answered yet */
  const running = ref(new Set<WebviewCommand>());

  const live = computed(() => capabilities.value.live);
  /** time axis of the whole session, at least one second */
  const domain = computed<[number, number]>(() => [0, Math.max(1000, model.value.duration)]);

  let redrawTimer: ReturnType<typeof setTimeout> | undefined;
  let lastRedraw = 0;

  function redrawNow(): void {
    if (redrawTimer !== undefined) clearTimeout(redrawTimer);
    redrawTimer = undefined;
    lastRedraw = performance.now();
    triggerRef(model);
  }

  function scheduleRedraw(): void {
    if (redrawTimer !== undefined) return;
    redrawTimer = setTimeout(redrawNow, Math.max(0, LIVE_REDRAW_MS - (performance.now() - lastRedraw)));
  }

  function apply(data: Delta): void {
    model.value.applyDelta(data);
  }

  function handle(event: HostEvent): void {
    switch (event.type) {
      case 'init':
        apply(event.data);
        label.value = event.label;
        state.value = event.state;
        capabilities.value = event.capabilities;
        loaded.value = true;
        redrawNow();
        break;
      case 'delta':
        apply(event.data);
        scheduleRedraw();
        break;
      case 'state':
        state.value = event.state;
        capabilities.value = event.capabilities;
        break;
      case 'reveal':
        break; // navigation: handled by the app shell
    }
  }

  /** Start listening to the extension; returns the function that stops it. */
  function connect(): () => void {
    const stop = host.onEvent(handle);
    host.ready();
    return () => {
      stop();
      if (redrawTimer !== undefined) clearTimeout(redrawTimer);
    };
  }

  /** Run a command in the extension. A failure is shown to the user; returns whether it succeeded. */
  async function run<C extends WebviewCommand>(command: C, args: WebviewCommandArgs[C]): Promise<boolean> {
    running.value.add(command);
    try {
      await host.runCommand(command, args);
      return true;
    } catch (e) {
      notifications.error(errorMessage(e));
      return false;
    } finally {
      running.value.delete(command);
    }
  }

  function isRunning(command: WebviewCommand): boolean {
    return running.value.has(command);
  }

  /** Show a frame's source; synthetic frames (`<native>`, `~`) have none. */
  function openSource(file: string, line: number): void {
    if (!isSyntheticFile(file)) host.openSource(file, line);
  }

  /** Sample count → approximate thread time. */
  function fmtSamples(samples: number): string {
    return fmtMs(samples * model.value.sampleIntervalMs);
  }

  return { model, loaded, label, state, capabilities, live, domain, connect, run, isRunning, openSource, fmtSamples };
});
