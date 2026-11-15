/**
 * The one harness of the dashboard feature specs: the whole app — real router,
 * stores and components — over a fresh in-memory extension host.
 */
import * as fs from 'node:fs';
import * as path from 'node:path';
import * as zlib from 'node:zlib';
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils';
import { createPinia } from 'pinia';
import type { Router } from 'vue-router';
import type { Delta } from '../../../src/shared/model';
import type { Capabilities, SessionState } from '../../../src/shared/protocol';
import App from '../../../src/webview/App.vue';
import { createDashboardRouter } from '../../../src/webview/router';
import { hostClientKey } from '../../../src/webview/services/hostClientKey';
import { MockHostClient } from '../../../src/webview/services/mockHostClient';

export type Fixture = 'cpu' | 'leaky' | 'async';

/** A recorded `.vspyprof` profile from test/fixtures. */
export function loadDelta(name: Fixture): Delta {
  const file = path.resolve(__dirname, '..', '..', 'fixtures', `${name}.vspyprof`);
  return JSON.parse(zlib.gunzipSync(fs.readFileSync(file)).toString()) as Delta;
}

export interface MountOptions {
  fixture?: Fixture;
  /** a running program instead of a saved profile */
  live?: boolean;
  capabilities?: Partial<Capabilities>;
}

export interface MountedApp {
  wrapper: VueWrapper;
  host: MockHostClient;
  router: Router;
}

/** Let navigation, host events and re-renders finish. */
export async function settle(router: Router): Promise<void> {
  await router.isReady();
  for (let i = 0; i < 3; i++) await flushPromises();
}

/** Open the dashboard at `path`, as if the panel was reopened there. */
export async function mountApp(path: string, options: MountOptions = {}): Promise<MountedApp> {
  const live = options.live ?? false;
  const state: SessionState = live ? 'running' : 'file';
  const capabilities: Capabilities = { agent: live, tracemalloc: false, asyncioDebug: false, live, ...options.capabilities };
  const host = new MockHostClient(
    { label: `${options.fixture ?? 'cpu'}.py`, state, capabilities, data: loadDelta(options.fixture ?? 'cpu') },
    { route: path, mode: 'wall', source: 'threads', hideLibs: false, byLine: false },
  );
  const router = createDashboardRouter();
  const wrapper = mount(App, {
    attachTo: document.body,
    global: { plugins: [createPinia(), router], provide: { [hostClientKey]: host } },
  });
  await settle(router);
  return { wrapper, host, router };
}
