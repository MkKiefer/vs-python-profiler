import { describe, expect, it } from 'vitest';
import { mountApp, settle } from './support/mountApp';
import { buttonByText, tid } from './support/tid';

/** Finish a drag that started with a mousedown on a chart. */
function dragTo(clientX: number): void {
  window.dispatchEvent(new MouseEvent('mousemove', { clientX }));
  window.dispatchEvent(new MouseEvent('mouseup', { clientX }));
}

describe('filters', () => {
  it('test_brushing_a_chart_selects_a_time_range_for_the_extension', async () => {
    const { wrapper, router, host } = await mountApp('/overview');

    await wrapper.get('[role="img"][aria-label="CPU"]').trigger('mousedown', { clientX: 100 });
    dragTo(300);
    await settle(router);

    expect(wrapper.find(tid('range-chip')).exists()).toBe(true);
    const sent = host.viewStates.at(-1);
    expect(sent?.t0).toBeGreaterThan(0);
    expect(sent?.t1).toBeGreaterThan(sent?.t0 ?? 0);
  });

  it('test_clear_time_range_removes_the_chip', async () => {
    const { wrapper, router, host } = await mountApp('/overview');
    await wrapper.get('[role="img"][aria-label="CPU"]').trigger('mousedown', { clientX: 100 });
    dragTo(300);
    await settle(router);

    await wrapper.get('button[aria-label="Clear time range"]').trigger('click');
    await settle(router);

    expect(wrapper.find(tid('range-chip')).exists()).toBe(false);
    expect(host.viewStates.at(-1)?.t0).toBeUndefined();
  });

  it('test_a_click_without_drag_selects_nothing', async () => {
    const { wrapper, router } = await mountApp('/overview');

    await wrapper.get('[role="img"][aria-label="CPU"]').trigger('mousedown', { clientX: 100 });
    dragTo(102);
    await settle(router);

    expect(wrapper.find(tid('range-chip')).exists()).toBe(false);
  });

  it('test_mode_switch_is_reported_and_persisted', async () => {
    const { wrapper, router, host } = await mountApp('/cpu');

    const mode = wrapper.get('[role="radiogroup"][aria-label="Mode"]');
    await mode.findAll('button').filter((b) => b.text() === 'CPU')[0].trigger('click');
    await settle(router);

    expect(host.viewStates.at(-1)?.mode).toBe('cpu');
    expect(host.loadState()?.mode).toBe('cpu');
  });

  it('test_thread_filter_is_reported_to_the_extension', async () => {
    const { wrapper, router, host } = await mountApp('/cpu');
    const threads = wrapper.get('[role="group"][aria-label="All threads"]');

    await threads.findAll('input[type="checkbox"]')[0].setValue(true);
    await settle(router);

    expect(host.viewStates.at(-1)?.threads).toHaveLength(1);
    expect(wrapper.text()).toContain('1 thread');
  });

  it('test_async_flame_graph_button_groups_by_task', async () => {
    const { wrapper, router, host } = await mountApp('/async', { fixture: 'async' });

    await buttonByText(wrapper, 'Async-aware flame graph').trigger('click');
    await settle(router);

    expect(router.currentRoute.value.path).toBe('/cpu');
    expect(host.viewStates.at(-1)?.source).toBe('async');
  });
});
