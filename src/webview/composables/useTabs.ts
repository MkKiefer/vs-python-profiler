import { computed, ref, watch, type ComputedRef } from 'vue';
import { useRoute, type RouteLocationRaw } from 'vue-router';
import { RouteName } from '../router/routeNames';
import { useSessionStore } from '../stores/session';

export interface TabEntry {
  route: RouteName;
  label: string;
  badge?: string;
  active: boolean;
  /** where the tab leads: the CPU tab returns to the CPU view last shown */
  target: RouteLocationRaw;
}

const TABS: readonly [RouteName, string][] = [
  [RouteName.Overview, 'Overview'],
  [RouteName.Cpu, 'CPU'],
  [RouteName.Memory, 'Memory'],
  [RouteName.Async, 'Async'],
  [RouteName.Timeline, 'Timeline'],
];

const CPU_ROUTES: ReadonlySet<unknown> = new Set([RouteName.Cpu, RouteName.CpuFocus]);

/** The dashboard's top-level tabs with their badges. */
export function useTabs(): ComputedRef<TabEntry[]> {
  const route = useRoute();
  const session = useSessionStore();
  const lastCpu = ref<RouteLocationRaw>({ name: RouteName.Cpu });

  watch(
    () => route.fullPath,
    () => {
      if (CPU_ROUTES.has(route.name)) lastCpu.value = route.fullPath;
    },
    { immediate: true },
  );

  return computed(() => {
    const model = session.model;
    const asyncIssues = model.events.filter((e) => e.kind === 'slow-callback' || e.kind === 'never-awaited').length;
    const badges: Partial<Record<RouteName, string>> = {};
    if (asyncIssues) badges[RouteName.Async] = String(asyncIssues);
    if (model.snapshots.length) badges[RouteName.Memory] = String(model.snapshots.length);
    return TABS.map(([name, label]) => {
      const cpu = name === RouteName.Cpu;
      return {
        route: name,
        label,
        badge: badges[name],
        active: cpu ? CPU_ROUTES.has(route.name) : route.name === name,
        target: cpu ? lastCpu.value : { name },
      };
    });
  });
}
