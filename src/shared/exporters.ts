/** Export formats understood by other tools. */
import type { ProfileModel } from './model';

/** Brendan Gregg collapsed stacks: `root;child;leaf count` (flamegraph.pl, speedscope, inferno). */
export function toCollapsed(model: ProfileModel): string {
  const counts = model.countStacks({});
  const lines: string[] = [];
  for (const [sid, n] of counts) {
    const names = model.path(sid).map((fr) => {
      const f = model.frames[fr];
      return `${f.func} (${f.file}:${f.line})`.replace(/;/g, ',');
    });
    lines.push(`${names.join(';')} ${n}`);
  }
  return lines.join('\n') + '\n';
}

/** The subset of speedscope's file format we write (sampled profiles). */
export interface SpeedscopeFile {
  $schema: string;
  name: string;
  exporter: string;
  shared: { frames: { name: string; file: string; line: number }[] };
  profiles: {
    type: 'sampled';
    name: string;
    unit: 'milliseconds';
    startValue: number;
    endValue: number;
    samples: number[][];
    weights: number[];
  }[];
}

/** speedscope sampled profile, one profile per thread. https://www.speedscope.app */
export function toSpeedscope(model: ProfileModel, name: string): SpeedscopeFile {
  const frameIndex = new Map<number, number>();
  const frames: { name: string; file: string; line: number }[] = [];
  const idx = (fr: number) => {
    let i = frameIndex.get(fr);
    if (i === undefined) {
      const f = model.frames[fr];
      i = frames.length;
      frames.push({ name: f.func, file: f.file, line: f.line });
      frameIndex.set(fr, i);
    }
    return i;
  };
  const interval = model.sampleIntervalMs;
  const byThread = new Map<number, { samples: number[][]; weights: number[]; start: number; end: number }>();
  const t = model.samples;
  for (let i = 0; i < t.length; i++) {
    const tid = t.tid[i];
    let p = byThread.get(tid);
    if (!p) byThread.set(tid, (p = { samples: [], weights: [], start: t.t[i], end: t.t[i] }));
    p.samples.push(model.path(t.stack[i]).map(idx));
    p.weights.push(interval);
    p.end = t.t[i] + interval;
  }
  return {
    $schema: 'https://www.speedscope.app/file-format-schema.json',
    name,
    exporter: 'vscode-python-profiler',
    shared: { frames },
    profiles: [...byThread].map(([tid, p]) => ({
      type: 'sampled' as const,
      name: model.threadName(tid),
      unit: 'milliseconds' as const,
      startValue: p.start,
      endValue: p.end,
      samples: p.samples,
      weights: p.weights,
    })),
  };
}
