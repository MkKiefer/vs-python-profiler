import { after, before, test } from 'node:test';
import assert from 'node:assert/strict';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import type { ExtensionContext } from 'vscode';
import { activate } from '../src/extension/extension';
import { recorded, Uri, workspace } from './support/vscodeStub';

// tests are bundled into dist-test/, one level below the repository root
const ROOT = path.join(__dirname, '..');

interface Manifest {
  contributes: {
    commands: { command: string }[];
    views: Record<string, { id: string }[]>;
    customEditors: { viewType: string }[];
    debuggers: { type: string }[];
  };
}

const manifest = JSON.parse(fs.readFileSync(path.join(ROOT, 'package.json'), 'utf8')) as Manifest;
const subscriptions: { dispose(): unknown }[] = [];
let storage: string;

before(() => {
  storage = fs.mkdtempSync(path.join(os.tmpdir(), 'vspyprof-test-'));
  const context = {
    extensionPath: ROOT,
    extensionUri: Uri.file(ROOT),
    storageUri: Uri.file(storage),
    globalStorageUri: Uri.file(storage),
    subscriptions,
  };
  activate(context as unknown as ExtensionContext);
});

after(() => {
  // if a timer survived disposal, the test process would not exit
  for (const subscription of subscriptions) subscription.dispose();
  fs.rmSync(storage, { recursive: true, force: true });
});

test('activation registers every command declared in package.json', () => {
  const declared = manifest.contributes.commands.map((c) => c.command).sort();

  const missing = declared.filter((id) => !recorded.commands.has(id));

  assert.deepEqual(missing, []);
});

test('activation registers no undeclared commands except the process picker variable', () => {
  const declared = new Set(manifest.contributes.commands.map((c) => c.command));

  const undeclared = [...recorded.commands.keys()].filter((id) => !declared.has(id));

  assert.deepEqual(undeclared, ['vspyprof.pickProcess']);
});

test('activation provides data for every contributed view', () => {
  const views = Object.values(manifest.contributes.views).flat().map((v) => v.id);

  assert.deepEqual([...recorded.treeViews].sort(), [...views].sort());
});

test('activation registers the profile editor and the debug type', () => {
  assert.deepEqual(recorded.customEditors, manifest.contributes.customEditors.map((e) => e.viewType));
  assert.ok(recorded.debugTypes.includes(manifest.contributes.debuggers[0].type));
});

test('activation reports that no session is live', () => {
  assert.equal(recorded.contexts.get('vspyprof.hasLiveSession'), false);
});

test('session commands without a session tell the user instead of failing', async () => {
  const stop = recorded.commands.get('vspyprof.stop');
  assert.ok(stop);

  await assert.doesNotReject(async () => {
    await stop(undefined);
  });
});

test('profiling in an untrusted workspace asks for trust instead of running Python', async () => {
  const profileFile = recorded.commands.get('vspyprof.profileFile');
  const pickProcess = recorded.commands.get('vspyprof.pickProcess');
  assert.ok(profileFile && pickProcess);
  workspace.isTrusted = false;
  recorded.warnings.length = 0;

  try {
    await profileFile(undefined);
    const picked = await pickProcess();

    assert.equal(picked, undefined);
    assert.equal(recorded.warnings.length, 2);
    assert.match(recorded.warnings[0], /trusted workspace/);
  } finally {
    workspace.isTrusted = true;
  }
});
