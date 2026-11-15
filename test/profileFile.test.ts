import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as path from 'node:path';
import { parseProfile, readProfile } from '../src/extension/profileFile';
import type { Delta } from '../src/shared/model';
import { loadProfile } from './support/fixtures';

// tests are bundled into dist-test/, one level below the repository root
const FIXTURES = path.join(__dirname, '..', 'test', 'fixtures');

function savedProfile(): Record<string, unknown> {
  return { ...loadProfile('cpu').toDelta() };
}

test('readProfile reads a recorded profile', async () => {
  const data: Delta = await readProfile(path.join(FIXTURES, 'cpu.vspyprof'));

  assert.equal(data.format, 'vspyprof');
  assert.ok(data.samples.t.length > 1000);
});

test('parseProfile accepts a profile without a version (format 1)', () => {
  const data = savedProfile();
  delete data.version;

  assert.equal(parseProfile('a.vspyprof', data).format, 'vspyprof');
});

test('parseProfile rejects a profile from a newer format version', () => {
  const data = { ...savedProfile(), version: 2 };

  assert.throws(() => parseProfile('a.vspyprof', data), /profile format 2; .* reads up to 1/);
});

test('parseProfile rejects another kind of JSON file', () => {
  assert.throws(() => parseProfile('a.vspyprof', { format: 'speedscope' }), /a\.vspyprof is not a \.vspyprof file/);
});

test('parseProfile rejects a profile with a missing table', () => {
  const data = savedProfile();
  delete data.stacks;

  assert.throws(() => parseProfile('a.vspyprof', data), /damaged: "stacks" is not a list/);
});

test('parseProfile rejects sample columns of different lengths', () => {
  const data = savedProfile();
  data.samples = { t: [1, 2], tid: [1, 1], stack: [0], status: [0, 0] };

  assert.throws(() => parseProfile('a.vspyprof', data), /the "samples" columns differ in length/);
});
