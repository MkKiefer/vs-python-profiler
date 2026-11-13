/**
 * Tabs are routes. A webview has no address bar, so the router keeps its
 * history in memory and the current path is persisted through the host client
 * (`PersistedState.route`) to survive hiding and reloading the panel.
 */
import { createMemoryHistory, createRouter, type RouteRecordRaw, type Router } from 'vue-router';
import { RouteName } from './routeNames';
import OverviewView from '../views/OverviewView.vue';
import CpuView from '../views/CpuView.vue';
import CpuFocusView from '../views/CpuFocusView.vue';
import MemoryView from '../views/MemoryView.vue';
import AsyncView from '../views/AsyncView.vue';
import TimelineView from '../views/TimelineView.vue';

export const routes: RouteRecordRaw[] = [
  { path: '/', redirect: { name: RouteName.Overview } },
  { path: '/overview', name: RouteName.Overview, component: OverviewView },
  { path: '/cpu', name: RouteName.Cpu, component: CpuView },
  { path: '/cpu/focus/:fn(\\d+)', name: RouteName.CpuFocus, component: CpuFocusView },
  { path: '/memory', name: RouteName.Memory, component: MemoryView },
  { path: '/async', name: RouteName.Async, component: AsyncView },
  { path: '/timeline', name: RouteName.Timeline, component: TimelineView },
  // empty params: the catch-all's own param must not be carried over
  { path: '/:unknown(.*)*', redirect: { name: RouteName.Overview, params: {} } },
];

export function createDashboardRouter(): Router {
  return createRouter({ history: createMemoryHistory(), routes });
}
