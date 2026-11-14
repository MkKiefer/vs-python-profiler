import * as esbuild from 'esbuild';
import { readdirSync } from 'node:fs';

// Builds the extension host (and its node tests). The webview is built by Vite: see vite.config.ts.

// Vite needs Node.js ^20.19.0 || >=22.12.0 (package.json "engines.node"). Every npm script
// that builds starts here, so an older Node fails with this message instead of a Vite stack trace.
const [major, minor] = process.versions.node.split('.').map(Number);
if (!((major === 20 && minor >= 19) || (major === 22 && minor >= 12) || major > 22)) {
  console.error(
    `Node.js ${process.versions.node} is too old for this build: it needs ^20.19.0 or >=22.12.0 (${process.execPath}).\n` +
      'If you use nvm: it is loaded only in interactive shells, so VS Code tasks may get the system Node instead. ' +
      'See "Development" in README.md.',
  );
  process.exit(1);
}

const production = process.argv.includes('--production');
const watch = process.argv.includes('--watch');
const tests = process.argv.includes('--tests');

const common = { bundle: true, sourcemap: !production, minify: production, logLevel: 'info' };

const builds = tests
  ? [{
      ...common,
      entryPoints: readdirSync('test').filter((f) => f.endsWith('.test.ts')).map((f) => `test/${f}`),
      outdir: 'dist-test', platform: 'node', format: 'cjs', target: 'node20', outExtension: { '.js': '.cjs' },
      // tests run outside VS Code: the extension gets a stub of its API
      alias: { vscode: './test/support/vscodeStub.ts' },
    }]
  : [
      {
        ...common,
        entryPoints: ['src/extension/extension.ts'],
        outfile: 'dist/extension.js',
        platform: 'node', format: 'cjs', target: 'node20',
        external: ['vscode'],
      },
    ];

if (watch) {
  for (const b of builds) (await esbuild.context(b)).watch();
  // the webview is built by Vite (vite.config.ts); watch it in the same process
  const { build } = await import('vite');
  await build({ mode: 'development', build: { watch: {} } });
} else {
  await Promise.all(builds.map((b) => esbuild.build(b)));
}
