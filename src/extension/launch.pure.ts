/** vscode-free helpers for launch handling (unit tested). */

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

export function splitArgs(s: string): string[] {
  const out: string[] = [];
  const re = /"((?:\\.|[^"])*)"|'([^']*)'|(\S+)/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(s))) out.push(m[1] ?? m[2] ?? m[3]);
  return out;
}
