import * as fs from 'node:fs';
import * as path from 'node:path';
import * as zlib from 'node:zlib';
import { ProfileModel, type Delta } from '../../src/shared/model';

// tests are bundled into dist-test/, one level below the repository root
const FIXTURES = path.join(__dirname, '..', 'test', 'fixtures');

/** Load a recorded `.vspyprof` fixture: `cpu`, `leaky` or `async`. */
export function loadProfile(name: 'cpu' | 'leaky' | 'async'): ProfileModel {
  const raw = zlib.gunzipSync(fs.readFileSync(path.join(FIXTURES, `${name}.vspyprof`))).toString();
  const model = new ProfileModel();
  model.applyDelta(JSON.parse(raw) as Delta);
  return model;
}
