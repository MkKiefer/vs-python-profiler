/**
 * The TypeScript session layer against a real collector and a real target program.
 *
 * Needs a Python 3.15 interpreter: set VSPYPROF_TEST_PYTHON to its path, e.g.
 *   VSPYPROF_TEST_PYTHON=python/.venv/bin/python npm test
 * Without it the tests are skipped.
 */
import { after, before, test } from 'node:test';
import assert from 'node:assert/strict';
import { spawn, type ChildProcess } from 'node:child_process';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import type { LogOutputChannel } from 'vscode';
import type { PythonInfo } from '../src/extension/environment';
import { ExtPaths } from '../src/extension/paths';
import type { Session } from '../src/extension/session';
import { SessionManager } from '../src/extension/sessionManager';
import { terminals, window } from './support/vscodeStub';

// tests are bundled into dist-test/, one level below the repository root
const ROOT = path.join(__dirname, '..');
const python = process.env.VSPYPROF_TEST_PYTHON ? path.resolve(process.env.VSPYPROF_TEST_PYTHON) : undefined;
const skip = python ? false : 'set VSPYPROF_TEST_PYTHON to a Python 3.15 interpreter to run';

let storage: string;
let sessions: SessionManager;
let target: ChildProcess;
let session: Session;

async function until(condition: () => boolean, what: string, timeoutMs = 15_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (!condition()) {
    if (Date.now() > deadline) throw new Error(`timed out waiting for ${what}`);
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
}

before(async () => {
  if (!python) return;
  storage = fs.mkdtempSync(path.join(os.tmpdir(), 'vspyprof-session-'));
  sessions = new SessionManager(new ExtPaths(ROOT), window.createOutputChannel() as unknown as LogOutputChannel, storage);
  target = spawn(python, [path.join(ROOT, 'test-apps', 'cpu_bound.py'), '30'], { stdio: 'ignore' });
  await new Promise((resolve) => setTimeout(resolve, 500)); // let the interpreter start
  const info: PythonInfo = { executable: python, version: '3.15', major: 3, minor: 15, freeThreaded: false, label: 'test' };
  session = await sessions.attach(target.pid ?? 0, info, 'cpu_bound.py', { rateHz: 200 });
});

after(() => {
  if (!python) return;
  target.kill();
  sessions.dispose();
  fs.rmSync(storage, { recursive: true, force: true });
});

test('attach starts a running session that receives samples', { skip }, async () => {
  await until(() => session.model.samples.sampleCount > 50, 'samples');
  // Right after attaching, the main thread imports the injected agent; those samples are
  // dropped as profiler-internal, so the program's own main-thread functions show up a moment later.
  await until(() => session.model.fns.some((fn) => fn.func === 'fib'), 'main-thread samples');

  assert.equal(session.state, 'running');
  assert.equal(session.pid, target.pid);
  assert.equal(session.model.rateHz, 200);
});

test('the injected agent connects and reports its capability', { skip }, async () => {
  await until(() => session.capabilities.agent, 'agent connection');

  assert.deepEqual(session.capabilities, { agent: true, tracemalloc: false, asyncioDebug: false, live: true });
});

test('stop ends the session and auto-saves the profile', { skip }, async () => {
  await sessions.stop(session);
  await until(() => session.filePath !== undefined && session.client === undefined, 'auto-save and collector shutdown');

  assert.equal(session.state, 'stopped');
  assert.equal(session.live, false);
  assert.ok(fs.statSync(session.filePath ?? '').size > 0);
  assert.deepEqual(sessions.savedProfiles(), [], 'a profile that is open as a session is not listed twice');
});

test('removing the session keeps its saved profile, which opens again from disk', { skip }, async () => {
  const file = session.filePath ?? '';
  const samples = session.model.samples.sampleCount;

  await sessions.remove(session);
  const listed = sessions.savedProfiles().map((profile) => profile.file);
  const reopened = await sessions.openFile(file);

  assert.deepEqual(listed, [file]);
  assert.deepEqual(sessions.sessions, [reopened]);
  assert.equal(reopened.state, 'file');
  assert.equal(reopened.model.samples.sampleCount, samples);
  assert.equal(reopened.label, 'cpu_bound.py');
});

test('deleting a saved profile closes the session showing it', { skip }, () => {
  const [opened] = sessions.sessions;

  sessions.deleteSaved(opened.filePath ?? '');

  assert.deepEqual(sessions.sessions, []);
  assert.deepEqual(sessions.savedProfiles(), []);
  assert.equal(sessions.active, undefined);
});

test('a launched program whose terminal closes before connecting fails at once', { skip }, async () => {
  const info: PythonInfo = { executable: python ?? '', version: '3.15', major: 3, minor: 15, freeThreaded: false, label: 'test' };
  // the stub terminal runs nothing: the program never connects, as when the script is missing
  const launched = await sessions.launch({ python: info, kind: 'path', target: 'missing.py', args: [], label: 'missing.py' });
  assert.equal(launched.state, 'waiting');
  const terminal = terminals.created.at(-1);
  assert.ok(terminal);

  terminals.close(terminal, 2);

  assert.equal(launched.state, 'error');
  assert.equal(launched.error, 'The program exited with code 2 before it connected to the profiler.');
  await until(() => launched.client === undefined, 'collector shutdown');
  await sessions.remove(launched);
});

test('removing a live session waits for its auto-save', { skip }, async () => {
  const second = spawn(python ?? '', [path.join(ROOT, 'test-apps', 'cpu_bound.py'), '30'], { stdio: 'ignore' });
  try {
    await new Promise((resolve) => setTimeout(resolve, 500)); // let the interpreter start
    const info: PythonInfo = { executable: python ?? '', version: '3.15', major: 3, minor: 15, freeThreaded: false, label: 'test' };
    const live = await sessions.attach(second.pid ?? 0, info, 'cpu_bound.py', { rateHz: 200, inject: false });
    await until(() => live.model.samples.sampleCount > 50, 'samples');

    await sessions.remove(live);
    const saved = sessions.savedProfiles();

    assert.deepEqual(sessions.sessions, []);
    assert.equal(saved.length, 1, 'the auto-save finished before the collector was disposed');
    assert.ok(saved[0].size > 0);
  } finally {
    second.kill();
  }
});
