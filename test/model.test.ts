import { test } from 'node:test';
import assert from 'node:assert/strict';
import { Cat, ProfileModel, type TreeNode } from '../src/shared/model';
import { loadProfile } from './support/fixtures';

test('cpu profile contains the hot functions and the worker thread', () => {
  const m = loadProfile('cpu');
  const counts = m.countStacks({ mode: 'cpu' });

  const top = m.topFunctions(counts).map((f) => m.fns[f.fn].func);

  assert.ok(m.samples.length > 1000, `samples ${m.samples.length}`);
  for (const fn of ['fib', 'checksum', 'parse_rows']) assert.ok(top.includes(fn), `${fn} missing in ${top.slice(0, 10).join()}`);
  assert.ok(m.threadList().some((t) => t.name === 'checksum-worker'));
});

test('a delta with more rows than the call stack can spread loads completely', () => {
  const m = loadProfile('async');
  const rows = 300_000;
  const delta = m.toDelta();
  delta.taskEvents = Array.from({ length: rows }, (_, i): [number, number, string] => [i, 1, 'running']);
  delta.gc = Array.from({ length: rows }, (_, i): [number, number, number, number, number] => [i, 0.1, 0, 1, 100]);

  const loaded = new ProfileModel();
  loaded.applyDelta(delta);

  assert.equal(loaded.taskEvents.length, rows);
  assert.equal(loaded.gc.length, rows);
});

test('launcher and runpy frames do not leak into user stacks', () => {
  const m = loadProfile('cpu');

  const files = new Set([...m.countStacks({}).keys()].flatMap((sid) => m.path(sid).map((frame) => m.frames[frame].file)));

  assert.deepEqual([...files].filter((file) => file.includes('_vspyprof') || file.includes('runpy')), []);
});

test('call tree totals equal the number of samples', () => {
  const m = loadProfile('cpu');
  const counts = m.countStacks({});
  const total = m.totalWeight(counts);
  const sumSelf = (n: TreeNode): number => n.self + n.children.reduce((a, c) => a + sumSelf(c), 0);

  const tree = m.buildTree(counts);

  assert.equal(tree.total, total);
  assert.equal(sumSelf(tree), total);
});

test('inverted and library-hiding trees keep the total', () => {
  const m = loadProfile('cpu');
  const counts = m.countStacks({});
  const total = m.totalWeight(counts);

  assert.equal(m.buildTree(counts, { inverted: true }).total, total);
  assert.equal(m.buildTree(counts, { hideLibs: true }).total, total);
});

test('focused trees are rooted at the function and agree on its total', () => {
  const m = loadProfile('cpu');
  const counts = m.countStacks({});
  const fib = m.fns.findIndex((f) => f.func === 'fib');

  const callees = m.buildTree(counts, { focusFn: fib, focus: 'callees' });
  const callers = m.buildTree(counts, { focusFn: fib, focus: 'callers' });

  assert.equal(m.fns[callees.children[0].fn].func, 'fib');
  assert.equal(callers.total, callees.total);
});

test('cpu mode drops idle samples', () => {
  const m = loadProfile('cpu');

  const wall = m.totalWeight(m.countStacks({ mode: 'wall' }));
  const cpu = m.totalWeight(m.countStacks({ mode: 'cpu' }));

  assert.ok(cpu > 0 && cpu < wall, `cpu ${cpu}, wall ${wall}`);
});

test('time range filter selects a subset of samples', () => {
  const m = loadProfile('cpu');
  const all = m.totalWeight(m.countStacks({}));

  const firstHalf = m.totalWeight(m.countStacks({ t0: 0, t1: m.duration / 2 }));

  assert.ok(firstHalf > 0 && firstHalf < all, `first half ${firstHalf}, all ${all}`);
});

test('line heat attributes self time to the leaf line', () => {
  const m = loadProfile('cpu');
  const fibLine = 7; // return n if n < 2 else fib(n - 1) + fib(n - 2)

  const heat = m.lineHeat(m.countStacks({ mode: 'cpu' }));

  const file = [...heat.keys()].find((f) => f.endsWith('cpu_bound.py'));
  assert.ok(file, 'cpu_bound.py has no heat');
  assert.ok((heat.get(file)?.get(fibLine)?.self ?? 0) > 0);
});

test('sample interval follows the recorded sampling rate', () => {
  const m = new ProfileModel();
  assert.equal(m.sampleIntervalMs, 1);

  m.meta = { options: { rateHz: 250 } };

  assert.equal(m.rateHz, 250);
  assert.equal(m.sampleIntervalMs, 4);
});

test('snapshot diff ranks the leaking allocation site first', () => {
  const m = loadProfile('leaky');
  const [a, b] = m.snapshots;

  const diff = m.snapshotDiff(a.id, b.id);

  assert.equal(m.snapshots.length, 2);
  assert.ok(diff[0].dSize > 0);
  const where = m.userLeaf(diff[0].sid);
  assert.ok(where && ['handle_request', 'Record.__init__'].includes(where.func), where?.func);
});

test('memory profile carries allocation trees, object counts and markers', () => {
  const m = loadProfile('leaky');

  const tree = m.buildTree(m.snapshotCounts(m.snapshots[1].id));

  assert.ok(tree.total > 0);
  assert.equal(m.objectCounts.length, 1);
  assert.ok(m.objectCounts[0].counts.some(([name]) => name.endsWith('Record')));
  assert.ok(m.markers.some(([, name]) => name === 'load test'));
});

test('asyncio profile has tasks, async stacks, loop lag and debug events', () => {
  const m = loadProfile('async');

  const asyncTree = m.buildTree(m.countStacks({ source: 'async' }));

  assert.ok([...m.tasks.values()].some((t) => t.name.startsWith('worker-')));
  assert.ok(m.asyncSamples.length > 0);
  assert.ok(asyncTree.total > 0);
  assert.ok(Math.max(...(m.tracks.get('loopLag')?.v ?? [])) > 100);
  assert.ok(m.events.some((e) => e.kind === 'slow-callback'));
  assert.ok(m.taskEvents.length > 0);
});

test('frames are classified as user code or stdlib', () => {
  const m = loadProfile('async');

  assert.equal(m.frames.find((f) => f.file.includes('asyncio'))?.cat, Cat.Std);
  assert.equal(m.frames.find((f) => f.file.endsWith('async_storm.py'))?.cat, Cat.User);
});

test('toDelta round-trips through applyDelta', () => {
  const m = loadProfile('async');

  const copy = new ProfileModel();
  copy.applyDelta(m.toDelta());

  assert.equal(copy.samples.length, m.samples.length);
  assert.equal(copy.tasks.size, m.tasks.size);
  assert.deepEqual(copy.topFunctions(copy.countStacks({})).slice(0, 5), m.topFunctions(m.countStacks({})).slice(0, 5));
});
