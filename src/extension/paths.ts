import * as path from 'node:path';

/** `python -I -c COLLECTOR_BOOT <python-dir> serve` – the dir is popped from argv. */
export const COLLECTOR_BOOT =
  'import sys; sys.path.insert(0, sys.argv.pop(1)); from _vscode_pyprof.cli import main; main()';

/** Runs in the user's environment (no -I): `python -c LAUNCHER_BOOT <python-dir> run ...` */
export const LAUNCHER_BOOT =
  'import sys; sys.path.insert(0, sys.argv.pop(1)); from _vscode_pyprof.launcher import cli_main; cli_main()';

export class ExtPaths {
  constructor(readonly root: string) {}
  get python(): string {
    return path.join(this.root, 'python');
  }
  get bin(): string {
    return path.join(this.root, 'bin');
  }
  get processesScript(): string {
    return path.join(this.root, 'python', '_vscode_pyprof', 'processes.py');
  }
}
