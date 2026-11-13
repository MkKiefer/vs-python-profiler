import { test } from 'node:test';
import assert from 'node:assert/strict';
import { toCollapsed, toSpeedscope } from '../src/shared/exporters';
import { loadProfile } from './support/fixtures';

test('collapsed stacks list frames root to leaf with a sample count', () => {
  const collapsed = toCollapsed(loadProfile('cpu'));

  assert.match(collapsed, /fib \(.*cpu_bound\.py:\d+\) \d+\n/);
});

test('collapsed stack counts add up to the number of samples', () => {
  const m = loadProfile('cpu');

  const counts = toCollapsed(m)
    .trimEnd()
    .split('\n')
    .map((line) => Number(line.slice(line.lastIndexOf(' ') + 1)));

  assert.equal(counts.reduce((a, b) => a + b, 0), m.samples.length);
});

test('speedscope export has one sampled profile per thread covering every sample', () => {
  const m = loadProfile('cpu');

  const file = toSpeedscope(m, 'run');

  assert.equal(file.name, 'run');
  assert.equal(file.profiles.length, m.threadList().length);
  assert.ok(file.profiles.every((p) => p.type === 'sampled' && p.samples.length === p.weights.length));
  assert.equal(file.profiles.reduce((n, p) => n + p.samples.length, 0), m.samples.length);
});

test('speedscope samples reference shared frames', () => {
  const file = toSpeedscope(loadProfile('cpu'), 'run');

  const indices = file.profiles.flatMap((p) => p.samples.flat());

  assert.ok(indices.every((i) => i >= 0 && i < file.shared.frames.length));
  assert.ok(file.shared.frames.some((frame) => frame.name === 'fib'));
});
