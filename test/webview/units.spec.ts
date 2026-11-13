import { describe, expect, it } from 'vitest';
import { ProfileModel } from '../../src/shared/model';
import type { FromWebview } from '../../src/shared/protocol';
import { computeInsights, monotonicShare } from '../../src/webview/domain/insights';
import { RouteName } from '../../src/webview/router/routeNames';
import { parsePersistedState, type HostEvent, type PersistedState } from '../../src/webview/services/hostClient';
import { MockHostClient } from '../../src/webview/services/mockHostClient';
import { VsCodeHostClient, type VsCodeApi } from '../../src/webview/services/vsCodeHostClient';
import { loadDelta } from './support/mountApp';

class FakeVsCodeApi implements VsCodeApi {
  readonly sent: FromWebview[] = [];
  state: unknown;
  postMessage(message: FromWebview): void {
    this.sent.push(message);
  }
  getState(): unknown {
    return this.state;
  }
  setState(state: PersistedState): void {
    this.state = state;
  }
}

function fromExtension(data: unknown): void {
  window.dispatchEvent(new MessageEvent('message', { data }));
}

describe('VsCodeHostClient', () => {
  it('test_run_command_resolves_on_its_own_result', async () => {
    const api = new FakeVsCodeApi();
    const client = new VsCodeHostClient(api, window);

    const first = client.runCommand('snapshot', { label: 'a' });
    const second = client.runCommand('save', {});
    const [firstId, secondId] = api.sent.map((m) => (m.type === 'command' ? m.id : -1));
    fromExtension({ type: 'commandResult', id: secondId, error: 'Disk is full' });
    fromExtension({ type: 'commandResult', id: firstId });

    await expect(first).resolves.toBeUndefined();
    await expect(second).rejects.toThrow('Disk is full');
    expect(api.sent[0]).toEqual({ type: 'command', id: firstId, command: 'snapshot', args: { label: 'a' } });
  });

  it('test_pushed_events_reach_listeners_but_results_do_not', () => {
    const client = new VsCodeHostClient(new FakeVsCodeApi(), window);
    const received: HostEvent[] = [];
    const stop = client.onEvent((event) => received.push(event));

    fromExtension({ type: 'reveal', fn: 4 });
    fromExtension({ type: 'commandResult', id: 999 });
    stop();
    fromExtension({ type: 'reveal', fn: 5 });

    expect(received).toEqual([{ type: 'reveal', fn: 4 }]);
  });

  it('test_load_state_validates_what_was_saved', () => {
    const api = new FakeVsCodeApi();
    api.state = { route: '/memory', mode: 'bogus', hideLibs: true };

    expect(new VsCodeHostClient(api, window).loadState()).toEqual({
      route: '/memory',
      mode: 'wall',
      source: 'threads',
      hideLibs: true,
      byLine: false,
    });
  });
});

describe('parsePersistedState', () => {
  it('test_parse_non_object_returns_undefined', () => {
    expect(parsePersistedState(undefined)).toBeUndefined();
    expect(parsePersistedState('cpu')).toBeUndefined();
  });

  it('test_parse_keeps_valid_values', () => {
    const state: PersistedState = { route: '/cpu?view=top', mode: 'gil', source: 'async', hideLibs: false, byLine: true };

    expect(parsePersistedState(state)).toEqual(state);
  });
});

describe('MockHostClient', () => {
  it('test_live_only_command_on_finished_session_is_rejected', async () => {
    const host = new MockHostClient({
      label: 'x',
      state: 'file',
      capabilities: { agent: false, tracemalloc: false, asyncioDebug: false, live: false },
      data: loadDelta('cpu'),
    });

    await expect(host.runCommand('snapshot', {})).rejects.toThrow('not live');
    await expect(host.runCommand('save', {})).resolves.toBeUndefined();
  });
});

describe('insights', () => {
  function insightsFor(fixture: 'cpu' | 'leaky' | 'async', live = false) {
    const model = new ProfileModel();
    model.applyDelta(loadDelta(fixture));
    const counts = model.countStacks({ source: 'threads', mode: 'cpu' });
    return computeInsights({
      model,
      capabilities: { agent: false, tracemalloc: false, asyncioDebug: false, live },
      state: live ? 'running' : 'file',
      counts,
      total: model.totalWeight(counts),
    });
  }

  it('test_monotonic_share_counts_non_decreasing_steps', () => {
    expect(monotonicShare([1, 2, 2, 1, 3])).toBe(0.75);
    expect(monotonicShare([5])).toBe(0);
  });

  it('test_async_profile_reports_never_awaited_and_slow_callbacks', () => {
    const ids = insightsFor('async').map((i) => i.id);

    expect(ids).toContain('never-awaited');
    expect(ids).toContain('slow-callbacks');
  });

  it('test_insight_actions_lead_to_a_tab_or_a_function', () => {
    for (const insight of [...insightsFor('cpu'), ...insightsFor('leaky'), ...insightsFor('async')]) {
      const target = insight.action?.target;
      if (!target) continue;
      if (target.kind === 'route') expect(Object.values(RouteName)).toContain(target.route);
      else expect(target.fn).toBeGreaterThanOrEqual(0);
    }
  });

  it('test_live_session_without_agent_says_so', () => {
    expect(insightsFor('cpu', true).map((i) => i.id)).toContain('no-agent');
    expect(insightsFor('cpu', false).map((i) => i.id)).not.toContain('no-agent');
  });
});
