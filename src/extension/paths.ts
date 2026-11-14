import * as path from 'node:path';

/** `python -I -c COLLECTOR_BOOT <python-dir> serve` – the dir is popped from argv. */
export const COLLECTOR_BOOT =
  'import sys; sys.path.insert(0, sys.argv.pop(1)); from _vscode_pyprof.collector.cli import main; main()';

/** Runs in the user's environment (no -I): `python -c LAUNCHER_BOOT <python-dir> (-m module | script) ...` */
export const LAUNCHER_BOOT =
  'import sys; sys.path.insert(0, sys.argv.pop(1)); from _vscode_pyprof.target.launcher import main; main()';

export class ExtPaths {
  constructor(readonly root: string) {}
  get python(): string {
    return path.join(this.root, 'python');
  }
  get processesScript(): string {
    return path.join(this.root, 'python', '_vscode_pyprof', 'processes.py');
  }
}
