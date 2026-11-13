export function fmtBytes(n: number | undefined, signed = false): string {
  if (n === undefined || !isFinite(n)) return '–';
  const sign = n < 0 ? '−' : signed && n > 0 ? '+' : '';
  let v = Math.abs(n);
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let u = 0;
  while (v >= 1024 && u < units.length - 1) {
    v /= 1024;
    u++;
  }
  return `${sign}${v >= 100 || u === 0 ? v.toFixed(0) : v.toFixed(1)} ${units[u]}`;
}

export function fmtMs(ms: number | undefined): string {
  if (ms === undefined || !isFinite(ms)) return '–';
  if (ms < 1) return `${(ms * 1000).toFixed(0)} µs`;
  if (ms < 1000) return `${ms.toFixed(ms < 10 ? 1 : 0)} ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(s < 10 ? 2 : 1)} s`;
  const m = Math.floor(s / 60);
  return `${m}m ${Math.round(s - m * 60)}s`;
}

export function fmtPct(part: number, whole: number, digits = 1): string {
  if (!whole) return '0%';
  return `${((100 * part) / whole).toFixed(digits)}%`;
}

export function fmtCount(n: number): string {
  if (n < 1000) return String(n);
  if (n < 1e6) return `${(n / 1000).toFixed(n < 1e4 ? 1 : 0)}k`;
  return `${(n / 1e6).toFixed(1)}M`;
}

export function shortPath(file: string, maxParts = 2): string {
  const parts = file.split(/[\\/]/).filter(Boolean);
  if (parts.length <= maxParts) return file;
  return '…/' + parts.slice(-maxParts).join('/');
}

export function moduleLabel(file: string): string {
  const m = file.match(/(?:site-packages|dist-packages)[\\/]([^\\/]+)/);
  if (m) return m[1];
  const parts = file.split(/[\\/]/);
  return parts[parts.length - 1] || file;
}
