/** Automatic findings for the Overview tab, each with a link into the tab that explains it. */
import { Cat, type ProfileModel } from '../../shared/model';
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

/** Share of discarded sampling attempts from which the dashboard suggests blocking sampling. */
export const TORN_SAMPLES_HINT = 0.15;

/** Share of CPU time in asyncio debug mode's traceback capture from which the dashboard points it out. */
export const ASYNCIO_DEBUG_HINT = 0.05;

/** `asyncio.format_helpers.extract_stack`: what debug mode runs for every new Handle, Future and Task. */
export function isAsyncioTracebackCapture(file: string, func: string): boolean {
  return func === 'extract_stack' && file.replaceAll('\\', '/').endsWith('/asyncio/format_helpers.py');
}

/** Share of steps in `values` that do not go down. */
export function monotonicShare(values: readonly number[]): number {
  let up = 0;
  for (let i = 1; i < values.length; i++) if (values[i] >= values[i - 1]) up++;
  return up / Math.max(1, values.length - 1);
}

export function computeInsights({ model: m, capabilities, state, counts, total }: InsightInput): Insight[] {
  const out: Insight[] = [];

  const functions = m.topFunctions(counts);
  const top = functions.find((f) => m.fns[f.fn].cat === Cat.User);
  if (top && total > 200 && top.self / total > 0.25) {
    out.push({
      id: 'hot-function',
      severity: 'warn',
      text: `${m.fns[top.fn].func} uses ${fmtPct(top.self, total)} of CPU time in its own code (not in functions it calls).`,
      action: { label: 'Show callers & callees', target: { kind: 'focus', fn: top.fn } },
    });
  }

  const debugCapture = functions.find((f) => isAsyncioTracebackCapture(m.fns[f.fn].file, m.fns[f.fn].func));
  if (debugCapture && total > 200 && debugCapture.total / total >= ASYNCIO_DEBUG_HINT) {
    out.push({
      id: 'asyncio-debug-overhead',
      severity: 'warn',
      text: `asyncio debug mode records a traceback for every task and callback: ${fmtPct(debugCapture.total, total)} of CPU time went there. Turn it off when you measure CPU time.`,
      action: { label: 'Show callers & callees', target: { kind: 'focus', fn: debugCapture.fn } },
    });
  }

  const waiting = m.countWaitingForGil();
  const sampled = m.samples.sampleCount;
  // needs two sampled threads: with one, GIL waits come from our own agent
  if (m.threadList().length >= 2 && sampled > 500 && waiting / sampled > 0.15) {
    out.push({
      id: 'gil-contention',
      severity: 'warn',
      text: `Threads were waiting for the GIL in ${fmtPct(waiting, sampled)} of samples — CPU-bound threads contend for the interpreter.`,
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

  // the share of sampling attempts, as on the overview's Samples tile; Tachyon itself discards
  // about 10 % on busy multi-threaded programs, so only clearly more than that is worth a hint
  const attempts = m.stats.samples + m.stats.errors;
  if (m.stats.samples > 100 && m.stats.errors / attempts >= TORN_SAMPLES_HINT) {
    out.push({
      id: 'torn-samples',
      severity: 'warn',
      text: `${fmtPct(m.stats.errors, attempts)} of samples were discarded because stacks changed while being read. Enable "vspyprof.blockingSampling" for consistent samples.`,
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
