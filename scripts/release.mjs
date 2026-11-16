// Prepares a release: bumps the version everywhere it lives and moves the
// CHANGELOG's [Unreleased] entries under the new version.
//
//   npm run release -- patch|minor|major|X.Y.Z
//
// It only edits files; commit them, merge to main, then run the "Release"
// workflow (Actions -> Release -> Run workflow) or push the tag vX.Y.Z.
import { readFileSync, writeFileSync } from 'node:fs';
import { argv, exit } from 'node:process';

const SEMVER = /^(\d+)\.(\d+)\.(\d+)$/;

function fail(message) {
  console.error(`release: ${message}`);
  exit(1);
}

function nextVersion(current, bump) {
  const match = SEMVER.exec(current);
  if (match === null) fail(`current version "${current}" is not X.Y.Z`);
  const [major, minor, patch] = match.slice(1).map(Number);
  switch (bump) {
    case 'major':
      return `${major + 1}.0.0`;
    case 'minor':
      return `${major}.${minor + 1}.0`;
    case 'patch':
      return `${major}.${minor}.${patch + 1}`;
    default:
      if (!SEMVER.test(bump)) fail(`expected patch, minor, major or X.Y.Z, got "${bump ?? ''}"`);
      return bump;
  }
}

/** Replaces exactly one occurrence of `search`, so a format change fails loudly instead of silently. */
function replaceOnce(file, text, search, replacement) {
  const count = text.split(search).length - 1;
  if (count !== 1) fail(`${file}: expected one match of ${JSON.stringify(search)}, found ${count}`);
  return text.replace(search, () => replacement);
}

function edit(file, transform) {
  writeFileSync(file, transform(readFileSync(file, 'utf8')));
  console.log(`  updated ${file}`);
}

const current = JSON.parse(readFileSync('package.json', 'utf8')).version;
const version = nextVersion(current, argv[2]);
if (version === current) fail(`version is already ${current}`);

const changelog = readFileSync('CHANGELOG.md', 'utf8');
const unreleased = /^## \[Unreleased\]\n([\s\S]*?)(?=^## \[|^\[Unreleased\]:)/m.exec(changelog);
if (unreleased === null) fail('CHANGELOG.md has no "## [Unreleased]" section');
if (unreleased[1].trim() === '') fail('CHANGELOG.md: [Unreleased] is empty; describe the changes first');

console.log(`${current} -> ${version}`);
const today = new Date().toISOString().slice(0, 10);

edit('package.json', (text) => replaceOnce('package.json', text, `"version": "${current}"`, `"version": "${version}"`));
edit('package-lock.json', (text) => {
  const lock = JSON.parse(text);
  lock.version = version;
  lock.packages[''].version = version;
  return `${JSON.stringify(lock, null, 2)}\n`;
});
edit('python/pyproject.toml', (text) =>
  replaceOnce('python/pyproject.toml', text, `\nversion = "${current}"\n`, `\nversion = "${version}"\n`),
);
edit('CHANGELOG.md', (text) => {
  let out = replaceOnce('CHANGELOG.md', text, '## [Unreleased]\n', `## [Unreleased]\n\n## [${version}] - ${today}\n`);
  const repo = 'https://github.com/MkKiefer/vs-python-profiler';
  out = replaceOnce(
    'CHANGELOG.md',
    out,
    `[Unreleased]: ${repo}/compare/v${current}...HEAD\n`,
    `[Unreleased]: ${repo}/compare/v${version}...HEAD\n[${version}]: ${repo}/compare/v${current}...v${version}\n`,
  );
  return out;
});

console.log(`
Next:
  git switch -c release/v${version}
  git commit -am "Release v${version}" && git push -u origin release/v${version}
  # open a PR, let CI pass, merge it; then Actions -> Release -> Run workflow (on main)`);
