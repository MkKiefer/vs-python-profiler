/**
 * What the dashboard shows: sample mode, grouping, thread and time filters.
 * These filters are shared by every tab and reported to the extension, which
 * uses them for the editor heat map and the Hotspots view.
 */
import { defineStore } from 'pinia';
import { computed, ref, watch } from 'vue';
import type { Filter, Mode, Source } from '../../shared/model';
import type { PersistedState } from '../services/hostClient';
import { useHostClient } from '../services/hostClientKey';

export type MemoryWeight = 'size' | 'count';

export const useViewStore = defineStore('view', () => {
  const host = useHostClient();

  const mode = ref<Mode>('wall');
  const source = ref<Source>('threads');
  const threads = ref<number[]>([]);
  const hideLibs = ref(false);
  const byLine = ref(false);
  const search = ref('');
  const range = ref<[number, number] | null>(null);
  /** memory tab: the snapshot shown, the one it is compared with, and the weight */
  const memorySnapshot = ref<number | undefined>(undefined);
  const memoryBaseline = ref<number | undefined>(undefined);
  const memoryWeight = ref<MemoryWeight>('size');

  const filter = computed<Filter>(() => ({
    t0: range.value?.[0],
    t1: range.value?.[1],
    mode: mode.value,
    source: source.value,
    threads: threads.value.length ? new Set(threads.value) : null,
  }));

  /** Changes whenever the shape of trees and tables changes (not on new live data). */
  const structureKey = computed(() =>
    JSON.stringify([mode.value, source.value, threads.value, hideLibs.value, byLine.value, range.value]),
  );

  function setRange(t0: number, t1: number): void {
    range.value = [Math.max(0, t0), t1];
  }

  function clearRange(): void {
    range.value = null;
  }

  function setThread(tid: number, included: boolean): void {
    const others = threads.value.filter((other) => other !== tid);
    threads.value = included ? [...others, tid] : others;
  }

  function restore(state: PersistedState): void {
    mode.value = state.mode;
    source.value = state.source;
    hideLibs.value = state.hideLibs;
    byLine.value = state.byLine;
  }

  function persisted(route: string): PersistedState {
    return { route, mode: mode.value, source: source.value, hideLibs: hideLibs.value, byLine: byLine.value };
  }

  watch([mode, source, range, threads], () => {
    host.sendViewState({
      mode: mode.value,
      source: source.value,
      t0: range.value?.[0],
      t1: range.value?.[1],
      threads: [...threads.value],
    });
  });

  return {
    mode,
    source,
    threads,
    hideLibs,
    byLine,
    search,
    range,
    memorySnapshot,
    memoryBaseline,
    memoryWeight,
    filter,
    structureKey,
    setRange,
    clearRange,
    setThread,
    restore,
    persisted,
  };
});
