/** Reading and writing `.pyprof` files: gzip-compressed JSON in `Delta` shape. */
import * as fs from 'node:fs';
import * as zlib from 'node:zlib';
import { promisify } from 'node:util';
import type { Delta } from '../shared/model';

const gzip = promisify(zlib.gzip);
const gunzip = promisify(zlib.gunzip);

export const PROFILE_EXTENSION = 'pyprof';
const FORMAT = 'pyprof';

export async function readProfile(file: string): Promise<Delta> {
  const raw = await fs.promises.readFile(file);
  const isGzip = raw[0] === 0x1f && raw[1] === 0x8b;
  const text = (isGzip ? await gunzip(raw) : raw).toString('utf8');
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    throw new Error(`${file} is not a .pyprof file (invalid JSON)`);
  }
  if (typeof data !== 'object' || data === null || (data as { format?: unknown }).format !== FORMAT) {
    throw new Error(`${file} is not a .pyprof file`);
  }
  return data as Delta;
}

export async function writeProfile(file: string, data: Delta): Promise<void> {
  await fs.promises.writeFile(file, await gzip(Buffer.from(JSON.stringify(data), 'utf8')));
}

/** File-system safe name derived from a session label. */
export function profileFileStem(label: string): string {
  return label.replace(/[^\w.-]+/g, '_').slice(0, 60) || 'profile';
}
