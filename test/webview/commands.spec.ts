import { describe, expect, it } from 'vitest';
import { mountApp, settle } from './support/mountApp';
import { buttonByText, buttonsByText, byTid } from './support/tid';

describe('session commands', () => {
  it('test_stop_live_session_shows_stopped_state', async () => {
    const { wrapper, router, host } = await mountApp('/overview', { live: true });

    await buttonByText(wrapper, '■Stop').trigger('click');
    await settle(router);

    expect(host.commands).toContainEqual({ command: 'stop', args: {} });
    expect(byTid(wrapper, 'session-state').text()).toBe('stopped');
    expect(buttonsByText(wrapper, '■Stop')).toHaveLength(0);
  });

  it('test_failed_command_shows_the_error', async () => {
    const { wrapper, router, host } = await mountApp('/overview');
    host.failNext('save', 'Disk is full');

    await buttonByText(wrapper, 'Save').trigger('click');
    await settle(router);

    expect(wrapper.get('[role="alert"]').text()).toContain('Disk is full');
    expect(buttonByText(wrapper, 'Save').attributes('disabled')).toBeUndefined();
  });

  it('test_toast_dismiss_removes_it', async () => {
    const { wrapper, router, host } = await mountApp('/overview');
    host.failNext('save', 'Disk is full');
    await buttonByText(wrapper, 'Save').trigger('click');
    await settle(router);

    await wrapper.get('[role="alert"] button[aria-label="Dismiss"]').trigger('click');

    expect(wrapper.find('[role="alert"]').exists()).toBe(false);
  });

  it('test_start_memory_tracing_flips_the_button', async () => {
    const { wrapper, router, host } = await mountApp('/memory', { fixture: 'leaky', live: true });

    await buttonByText(wrapper, 'Start memory tracing').trigger('click');
    await settle(router);

    expect(host.commands).toContainEqual({ command: 'tracemalloc', args: { enabled: true } });
    expect(buttonsByText(wrapper, 'Stop memory tracing')).toHaveLength(1);
  });

  it('test_asyncio_debug_toggle_sends_enable', async () => {
    const { wrapper, router, host } = await mountApp('/async', { fixture: 'async', live: true });

    await buttonByText(wrapper, 'Enable asyncio debug').trigger('click');
    await settle(router);

    expect(host.commands).toContainEqual({ command: 'asyncioDebug', args: { enabled: true } });
    expect(buttonsByText(wrapper, 'Disable asyncio debug')).toHaveLength(1);
  });

  it('test_saved_profile_has_no_live_actions', async () => {
    const { wrapper } = await mountApp('/memory', { fixture: 'leaky' });

    expect(buttonsByText(wrapper, '■Stop')).toHaveLength(0);
    expect(buttonsByText(wrapper, 'Start memory tracing')).toHaveLength(0);
    expect(buttonsByText(wrapper, 'Count objects')).toHaveLength(0);
  });

  it('test_live_session_without_agent_warns_on_memory_tab', async () => {
    const { wrapper } = await mountApp('/memory', { live: true, capabilities: { agent: false } });

    expect(wrapper.text()).toContain('The in-process agent is not connected');
    expect(buttonsByText(wrapper, 'Take snapshot')).toHaveLength(0);
  });
});
