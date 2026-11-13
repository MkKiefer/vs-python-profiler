import { describe, expect, it } from 'vitest';
import { RouteName } from '../../src/webview/router/routeNames';
import { mountApp, settle } from './support/mountApp';
import { buttonByText, byTid } from './support/tid';

describe('navigation', () => {
  it('test_tab_click_opens_tab_and_persists_route', async () => {
    const { wrapper, router, host } = await mountApp('/overview');

    await buttonByText(wrapper, 'Memory').trigger('click');
    await settle(router);

    expect(router.currentRoute.value.name).toBe(RouteName.Memory);
    expect(host.loadState()?.route).toBe('/memory');
  });

  it('test_number_key_switches_to_that_tab', async () => {
    const { router } = await mountApp('/overview');

    window.dispatchEvent(new KeyboardEvent('keydown', { key: '5' }));
    await settle(router);

    expect(router.currentRoute.value.name).toBe(RouteName.Timeline);
  });

  it('test_number_key_while_typing_in_search_is_ignored', async () => {
    const { wrapper, router } = await mountApp('/cpu');

    await wrapper.get('input[aria-label="Search functions / files"]').trigger('keydown', { key: '3' });
    await settle(router);

    expect(router.currentRoute.value.name).toBe(RouteName.Cpu);
  });

  it('test_cpu_tab_returns_to_last_cpu_view', async () => {
    const { wrapper, router } = await mountApp('/cpu?view=tree');

    await buttonByText(wrapper, 'Overview').trigger('click');
    await settle(router);
    await buttonByText(wrapper, 'CPU').trigger('click');
    await settle(router);

    expect(router.currentRoute.value.fullPath).toBe('/cpu?view=tree');
  });

  it('test_cpu_view_switch_is_kept_in_the_route', async () => {
    const { wrapper, router } = await mountApp('/cpu');

    await buttonByText(wrapper, 'Top functions').trigger('click');
    await settle(router);

    expect(router.currentRoute.value.query.view).toBe('top');
    expect(wrapper.text()).toContain('Self time');
  });

  it('test_reveal_from_extension_opens_callers_and_callees', async () => {
    const { wrapper, router, host } = await mountApp('/overview');
    const fn = 3;

    host.emit({ type: 'reveal', fn });
    await settle(router);

    expect(router.currentRoute.value.name).toBe(RouteName.CpuFocus);
    expect(router.currentRoute.value.params.fn).toBe(String(fn));
    expect(byTid(wrapper, 'focus-banner').text()).toContain('clear focus');
  });

  it('test_top_function_click_focuses_it_and_clear_returns', async () => {
    const { wrapper, router } = await mountApp('/cpu?view=top');
    const firstRow = wrapper.get('[data-testid^="top-functions-row-"]');
    const fn = firstRow.attributes('data-testid')?.replace('top-functions-row-', '');

    await firstRow.trigger('click');
    await settle(router);

    expect(router.currentRoute.value.name).toBe(RouteName.CpuFocus);
    expect(router.currentRoute.value.params.fn).toBe(fn);

    await buttonByText(wrapper, '✕ clear focus').trigger('click');
    await settle(router);

    expect(router.currentRoute.value.name).toBe(RouteName.Cpu);
  });

  it('test_unknown_function_in_focus_route_offers_a_way_back', async () => {
    const { wrapper } = await mountApp('/cpu/focus/99999');

    expect(wrapper.text()).toContain('This function is not in the profile.');
  });
});
