import { describe, expect, it, vi } from 'vitest';
import type { Delta } from '../../src/shared/model';
import { RouteName } from '../../src/webview/router/routeNames';
import { mountApp, settle } from './support/mountApp';
import { buttonByText, byTid } from './support/tid';

/** A live delta that only moves the clock and the sampling statistics. */
function statsDelta(now: number, samples: number): Delta {
  const columns = { t: [], tid: [], stack: [], status: [] };
  return {
    now,
    frames: [],
    stacks: [],
    samples: columns,
    asyncSamples: columns,
    tracks: {},
    gc: [],
    markers: [],
    events: [],
    taskEvents: [],
    tasks: [],
    threads: {},
    snapshots: [],
    objectCounts: [],
    stats: { samples, errors: 0, rateHz: 1000 },
  };
}

function tile(wrapper: Awaited<ReturnType<typeof mountApp>>['wrapper'], label: string): string {
  return wrapper.get(`[role="group"][aria-label="${label}"]`).text();
}

describe('overview', () => {
  it('test_async_profile_insights_link_into_the_async_tab', async () => {
    const { wrapper, router } = await mountApp('/overview', { fixture: 'async' });

    expect(byTid(wrapper, 'insight-never-awaited').text()).toContain('never awaited');
    await byTid(wrapper, 'insight-never-awaited').get('button').trigger('click');
    await settle(router);

    expect(router.currentRoute.value.name).toBe(RouteName.Async);
  });

  it('test_hottest_function_click_opens_callers_and_callees', async () => {
    const { wrapper, router } = await mountApp('/overview');

    await wrapper.get('[data-testid^="hottest-row-"]').trigger('click');
    await settle(router);

    expect(router.currentRoute.value.name).toBe(RouteName.CpuFocus);
  });

  it('test_live_delta_updates_tiles_after_the_redraw_interval', async () => {
    const { wrapper, router, host } = await mountApp('/overview', { live: true });
    const before = tile(wrapper, 'Samples');

    host.emit({ type: 'delta', data: statsDelta(60_000, 123_456) });
    await settle(router);
    // deltas are coalesced: the tiles update within one redraw interval (500 ms)
    await vi.waitFor(() => expect(tile(wrapper, 'Samples')).toContain('123k'), { timeout: 2000 });

    expect(before).not.toContain('123k');
    expect(tile(wrapper, 'Duration')).toContain('1m 0s');
  });
});

describe('async tab', () => {
  it('test_slow_callbacks_are_counted_and_listed', async () => {
    const { wrapper } = await mountApp('/async', { fixture: 'async' });

    expect(tile(wrapper, 'Slow callbacks')).not.toContain('Slow callbacks0');
    expect(wrapper.findAll('[data-testid^="async-events-row-"]').length).toBeGreaterThan(0);
    expect(wrapper.findAll('[data-testid^="tasks-row-"]')).toHaveLength(17);
  });

  it('test_badge_counts_async_issues', async () => {
    const { wrapper } = await mountApp('/overview', { fixture: 'async' });

    expect(wrapper.get('[role="tab"][title^="Async"]').text()).toMatch(/^Async\d+$/);
  });
});

describe('memory tab', () => {
  it('test_two_snapshots_are_compared_by_default', async () => {
    const { wrapper } = await mountApp('/memory', { fixture: 'leaky' });

    expect(wrapper.text()).toContain('Growth before → after');
    expect(wrapper.findAll('[data-testid^="snapshot-diff-row-"]').length).toBeGreaterThan(0);
  });

  it('test_no_baseline_shows_allocation_sites', async () => {
    const { wrapper, router } = await mountApp('/memory', { fixture: 'leaky' });

    const compare = wrapper.findAll('label').find((l) => l.text().startsWith('compare with'));
    await compare?.get('select').setValue('');
    await settle(router);

    expect(wrapper.text()).toContain('Top allocation sites · after');
    expect(wrapper.text()).not.toContain('Growth before → after');
  });

  it('test_profile_without_snapshots_explains_how_to_get_them', async () => {
    const { wrapper } = await mountApp('/memory', { fixture: 'cpu' });

    expect(wrapper.text()).toContain('This profile has no memory snapshots.');
  });

  it('test_allocation_site_click_opens_source', async () => {
    const { wrapper, router, host } = await mountApp('/memory', { fixture: 'leaky' });

    await wrapper.get('[data-testid^="snapshot-diff-row-"]').trigger('click');
    await settle(router);

    expect(host.openedSources.length).toBe(1);
  });
});

describe('cpu tab', () => {
  it('test_call_tree_opens_hot_path_and_collapses_on_click', async () => {
    const { wrapper, router } = await mountApp('/cpu?view=tree');
    const expanded = wrapper.findAll('[data-testid^="call-tree-row-"][aria-expanded="true"]');
    expect(expanded.length).toBeGreaterThan(0);
    const rowsBefore = wrapper.findAll('[data-testid^="call-tree-row-"]').length;

    await expanded[0].trigger('click');
    await settle(router);

    expect(wrapper.findAll('[data-testid^="call-tree-row-"]').length).toBeLessThan(rowsBefore);
  });

  it('test_top_functions_sort_toggles_on_header_click', async () => {
    const { wrapper, router } = await mountApp('/cpu?view=top');
    const header = wrapper.findAll('th').find((th) => th.text() === 'Function');

    await header?.trigger('click');
    await settle(router);

    expect(header?.attributes('aria-sort')).toBe('ascending');
    await header?.trigger('click');
    expect(header?.attributes('aria-sort')).toBe('descending');
  });

  it('test_double_click_on_top_function_opens_source', async () => {
    const { wrapper, host } = await mountApp('/cpu?view=top');

    await wrapper.get('[data-testid^="top-functions-row-"]').trigger('dblclick');

    expect(host.openedSources).toHaveLength(1);
  });

  it('test_save_and_export_are_offered_for_saved_profiles', async () => {
    const { wrapper } = await mountApp('/cpu');

    expect(buttonByText(wrapper, 'Save').exists()).toBe(true);
    expect(buttonByText(wrapper, 'Export').exists()).toBe(true);
  });
});
