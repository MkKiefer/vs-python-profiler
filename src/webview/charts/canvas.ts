/** Canvas and axis helpers shared by the charts. */

/** Fit a canvas to a CSS size with devicePixelRatio scaling; returns its 2D context in CSS pixels. */
export function fitCanvas(canvas: HTMLCanvasElement, width: number, height: number): CanvasRenderingContext2D | null {
  const dpr = window.devicePixelRatio || 1;
  const w = Math.max(1, Math.floor(width));
  const h = Math.max(1, Math.floor(height));
  if (canvas.width !== w * dpr || canvas.height !== h * dpr) {
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    canvas.style.width = `${w}px`;
    canvas.style.height = `${h}px`;
  }
  const ctx = canvas.getContext('2d');
  ctx?.setTransform(dpr, 0, 0, dpr, 0, 0);
  return ctx;
}

/** A round axis step (1, 2 or 5 × 10ⁿ) close to `raw`. */
export function niceStep(raw: number): number {
  const power = Math.pow(10, Math.floor(Math.log10(Math.max(raw, 1e-9))));
  const n = raw / power;
  return (n < 1.5 ? 1 : n < 3.5 ? 2 : n < 7.5 ? 5 : 10) * power;
}

/** Index of the value in sorted `ts` closest to `t`, or -1 when empty. */
export function nearestIndex(ts: readonly number[], t: number): number {
  if (!ts.length) return -1;
  let lo = 0;
  let hi = ts.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if (ts[mid] < t) lo = mid + 1;
    else hi = mid;
  }
  if (lo > 0 && Math.abs(ts[lo - 1] - t) < Math.abs(ts[lo] - t)) lo--;
  return lo;
}

/** `text`, truncated with an ellipsis to fit `width`; empty when not even two characters fit. */
export function fitText(ctx: CanvasRenderingContext2D, text: string, width: number): string {
  if (ctx.measureText(text).width <= width) return text;
  let lo = 0;
  let hi = text.length;
  while (lo < hi) {
    const mid = (lo + hi + 1) >>> 1;
    if (ctx.measureText(text.slice(0, mid) + '…').width <= width) lo = mid;
    else hi = mid - 1;
  }
  return lo > 1 ? text.slice(0, lo) + '…' : '';
}

/** `text` cut to `max` characters with an ellipsis. */
export function truncate(text: string, max: number): string {
  return text.length > max ? text.slice(0, max - 1) + '…' : text;
}

/** FNV-1a: a stable number per string (colour jitter). */
export function hashString(text: string): number {
  let x = 2166136261;
  for (let i = 0; i < text.length; i++) {
    x ^= text.charCodeAt(i);
    x = Math.imul(x, 16777619);
  }
  return x >>> 0;
}
