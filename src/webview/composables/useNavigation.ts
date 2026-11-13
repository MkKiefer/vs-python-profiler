import { useRouter } from 'vue-router';
import type { InsightTarget } from '../domain/insights';
import { RouteName } from '../router/routeNames';

/** Named navigation used across the dashboard. */
export function useNavigation(): {
  goTo: (route: RouteName) => void;
  focusFunction: (fn: number) => void;
  follow: (target: InsightTarget) => void;
} {
  const router = useRouter();

  function goTo(route: RouteName): void {
    void router.push({ name: route });
  }

  /** Callers and callees of one function (CPU tab). */
  function focusFunction(fn: number): void {
    void router.push({ name: RouteName.CpuFocus, params: { fn: String(fn) } });
  }

  function follow(target: InsightTarget): void {
    if (target.kind === 'focus') focusFunction(target.fn);
    else goTo(target.route);
  }

  return { goTo, focusFunction, follow };
}
