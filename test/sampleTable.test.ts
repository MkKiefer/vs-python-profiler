import { test } from 'node:test';
import assert from 'node:assert/strict';
import { MAX_RUN, SampleTable, type LegacyColumns, type RunColumns } from '../src/shared/sampleTable';

interface Sample {
  tick: number;
  tid: number;
  stack: number;
  status: number;
}

/** A small deterministic random generator (mulberry32), so failures reproduce. */
function random(seed: number): () => number {
  let state = seed;
  return () => {
    state = (state + 0x6d2b79f5) | 0;
    let t = Math.imul(state ^ (state >>> 15), 1 | state);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Threads that mostly keep their stack and status, sampled at uneven times, some ticks missing threads. */
function recording(seed: number, ticks: number): { times: number[]; samples: Sample[] } {
  const next = random(seed);
  const times: number[] = [];
  const samples: Sample[] = [];
  const current = [0, 1, 2, 3].map((thread) => ({ tid: 1000 + thread, stack: 1, status: 3 }));
  let t = 0;
  for (let tick = 0; tick < ticks; tick++) {
    t += 0.5 + next();
    times.push(Math.round(t * 1000) / 1000);
    for (const thread of current) {
      if (next() < 0.05) Object.assign(thread, { stack: 1 + Math.floor(next() * 3), status: next() < 0.5 ? 0 : 3 });
      if (next() > 0.03) samples.push({ tick, tid: thread.tid, stack: thread.stack, status: thread.status });
    }
  }
  return { times, samples };
}

/** Format 1: one row per sample. */
function legacy({ times, samples }: { times: number[]; samples: Sample[] }): LegacyColumns {
  return {
    t: samples.map((s) => times[s.tick]),
    tid: samples.map((s) => s.tid),
    stack: samples.map((s) => s.stack),
    status: samples.map((s) => s.status),
  };
}

/** Format 2 the way `SampleRuns` writes it: runs close when broken or at MAX_RUN, rows ordered by last tick. */
function encoded({ times, samples }: { times: number[]; samples: Sample[] }): RunColumns {
  const threadIds: number[] = [];
  const columns: RunColumns = { ticks: times, threadIds, tick: [], count: [], thread: [], stack: [], status: [] };
  const write = (thread: number, stack: number, status: number, start: number, count: number): void => {
    (columns.tick as number[]).push(start);
    (columns.count as number[]).push(count);
    (columns.thread as number[]).push(thread);
    (columns.stack as number[]).push(stack);
    (columns.status as number[]).push(status);
  };
  let open = new Map<string, { thread: number; stack: number; status: number; start: number; count: number }>();
  for (let tick = 0; tick < times.length; tick++) {
    const seen = new Map<string, { thread: number; stack: number; status: number; start: number; count: number }>();
    for (const s of samples.filter((sample) => sample.tick === tick)) {
      let thread = threadIds.indexOf(s.tid);
      if (thread < 0) thread = threadIds.push(s.tid) - 1;
      const key = `${thread}/${s.stack}/${s.status}`;
      const run = open.get(key);
      if (run && run.count < MAX_RUN) {
        run.count++;
        seen.set(key, run);
        open.delete(key);
      } else {
        if (run) write(run.thread, run.stack, run.status, run.start, run.count);
        open.delete(key);
        seen.set(key, { thread, stack: s.stack, status: s.status, start: tick, count: 1 });
      }
    }
    for (const run of open.values()) write(run.thread, run.stack, run.status, run.start, run.count);
    open = seen;
  }
  for (const run of open.values()) write(run.thread, run.stack, run.status, run.start, run.count);
  return columns;
}

/** Stack counts in `[t0, t1)` by brute force over the raw samples. */
function bruteForce(times: number[], samples: Sample[], t0: number, t1: number, status?: number): Map<number, number> {
  const counts = new Map<number, number>();
  for (const s of samples) {
    const t = times[s.tick];
    if (t < t0 || t >= t1 || (status !== undefined && !(s.status & status))) continue;
    counts.set(s.stack, (counts.get(s.stack) ?? 0) + 1);
  }
  return counts;
}

function counted(table: SampleTable, t0: number, t1: number, status?: number): Map<number, number> {
  const counts = new Map<number, number>();
  table.forEachRun(t0, t1, (row, first, last) => {
    if (status !== undefined && !(table.status[row] & status)) return;
    counts.set(table.stack[row], (counts.get(table.stack[row]) ?? 0) + last - first + 1);
  });
  return counts;
}

const sorted = (counts: Map<number, number>): [number, number][] => [...counts].sort((a, b) => a[0] - b[0]);

test('both formats count exactly the samples of any time range', () => {
  const data = recording(42, 2000);
  const runs = new SampleTable();
  runs.append(encoded(data));
  const rows = new SampleTable();
  rows.append(legacy(data));
  const next = random(7);
  const end = data.times[data.times.length - 1] + 1;

  for (let i = 0; i < 300; i++) {
    const a = next() * end;
    const b = next() * end;
    const [t0, t1] = a < b ? [a, b] : [b, a];
    const status = next() < 0.5 ? 2 : undefined;
    const expected = sorted(bruteForce(data.times, data.samples, t0, t1, status));
    assert.deepEqual(sorted(counted(runs, t0, t1, status)), expected, `runs, range ${t0}..${t1}`);
    assert.deepEqual(sorted(counted(rows, t0, t1, status)), expected, `rows, range ${t0}..${t1}`);
  }
  assert.equal(runs.sampleCount, data.samples.length);
  assert.ok(runs.length * 5 < data.samples.length, `${runs.length} runs for ${data.samples.length} samples`);
});

test('runs delivered in several deltas count like one', () => {
  const data = recording(3, 600);
  const whole = encoded(data);
  const table = new SampleTable();
  // split the rows and ticks at the run boundary where the first half's ticks end
  const split = 300;
  const rows = (whole.tick as number[]).map((tick, row) => ({ tick, row })).filter(({ tick, row }) => tick + whole.count[row] - 1 < split);
  const cut = rows.length;
  const slice = (values: ArrayLike<number>, from: number, to?: number): number[] => Array.from(values).slice(from, to);
  const part = (from: number, to: number | undefined, tickFrom: number, tickTo: number | undefined, threadIds: number[]): RunColumns => ({
    ticks: slice(whole.ticks, tickFrom, tickTo),
    threadIds,
    tick: slice(whole.tick, from, to),
    count: slice(whole.count, from, to),
    thread: slice(whole.thread, from, to),
    stack: slice(whole.stack, from, to),
    status: slice(whole.status, from, to),
  });
  // rows are ordered by last tick, so the first `cut` rows are exactly those ending before `split`
  table.append(part(0, cut, 0, split, whole.threadIds));
  table.append(part(cut, undefined, split, undefined, []));

  assert.equal(table.sampleCount, data.samples.length);
  assert.deepEqual(sorted(counted(table, 0, Infinity)), sorted(bruteForce(data.times, data.samples, 0, Infinity)));
});

test('typed columns from toColumns are taken over and later rows append after them', () => {
  const source = new SampleTable();
  source.append(encoded(recording(5, 100)));
  const copy = new SampleTable();

  copy.append(source.toColumns());
  const first = copy.append({ ticks: [1e6], threadIds: [], tick: [copy.tickCount], count: [1], thread: [0], stack: [9], status: [0] });

  assert.equal(first, source.length);
  assert.equal(copy.sampleCount, source.sampleCount + 1);
  assert.deepEqual(sorted(counted(copy, 1e6, Infinity)), [[9, 1]]);
});

test('threads are found by id', () => {
  const table = new SampleTable();
  table.append({ t: [1, 1, 2], tid: [0x7f000002, 0x7f000001, 0x7f000002], stack: [1, 2, 1], status: [0, 0, 0] });

  assert.equal(table.threadId(table.indexOfThread(0x7f000001)), 0x7f000001);
  assert.equal(table.indexOfThread(42), -1);
  assert.equal(table.tickCount, 2);
});
