/** Minimal dotenv parser (KEY=VALUE, quotes, comments, ${VAR} expansion). */
export function parseDotEnv(text: string, base: Record<string, string | undefined>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith('#')) continue;
    const m = line.match(/^(?:export\s+)?([\w.-]+)\s*=\s*(.*)$/);
    if (!m) continue;
    let v = m[2];
    let expand = true;
    if (v.startsWith("'") && v.endsWith("'") && v.length > 1) {
      v = v.slice(1, -1); // single quotes: literal
      expand = false;
    } else if (v.startsWith('"') && v.endsWith('"') && v.length > 1) {
      v = v.slice(1, -1).replace(/\\n/g, '\n');
    } else {
      v = v.replace(/\s+#.*$/, '');
    }
    if (expand) v = v.replace(/\$\{(\w+)\}/g, (_match, n: string) => out[n] ?? base[n] ?? '');
    out[m[1]] = v;
  }
  return out;
}
