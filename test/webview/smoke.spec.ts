/**
 * Opens every route with every recorded profile, saved and live. Any Vue
 * warning or console error fails the test (see support/setup.ts).
 * A new route is added to ROUTES.
 */
import { describe, expect, it } from 'vitest';
import { RouteName } from '../../src/webview/router/routeNames';
import { mountApp, type Fixture } from './support/mountApp';

const ROUTES: [path: string, name: RouteName][] = [
  ['/overview', RouteName.Overview],
  ['/cpu', RouteName.Cpu],
  ['/cpu?view=tree', RouteName.Cpu],
  ['/cpu?view=inverted', RouteName.Cpu],
  ['/cpu?view=top', RouteName.Cpu],
  ['/cpu/focus/0', RouteName.CpuFocus],
  ['/memory', RouteName.Memory],
  ['/async', RouteName.Async],
  ['/timeline', RouteName.Timeline],
];

const FIXTURES: Fixture[] = ['cpu', 'leaky', 'async'];

describe('every route renders', () => {
  for (const fixture of FIXTURES) {
    for (const live of [false, true]) {
      for (const [path, name] of ROUTES) {
        it(`${path} with the ${fixture} profile (${live ? 'live' : 'saved'})`, async () => {
          const { wrapper, router } = await mountApp(path, { fixture, live });

          expect(router.currentRoute.value.name).toBe(name);
          expect(wrapper.find('[role="tablist"]').exists()).toBe(true);
          wrapper.unmount();
        });
      }
    }
  }

  it('an unknown route falls back to the overview', async () => {
    const { router, wrapper } = await mountApp('/no-such-tab');

    expect(router.currentRoute.value.name).toBe(RouteName.Overview);
    wrapper.unmount();
  });
});
