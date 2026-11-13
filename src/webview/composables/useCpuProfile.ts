import { computed, type ComputedRef } from 'vue';
import type { TreeOptions } from '../../shared/model';
import { useSessionStore } from '../stores/session';
import { useViewStore } from '../stores/view';

/** Stack counts of the current selection, shared by the CPU views. */
export function useCpuProfile(): {
  counts: ComputedRef<Map<number, number>>;
  total: ComputedRef<number>;
  treeOptions: ComputedRef<TreeOptions>;
} {
  const session = useSessionStore();
  const view = useViewStore();
  const counts = computed(() => session.model.countStacks(view.filter));
  const total = computed(() => session.model.totalWeight(counts.value));
  const treeOptions = computed<TreeOptions>(() => ({ hideLibs: view.hideLibs, byLine: view.byLine }));
  return { counts, total, treeOptions };
}
