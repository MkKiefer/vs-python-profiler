import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as path from 'node:path';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as zlib from 'node:zlib';
import { parseProfile, readProfile, writeProfile } from '../src/extension/profileFile';
import { ProfileModel, type Delta, type SampleColumns } from '../src/shared/model';
import { loadProfile } from './support/fixtures';

// tests are bundled into dist-test/, one level below the repository root
const FIXTURES = path.join(__dirname, '..', 'test', 'fixtures');

/** Sample columns as plain arrays, as JSON has them (typed arrays from `toDelta()` compare unequal to arrays). */
function plain(columns: SampleColumns): Record<string, number[]> {
  return Object.fromEntries(Object.entries(columns).map(([name, values]: [string, ArrayLike<number>]) => [name, Array.from(values)]));
}

/** The decoded JSON of a recorded profile file, as `parseProfile` receives it. */
function savedProfile(): Record<string, unknown> {
  return JSON.parse(zlib.gunzipSync(fs.readFileSync(path.join(FIXTURES, 'cpu.vspyprof'))).toString()) as Record<string, unknown>;
}

test('readProfile reads a recorded profile', async () => {
  const data: Delta = await readProfile(path.join(FIXTURES, 'cpu.vspyprof'));

  assert.equal(data.format, 'vspyprof');
  assert.ok('t' in data.samples && data.samples.t.length > 1000, 'the fixtures are format 1');
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
    assert.equal(copy.samples.sampleCount, model.samples.sampleCount);
    assert.deepEqual(plain(copy.toDelta().samples), plain(model.toDelta().samples));
    assert.deepEqual(plain(copy.toDelta().asyncSamples), plain(model.toDelta().asyncSamples));
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
  const data = { ...savedProfile(), version: 3 };

  assert.throws(() => parseProfile('a.vspyprof', data), /profile format 3; .* reads up to 2/);
});

test('parseProfile rejects another kind of JSON file', () => {
  assert.throws(() => parseProfile('a.vspyprof', { format: 'speedscope' }), /a\.vspyprof is not a \.vspyprof file/);
});

test('parseProfile rejects a profile with a missing table', () => {
  const data = savedProfile();
  delete data.stacks;

  assert.throws(() => parseProfile('a.vspyprof', data), /damaged: "stacks" is not a list/);
});

/** A format 2 profile as JSON: the recorded fixture after a round through the model. */
function savedRunProfile(): Record<string, unknown> {
  const model = new ProfileModel();
  model.applyDelta(parseProfile('cpu.vspyprof', savedProfile()));
  const delta = model.toDelta();
  return { ...delta, samples: plain(delta.samples), asyncSamples: plain(delta.asyncSamples) };
}

test('parseProfile accepts a format 2 profile', () => {
  const data = parseProfile('a.vspyprof', savedRunProfile());

  assert.equal(data.version, 2);
  assert.ok('ticks' in data.samples);
});

test('parseProfile rejects runs that reach past the ticks', () => {
  const data = savedRunProfile();
  data.samples = { ticks: [1, 2], threadIds: [5], tick: [1], count: [2], thread: [0], stack: [0], status: [0] };

  assert.throws(() => parseProfile('a.vspyprof', data), /"samples" has runs outside its ticks or threads/);
});

test('parseProfile rejects runs of an unknown thread', () => {
  const data = savedRunProfile();
  data.samples = { ticks: [1, 2], threadIds: [5], tick: [0], count: [2], thread: [1], stack: [0], status: [0] };

  assert.throws(() => parseProfile('a.vspyprof', data), /"samples" has runs outside its ticks or threads/);
});

test('parseProfile rejects sample columns of different lengths', () => {
  const data = savedProfile();
  data.samples = { t: [1, 2], tid: [1, 1], stack: [0], status: [0, 0] };

  assert.throws(() => parseProfile('a.vspyprof', data), /the "samples" columns differ in length/);
});
