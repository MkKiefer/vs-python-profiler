import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  DEFAULT_CONFIGURATION_CHOICES,
  defaultConfiguration,
  parseLaunchConfig,
  pytestNodeId,
  splitArgs,
  uvicornTarget,
} from '../src/extension/launchConfig';

const LINES = [
  'import x',
  'class TestThing:',
  '    def helper(self): pass',
  '    def test_one(self):',
  '        assert 1',
  'async def test_two():',
  '    pass',
];
const DOCUMENT = { lineCount: LINES.length, lineAt: (n: number) => ({ text: LINES[n] }) };

test('pytestNodeId inside a test method returns Class::method', () => {
  assert.equal(pytestNodeId(DOCUMENT, 4), 'TestThing::test_one');
});

test('pytestNodeId inside a module-level async test returns its name', () => {
  assert.equal(pytestNodeId(DOCUMENT, 6), 'test_two');
});

test('pytestNodeId outside any test returns undefined', () => {
  assert.equal(pytestNodeId(DOCUMENT, 0), undefined);
});

test('splitArgs honours single and double quotes', () => {
  assert.deepEqual(splitArgs(`run "a b" 'c d' e`), ['run', 'a b', 'c d', 'e']);
});

test('parseLaunchConfig reads a debugpy launch configuration', () => {
  const config = parseLaunchConfig({
    name: 'API',
    type: 'debugpy',
    request: 'launch',
    module: 'uvicorn',
    args: ['app:main', '--port', 8000],
    cwd: '/work',
    env: { DEBUG: '1', WORKERS: 2, SKIPPED: null },
    envFile: '/work/.env',
    python: '/venv/bin/python',
  });

  assert.deepEqual(config, {
    request: 'launch',
    label: undefined,
    program: undefined,
    module: 'uvicorn',
    args: ['app:main', '--port', '8000'],
    cwd: '/work',
    env: { DEBUG: '1', WORKERS: '2' },
    envFile: '/work/.env',
    python: '/venv/bin/python',
    processId: undefined,
    profile: { rateHz: undefined, tracemalloc: undefined, asyncioDebug: undefined, native: undefined, inject: undefined },
  });
});

test('parseLaunchConfig splits a string of arguments', () => {
  assert.deepEqual(parseLaunchConfig({ program: 'app.py', args: '--name "A B"' }).args, ['--name', 'A B']);
});

test('parseLaunchConfig maps profile options to collector options', () => {
  const { profile } = parseLaunchConfig({ program: 'app.py', profile: { rateHz: 250, memory: true, asyncioDebug: true, native: false } });

  assert.deepEqual(profile, { rateHz: 250, tracemalloc: true, asyncioDebug: true, native: false, inject: undefined });
});

test('parseLaunchConfig ignores values of the wrong type', () => {
  const config = parseLaunchConfig({ program: 42, cwd: '', profile: { rateHz: 'fast', memory: 'yes' } });

  assert.equal(config.program, undefined);
  assert.equal(config.cwd, undefined);
  assert.deepEqual([config.profile.rateHz, config.profile.tracemalloc], [undefined, undefined]);
});

test('parseLaunchConfig accepts the process id as number or string', () => {
  assert.equal(parseLaunchConfig({ request: 'attach', processId: 4321 }).processId, 4321);
  assert.equal(parseLaunchConfig({ request: 'attach', processId: '4321' }).processId, 4321);
});

test('parseLaunchConfig without a usable process id leaves it undefined', () => {
  assert.equal(parseLaunchConfig({ request: 'attach', processId: '' }).processId, undefined);
  assert.equal(parseLaunchConfig({ request: 'attach', processId: 'abc' }).processId, undefined);
});

test('parseLaunchConfig treats unknown requests as launch', () => {
  assert.equal(parseLaunchConfig({}).request, 'launch');
});

test('defaultConfiguration module uses the given module name', () => {
  assert.deepEqual(defaultConfiguration('module', 'mypkg.cli'), {
    name: 'Profile: mypkg.cli',
    type: 'python-profiler',
    request: 'launch',
    module: 'mypkg.cli',
    args: [],
  });
});

test('defaultConfiguration django points at manage.py under the workspace folder', () => {
  const config = defaultConfiguration('django', 'site\\manage.py');
  assert.equal(config.program, '${workspaceFolder}/site/manage.py');
  assert.deepEqual(config.args, ['runserver', '--noreload']);
});

test('defaultConfiguration fastapi serves the app with uvicorn', () => {
  const config = defaultConfiguration('fastapi', 'app.main:app');
  assert.equal(config.module, 'uvicorn');
  assert.deepEqual(config.args, ['app.main:app', '--port', '8000']);
});

test('defaultConfiguration attach picks the process', () => {
  assert.equal(defaultConfiguration('attach').processId, '${command:pyprof.pickProcess}');
});

test('defaultConfiguration every choice parses as a launch config', () => {
  for (const { id: kind } of DEFAULT_CONFIGURATION_CHOICES) {
    const parsed = parseLaunchConfig(defaultConfiguration(kind, 'x'));
    assert.equal(parsed.request, kind === 'attach' ? 'attach' : 'launch');
  }
});

test('uvicornTarget turns a file path into module:app', () => {
  assert.equal(uvicornTarget('app/main.py'), 'app.main:app');
  assert.equal(uvicornTarget('main.py'), 'main:app');
});
