/** Reading and writing `.vspyprof` files: gzip-compressed JSON in `Delta` shape. */
import * as fs from 'node:fs';
import * as zlib from 'node:zlib';
import { Readable } from 'node:stream';
import { pipeline } from 'node:stream/promises';
import { promisify } from 'node:util';
import { MAX_RUN, PROFILE_FORMAT, PROFILE_FORMAT_VERSION, type Delta, type RunColumns } from '../shared/model';

const gunzip = promisify(zlib.gunzip);

export const PROFILE_EXTENSION = 'vspyprof';

export async function readProfile(file: string): Promise<Delta> {
  const raw = await fs.promises.readFile(file);
  const isGzip = raw[0] === 0x1f && raw[1] === 0x8b;
  const text = (isGzip ? await gunzip(raw) : raw).toString('utf8');
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    throw new Error(`${file} is not a .vspyprof file (invalid JSON)`);
  }
  return parseProfile(file, data);
}

const LIST_KEYS = ['frames', 'stacks', 'gc', 'markers', 'events', 'taskEvents', 'tasks', 'snapshots', 'objectCounts'] as const;
const RECORD_KEYS = ['tracks', 'threads'] as const;
const SAMPLE_KEYS = ['samples', 'asyncSamples'] as const;
/** the per-sample columns of format 1, and the per-run columns of format 2 */
const LEGACY_COLUMN_KEYS = ['t', 'tid', 'stack', 'status'] as const;
const RUN_COLUMN_KEYS = ['tick', 'count', 'thread', 'stack', 'status'] as const;

/**
 * Check that decoded JSON is a profile this version can show, so a damaged file or one from a newer
 * version fails here with a clear message instead of somewhere inside `ProfileModel.applyDelta`.
 */
export function parseProfile(file: string, data: unknown): Delta {
  if (!isRecord(data) || data.format !== PROFILE_FORMAT) throw new Error(`${file} is not a .vspyprof file`);
  const version = data.version ?? 1;
  if (typeof version !== 'number' || version > PROFILE_FORMAT_VERSION) {
    throw new Error(`${file} was saved in profile format ${JSON.stringify(version)}; this version of the extension reads up to ${PROFILE_FORMAT_VERSION}. Update the extension.`);
  }
  const damaged = (what: string): Error => new Error(`${file} is damaged: ${what}`);
  if (typeof data.now !== 'number') throw damaged('"now" is not a number');
  for (const key of LIST_KEYS) if (!Array.isArray(data[key])) throw damaged(`"${key}" is not a list`);
  for (const key of RECORD_KEYS) if (!isRecord(data[key])) throw damaged(`"${key}" is not an object`);
  for (const key of SAMPLE_KEYS) {
    const columns = data[key];
    if (!isRecord(columns)) throw damaged(`"${key}" is not an object`);
    const list = (name: string): unknown[] => {
      const values = columns[name];
      if (!Array.isArray(values)) throw damaged(`"${key}.${name}" is not a list`);
      return values;
    };
    const rows = (version >= 2 ? RUN_COLUMN_KEYS : LEGACY_COLUMN_KEYS).map(list);
    if (rows.some((column) => column.length !== rows[0].length)) throw damaged(`the "${key}" columns differ in length`);
    if (version >= 2) checkRuns(list('tick'), list('count'), list('thread'), list('ticks').length, list('threadIds').length, () => damaged(`"${key}" has runs outside its ticks or threads`));
  }
  // the checks above cover what applyDelta reads; the rest is the collector's side of the format
  return data as unknown as Delta;
}

/** Every run must lie within the ticks and name a known thread, or queries would read past the tables. */
function checkRuns(tick: unknown[], count: unknown[], thread: unknown[], ticks: number, threads: number, damaged: () => Error): void {
  for (let row = 0; row < tick.length; row++) {
    const start = tick[row];
    const length = count[row];
    const index = thread[row];
    if (typeof start !== 'number' || typeof length !== 'number' || typeof index !== 'number') throw damaged();
    if (start < 0 || length < 1 || length > MAX_RUN || start + length > ticks || index < 0 || index >= threads) throw damaged();
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/**
 * Write a profile as gzip-compressed JSON. Streamed: the sample columns (typed arrays from `toDelta()`)
 * are written chunk by chunk, so a long recording never becomes one JSON string in memory. The file is
 * replaced atomically, so a failed save never leaves a truncated profile behind.
 */
export async function writeProfile(file: string, data: Delta): Promise<void> {
  const temporary = `${file}.tmp`;
  try {
    await pipeline(Readable.from(profileText(data)), zlib.createGzip(), fs.createWriteStream(temporary));
    await fs.promises.rename(temporary, file);
  } catch (e) {
    await fs.promises.rm(temporary, { force: true });
    throw e;
  }
}

const COLUMN_CHUNK = 65_536;
const SAMPLE_TABLES: ReadonlySet<string> = new Set(['samples', 'asyncSamples']);

/** The JSON text of a profile, in pieces. */
function* profileText(data: Delta): Generator<string> {
  yield '{';
  let first = true;
  for (const [key, value] of Object.entries(data)) {
    if (value === undefined) continue; // JSON.stringify leaves such keys out as well
    yield `${first ? '' : ','}${JSON.stringify(key)}:`;
    first = false;
    if (SAMPLE_TABLES.has(key)) yield* columnsText(value as RunColumns);
    else yield JSON.stringify(value);
  }
  yield '}';
}

function* columnsText(columns: RunColumns): Generator<string> {
  yield '{';
  let first = true;
  for (const [name, values] of Object.entries(columns) as [string, RunColumns[keyof RunColumns]][]) {
    yield `${first ? '' : ','}${JSON.stringify(name)}:[`;
    first = false;
    for (let start = 0; start < values.length; start += COLUMN_CHUNK) {
      yield (start ? ',' : '') + values.slice(start, start + COLUMN_CHUNK).join(',');
    }
    yield ']';
  }
  yield '}';
}

/** File-system safe name derived from a session label. */
export function profileFileStem(label: string): string {
  return label.replace(/[^\w.-]+/g, '_').slice(0, 60) || 'profile';
}
