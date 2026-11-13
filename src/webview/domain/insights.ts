/** Automatic findings for the Overview tab, each with a link into the tab that explains it. */
import { Cat, STATUS_GIL_REQUESTED, STATUS_HAS_GIL, type ProfileModel } from '../../shared/model';
import type { Capabilities, SessionState } from '../../shared/protocol';
import { fmtBytes, fmtMs, fmtPct, maxOf, mean } from '../../shared/format';
import { RouteName } from '../router/routeNames';

export type Severity = 'bad' | 'warn' | 'info';

/** Where an insight's action leads. */
export type InsightTarget = { kind: 'route'; route: RouteName } | { kind: 'focus'; fn: number };

export interface Insight {
  id: string;
  severity: Severity;
  text: string;
  action?: { label: string; target: InsightTarget };
}

export interface InsightInput {
  model: ProfileModel;
  capabilities: Capabilities;
  state: SessionState;
  /** CPU-mode stack counts of the current selection */
  counts: Map<number, number>;
  total: number;
}

const MB = 1024 * 1024;

function route(route: RouteName): InsightTarget {
  return { kind: 'route', route };
}

function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? '' : 's'}`;
}

/** Share of steps in `values` that do not go down. */
export function monotonicShare(values: readonly number[]): number {
  let up = 0;
  for (let i = 1; i < values.length; i++) if (values[i] >= values[i - 1]) up++;
  return up / Math.max(1, values.length - 1);
}

export function computeInsights({ model: m, capabilities, state, counts, total }: InsightInput): Insight[] {
  const out: Insight[] = [];

  const top = m.topFunctions(counts).find((f) => m.fns[f.fn].cat === Cat.User);
  if (top && total > 200 && top.self / total > 0.25) {
    out.push({
      id: 'hot-function',
      severity: 'warn',
      text: `${m.fns[top.fn].func} uses ${fmtPct(top.self, total)} of CPU time in its own code (not in functions it calls).`,
      action: { label: 'Show callers & callees', target: { kind: 'focus', fn: top.fn } },
    });
  }

  let waiting = 0;
  const samples = m.samples;
  for (let i = 0; i < samples.length; i++) {
    const status = samples.status[i];
    if (status & STATUS_GIL_REQUESTED && !(status & STATUS_HAS_GIL)) waiting++;
  }
  // needs two sampled threads: with one, GIL waits come from our own agent
  if (m.threadList().length >= 2 && samples.length > 500 && waiting / samples.length > 0.15) {
    out.push({
      id: 'gil-contention',
      severity: 'warn',
      text: `Threads were waiting for the GIL in ${fmtPct(waiting, samples.length)} of samples — CPU-bound threads contend for the interpreter.`,
      action: { label: 'Open timeline', target: route(RouteName.Timeline) },
    });
  }

  const rss = m.tracks.get('rss');
  if (rss && rss.v.length >= 8) {
    const n = rss.v.length;
    const first = mean(rss.v.slice(0, Math.max(3, n / 10))) ?? 0;
    const last = mean(rss.v.slice(-Math.max(3, n / 10))) ?? 0;
    if (last > first * 1.3 && last - first > 20 * MB && monotonicShare(rss.v) > 0.6) {
      out.push({
        id: 'memory-growth',
        severity: 'bad',
        text: `Memory grew steadily from ${fmtBytes(first)} to ${fmtBytes(last)}. This looks like a leak.`,
        action: { label: m.snapshots.length >= 2 ? 'Compare snapshots' : 'Hunt it with snapshots', target: route(RouteName.Memory) },
      });
    }
  }

  const lag = m.tracks.get('loopLag');
  const blocked = lag ? lag.v.filter((v) => v > 100).length : 0;
  if (lag && blocked) {
    out.push({
      id: 'loop-blocked',
      severity: 'bad',
      text: `The event loop was blocked for more than 100 ms ${blocked === 1 ? 'once' : `${blocked} times`} (max ${fmtMs(maxOf(lag.v))}). Something synchronous runs inside a coroutine.`,
      action: { label: 'Investigate', target: route(RouteName.Async) },
    });
  }

  const never = m.events.filter((e) => e.kind === 'never-awaited').length;
  if (never) {
    out.push({
      id: 'never-awaited',
      severity: 'bad',
      text: `${never} coroutine${never > 1 ? 's were' : ' was'} never awaited.`,
      action: { label: 'Show', target: route(RouteName.Async) },
    });
  }
  const slow = m.events.filter((e) => e.kind === 'slow-callback').length;
  if (slow) {
    out.push({
      id: 'slow-callbacks',
      severity: 'warn',
      text: `${plural(slow, 'slow asyncio callback')} detected.`,
      action: { label: 'Show', target: route(RouteName.Async) },
    });
  }

  const gcPause = m.gc.reduce((sum, g) => sum + g[1], 0);
  if (m.duration > 2000 && gcPause / m.duration > 0.05) {
    out.push({
      id: 'gc-pauses',
      severity: 'warn',
      text: `Garbage collection paused the program for ${fmtMs(gcPause)} (${fmtPct(gcPause, m.duration)} of the run).`,
      action: { label: 'GC details', target: route(RouteName.Memory) },
    });
  }

  if (m.stats.samples > 100 && m.stats.errors / m.stats.samples > 0.2) {
    out.push({
      id: 'torn-samples',
      severity: 'warn',
      text: `${fmtPct(m.stats.errors, m.stats.samples)} of samples were discarded because stacks changed while being read. Enable "pyprof.blockingSampling" for consistent samples.`,
    });
  }

  if (capabilities.live && !capabilities.agent && state === 'running') {
    out.push({
      id: 'no-agent',
      severity: 'info',
      text: 'Running without the in-process agent: CPU, tasks and GC work; memory snapshots and loop lag are unavailable.',
    });
  }
  return out;
}
