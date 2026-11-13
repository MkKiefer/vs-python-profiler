import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as fs from 'node:fs';
import * as path from 'node:path';
import * as zlib from 'node:zlib';
import { Cat, ProfileModel, type Delta } from '../src/shared/model';
import { toCollapsed, toSpeedscope } from '../src/shared/exporters';
import { pytestNodeId, splitArgs } from '../src/extension/launch.pure';
import { parseDotEnv } from '../src/extension/dotenv';

const fixtures = path.join(__dirname, '..', 'test', 'fixtures');
function load(name: string): ProfileModel {
  const data = JSON.parse(zlib.gunzipSync(fs.readFileSync(path.join(fixtures, name))).toString()) as Delta;
  const m = new ProfileModel();
  m.applyDelta(data);
  return m;
}

test('cpu profile: hot functions and threads', () => {
  const m = load('cpu.pyprof');
  assert.ok(m.samples.length > 1000, `samples ${m.samples.length}`);
  const counts = m.countStacks({ mode: 'cpu' });
  const top = m.topFunctions(counts).map((f) => m.fns[f.fn].func);
  for (const fn of ['fib', 'checksum', 'parse_rows']) assert.ok(top.includes(fn), `${fn} in ${top.slice(0, 10)}`);
  assert.ok(m.threadList().some((t) => t.name === 'checksum-worker'));
  // no launcher/runpy frames leak into user stacks
  for (const [sid] of counts) for (const fr of m.path(sid)) assert.ok(!m.frames[fr].file.includes('_vscode_pyprof'));
});

test('tree totals are consistent; inverted and focused trees', () => {
  const m = load('cpu.pyprof');
  const counts = m.countStacks({});
  const total = m.totalWeight(counts);
  const tree = m.buildTree(counts);
  assert.equal(tree.total, total);
  const sumSelf = (n: typeof tree): number => n.self + n.children.reduce((a, c) => a + sumSelf(c), 0);
  assert.equal(sumSelf(tree), total);
  const inv = m.buildTree(counts, { inverted: true });
  assert.equal(inv.total, total);
  const fib = m.fns.findIndex((f) => f.func === 'fib');
  const callees = m.buildTree(counts, { focusFn: fib, focus: 'callees' });
  assert.equal(m.fns[callees.children[0].fn].func, 'fib');
  const callers = m.buildTree(counts, { focusFn: fib, focus: 'callers' });
  assert.equal(callers.total, callees.total);
  // hideLibs keeps only user frames + library entry frames
  const hidden = m.buildTree(counts, { hideLibs: true });
  assert.equal(hidden.total, total);
});

test('cpu mode filters idle samples, time range filter works', () => {
  const m = load('cpu.pyprof');
  const wall = m.totalWeight(m.countStacks({ mode: 'wall' }));
  const cpu = m.totalWeight(m.countStacks({ mode: 'cpu' }));
  assert.ok(cpu < wall && cpu > 0);
  const half = m.totalWeight(m.countStacks({ t0: 0, t1: m.duration / 2 }));
  assert.ok(half > 0 && half < wall);
});

test('line heat attributes self time to leaf lines', () => {
  const m = load('cpu.pyprof');
  const heat = m.lineHeat(m.countStacks({ mode: 'cpu' }));
  const file = [...heat.keys()].find((f) => f.endsWith('cpu_bound.py'))!;
  assert.ok(file);
  const lines = heat.get(file)!;
  const fibLine = 7; // return n if n < 2 else fib(n - 1) + fib(n - 2)
  assert.ok(lines.get(fibLine)!.self > 0);
});

test('memory snapshots: leak shows up in diff', () => {
  const m = load('leaky.pyprof');
  assert.equal(m.snapshots.length, 2);
  const [a, b] = m.snapshots;
  const diff = m.snapshotDiff(a.id, b.id);
  assert.ok(diff[0].dSize > 0);
  const where = m.userLeaf(diff[0].sid)!;
  assert.ok(['handle_request', 'Record.__init__'].includes(where.func), where.func);
  const tree = m.buildTree(m.snapshotCounts(b.id));
  assert.ok(tree.total > 0);
  assert.ok(m.objectCounts.length === 1 && m.objectCounts[0].counts.some(([n]) => n.endsWith('Record')));
  assert.equal(m.markers.some(([, n]) => n === 'load test'), true);
});

test('asyncio: tasks, async samples, loop lag, debug events', () => {
  const m = load('async.pyprof');
  const names = [...m.tasks.values()].map((t) => t.name);
  assert.ok(names.some((n) => n.startsWith('worker-')));
  assert.ok(m.asyncSamples.length > 0);
  const asyncTree = m.buildTree(m.countStacks({ source: 'async' }));
  assert.ok(asyncTree.total > 0);
  assert.ok(m.frames.some((f) => f.file === '<task>' || f.func.startsWith('worker-')));
  assert.ok(Math.max(...m.tracks.get('loopLag')!.v) > 100);
  assert.ok(m.events.some((e) => e.kind === 'slow-callback'));
  assert.ok(m.taskEvents.length > 0);
});

test('toDelta round-trips', () => {
  const m = load('async.pyprof');
  const m2 = new ProfileModel();
  m2.applyDelta(m.toDelta());
  assert.equal(m2.samples.length, m.samples.length);
  assert.equal(m2.tasks.size, m.tasks.size);
  assert.deepEqual(m2.topFunctions(m2.countStacks({})).slice(0, 5), m.topFunctions(m.countStacks({})).slice(0, 5));
});

test('exporters', () => {
  const m = load('cpu.pyprof');
  const collapsed = toCollapsed(m);
  assert.match(collapsed, /fib \(.*cpu_bound\.py:\d+\) \d+/);
  const sp = toSpeedscope(m, 'x') as any;
  assert.equal(sp.profiles[0].type, 'sampled');
  assert.equal(sp.profiles.reduce((a: number, p: any) => a + p.samples.length, 0), m.samples.length);
});

test('category classification', () => {
  const m = load('async.pyprof');
  const asyncioFrame = m.frames.find((f) => f.file.includes('asyncio'));
  assert.equal(asyncioFrame?.cat, Cat.Std);
  const user = m.frames.find((f) => f.file.endsWith('async_storm.py'));
  assert.equal(user?.cat, Cat.User);
});

test('pytest node ids and argument splitting', () => {
  const lines = ['import x', 'class TestThing:', '    def helper(self): pass', '    def test_one(self):', '        assert 1', 'def test_two():', '    pass'];
  const doc = { lineCount: lines.length, lineAt: (n: number) => ({ text: lines[n] }) };
  assert.equal(pytestNodeId(doc, 4), 'TestThing::test_one');
  assert.equal(pytestNodeId(doc, 6), 'test_two');
  assert.deepEqual(splitArgs(`run "a b" 'c d' e`), ['run', 'a b', 'c d', 'e']);
});

test('dotenv parsing', () => {
  const env = parseDotEnv('# c\nA=1\nexport B="x y"\nC=${A}-${HOME} # comment\nD=\'raw ${A}\'', { HOME: '/h' });
  assert.deepEqual(env, { A: '1', B: 'x y', C: '1-/h', D: 'raw ${A}' });
});
