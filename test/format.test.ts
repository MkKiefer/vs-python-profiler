import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseDotEnv } from '../src/extension/dotenv';
import { profileFileStem } from '../src/extension/profileFile';
import { errorMessage } from '../src/shared/errors';
import {
  fmtBytes,
  fmtCount,
  fmtMs,
  fmtPct,
  isSyntheticFile,
  maxOf,
  mean,
  moduleLabel,
  percentile,
  shortPath,
} from '../src/shared/format';

test('fmtBytes scales to binary units', () => {
  assert.equal(fmtBytes(512), '512 B');
  assert.equal(fmtBytes(1536), '1.5 KB');
  assert.equal(fmtBytes(300 * 1024 * 1024), '300 MB');
});

test('fmtBytes marks the sign when asked', () => {
  assert.equal(fmtBytes(2048, true), '+2.0 KB');
  assert.equal(fmtBytes(-2048, true), '−2.0 KB');
});

test('fmtBytes and fmtMs show a dash for missing values', () => {
  assert.equal(fmtBytes(undefined), '–');
  assert.equal(fmtMs(undefined), '–');
});

test('fmtMs picks a readable unit', () => {
  assert.equal(fmtMs(0.25), '250 µs');
  assert.equal(fmtMs(42), '42 ms');
  assert.equal(fmtMs(2500), '2.50 s');
  assert.equal(fmtMs(125_000), '2m 5s');
});

test('fmtPct handles an empty whole', () => {
  assert.equal(fmtPct(1, 4), '25.0%');
  assert.equal(fmtPct(1, 0), '0%');
});

test('fmtCount abbreviates thousands and millions', () => {
  assert.equal(fmtCount(999), '999');
  assert.equal(fmtCount(1500), '1.5k');
  assert.equal(fmtCount(2_500_000), '2.5M');
});

test('shortPath keeps the last path segments', () => {
  assert.equal(shortPath('/home/me/project/pkg/mod.py'), '…/pkg/mod.py');
  assert.equal(shortPath('mod.py'), 'mod.py');
});

test('moduleLabel names the package of library files', () => {
  assert.equal(moduleLabel('/venv/lib/python3.15/site-packages/requests/api.py'), 'requests');
  assert.equal(moduleLabel('/work/app.py'), 'app.py');
});

test('isSyntheticFile recognises frames without source', () => {
  assert.ok(isSyntheticFile('<native>'));
  assert.ok(isSyntheticFile('~'));
  assert.ok(isSyntheticFile(''));
  assert.ok(!isSyntheticFile('/work/app.py'));
});

test('maxOf handles arrays too large for Math.max spreading', () => {
  const values = new Float64Array(500_000).fill(1);
  values[123_456] = 7;

  assert.equal(maxOf(values), 7);
});

test('maxOf, mean and percentile return undefined for empty input', () => {
  assert.equal(maxOf([]), undefined);
  assert.equal(mean([]), undefined);
  assert.equal(percentile([], 0.99), undefined);
});

test('mean and percentile summarise values', () => {
  assert.equal(mean([1, 2, 3, 6]), 3);
  assert.equal(percentile([5, 1, 9, 3], 0.5), 5);
  assert.equal(percentile([5, 1, 9, 3], 0.99), 9);
});

test('errorMessage extracts the message of errors and stringifies the rest', () => {
  assert.equal(errorMessage(new Error('boom')), 'boom');
  assert.equal(errorMessage('plain'), 'plain');
});

test('profileFileStem makes labels file-system safe', () => {
  assert.equal(profileFileStem('pytest tests/test_api.py::TestX'), 'pytest_tests_test_api.py_TestX');
  assert.equal(profileFileStem('***'), '_');
  assert.equal(profileFileStem(''), 'profile');
});

test('parseDotEnv handles comments, export, quotes and expansion', () => {
  const env = parseDotEnv('# c\nA=1\nexport B="x y"\nC=${A}-${HOME} # comment\nD=\'raw ${A}\'', { HOME: '/h' });

  assert.deepEqual(env, { A: '1', B: 'x y', C: '1-/h', D: 'raw ${A}' });
});
