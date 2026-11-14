/** vscode-free helpers for launch handling (unit tested). */
import type { AttachOptions } from '../shared/protocol';

/** A debug configuration (ours or debugpy's) reduced to what profiling needs, with every field validated. */
export interface LaunchConfig {
  request: 'launch' | 'attach';
  /** display name for the session, if the configuration provides one */
  label?: string;
  program?: string;
  module?: string;
  args: string[];
  cwd?: string;
  env: Record<string, string>;
  envFile?: string;
  python?: string;
  processId?: number;
  profile: AttachOptions;
}

export function parseLaunchConfig(raw: Readonly<Record<string, unknown>>): LaunchConfig {
  const profile = isRecord(raw.profile) ? raw.profile : {};
  return {
    request: raw.request === 'attach' ? 'attach' : 'launch',
    label: text(raw.__label),
    program: text(raw.program),
    module: text(raw.module),
    args: Array.isArray(raw.args) ? raw.args.map(String) : typeof raw.args === 'string' ? splitArgs(raw.args) : [],
    cwd: text(raw.cwd),
    env: stringMap(raw.env),
    envFile: text(raw.envFile),
    python: text(raw.python) ?? text(raw.pythonPath),
    processId: positiveInteger(raw.processId) ?? positiveInteger(raw.pid),
    profile: {
      rateHz: typeof profile.rateHz === 'number' ? profile.rateHz : undefined,
      tracemalloc: flag(profile.memory),
      asyncioDebug: flag(profile.asyncioDebug),
      native: flag(profile.native),
      inject: flag(profile.inject),
    },
  };
}

/** Find `Class::test_fn` enclosing a line (indent based, good enough for tests). */
export function pytestNodeId(doc: { lineAt(n: number): { text: string }; lineCount: number }, line: number): string | undefined {
  let fn: string | undefined;
  let fnIndent = Infinity;
  for (let i = line; i >= 0; i--) {
    const text = doc.lineAt(i).text;
    const m = text.match(/^(\s*)(?:async\s+)?def\s+(test\w*)\s*\(/);
    if (m && !fn) {
      fn = m[2];
      fnIndent = m[1].length;
      if (fnIndent === 0) return fn;
      continue;
    }
    const c = text.match(/^(\s*)class\s+(\w+)/);
    if (fn && c && c[1].length < fnIndent) return `${c[2]}::${fn}`;
  }
  return fn;
}

/** Split a command line string into arguments, honouring single and double quotes. */
export function splitArgs(s: string): string[] {
  const out: string[] = [];
  const re = /"((?:\\.|[^"])*)"|'([^']*)'|(\S+)/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(s))) out.push(m[1] ?? m[2] ?? m[3]);
  return out;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function text(value: unknown): string | undefined {
  return typeof value === 'string' && value ? value : undefined;
}

function flag(value: unknown): boolean | undefined {
  return typeof value === 'boolean' ? value : undefined;
}

function positiveInteger(value: unknown): number | undefined {
  const n = typeof value === 'number' ? value : typeof value === 'string' ? Number(value) : NaN;
  return Number.isInteger(n) && n > 0 ? n : undefined;
}

function stringMap(value: unknown): Record<string, string> {
  const out: Record<string, string> = {};
  if (!isRecord(value)) return out;
  for (const [key, v] of Object.entries(value)) {
    if (typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean') out[key] = String(v);
  }
  return out;
}

/** The ready-made configurations offered when profiling without (or beside) a launch.json, like the Python debugger's. */
export type DefaultConfigurationKind = 'file' | 'module' | 'fastapi' | 'django' | 'pytest' | 'attach';

export interface DefaultConfigurationChoice {
  id: DefaultConfigurationKind;
  label: string;
  description: string;
}

export const DEFAULT_CONFIGURATION_CHOICES: readonly DefaultConfigurationChoice[] = [
  { id: 'file', label: 'Python File', description: 'Profile the currently active Python file' },
  { id: 'module', label: 'Module', description: "Profile a module with 'python -m'" },
  { id: 'fastapi', label: 'FastAPI', description: 'Profile a FastAPI app served by uvicorn' },
  { id: 'django', label: 'Django', description: "Profile 'manage.py runserver'" },
  { id: 'pytest', label: 'pytest', description: 'Profile the test suite' },
  { id: 'attach', label: 'Attach to Process', description: 'Profile a running Python process' },
];

/**
 * A launch.json-ready `python-profiler` configuration. `detail` is what the kind asks the user for:
 * the module name, the uvicorn app (`pkg.main:app`) or the manage.py path relative to the workspace folder.
 */
export function defaultConfiguration(kind: DefaultConfigurationKind, detail = ''): Record<string, unknown> {
  const base = { type: 'python-profiler', request: 'launch' };
  switch (kind) {
    case 'file':
      return { name: 'Profile: Current File', ...base, program: '${file}' };
    case 'module':
      return { name: `Profile: ${detail}`, ...base, module: detail, args: [] };
    case 'fastapi':
      return {
        name: 'Profile: FastAPI',
        ...base,
        module: 'uvicorn',
        args: [detail, '--port', '8000'],
        profile: { asyncioDebug: true },
      };
    case 'django':
      return {
        name: 'Profile: Django',
        ...base,
        program: `\${workspaceFolder}/${detail.split('\\').join('/')}`,
        args: ['runserver', '--noreload'],
      };
    case 'pytest':
      return { name: 'Profile: pytest', ...base, module: 'pytest', args: ['-q'] };
    case 'attach':
      return { name: 'Profile: Attach', type: 'python-profiler', request: 'attach', processId: '${command:pyprof.pickProcess}' };
  }
}

/** `app/main.py` → `app.main:app`, the uvicorn target for a FastAPI file. */
export function uvicornTarget(relativePath: string): string {
  return `${relativePath.replace(/\.py$/, '').split(/[\\/]/).join('.')}:app`;
}
