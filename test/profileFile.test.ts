import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as path from 'node:path';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as zlib from 'node:zlib';
import { parseProfile, readProfile, writeProfile } from '../src/extension/profileFile';
import { ProfileModel, type Delta } from '../src/shared/model';
import { loadProfile } from './support/fixtures';

// tests are bundled into dist-test/, one level below the repository root
const FIXTURES = path.join(__dirname, '..', 'test', 'fixtures');

/** The decoded JSON of a recorded profile file, as `parseProfile` receives it. */
function savedProfile(): Record<string, unknown> {
  return JSON.parse(zlib.gunzipSync(fs.readFileSync(path.join(FIXTURES, 'cpu.vspyprof'))).toString()) as Record<string, unknown>;
}

test('readProfile reads a recorded profile', async () => {
  const data: Delta = await readProfile(path.join(FIXTURES, 'cpu.vspyprof'));

  assert.equal(data.format, 'vspyprof');
  assert.ok(data.samples.t.length > 1000);
});

test('writeProfile streams typed columns into a file that reads back the same', async () => {
  const model = loadProfile('cpu');
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'vspyprof-write-'));
  try {
    const file = path.join(directory, 'copy.vspyprof');

    await writeProfile(file, model.toDelta());
    const copy = new ProfileModel();
    copy.applyDelta(await readProfile(file));

    assert.deepEqual(fs.readdirSync(directory), ['copy.vspyprof'], 'no temporary file is left behind');
    assert.equal(copy.samples.length, model.samples.length);
    assert.deepEqual(Array.from(copy.samples.t.subarray(0, copy.samples.length)), Array.from(model.samples.t.subarray(0, model.samples.length)));
    assert.deepEqual(Array.from(copy.samples.tid.subarray(0, 100)), Array.from(model.samples.tid.subarray(0, 100)));
    assert.deepEqual(copy.toDelta().stacks, model.toDelta().stacks);
    assert.deepEqual(copy.meta, model.meta);
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
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
