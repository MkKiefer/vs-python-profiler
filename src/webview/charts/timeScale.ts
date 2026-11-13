import { fmtMs } from '../../shared/format';
import { niceStep } from './canvas';

/** Maps a time domain onto the horizontal pixel span [x0, x1]. */
export class TimeScale {
  constructor(
    readonly domain: readonly [number, number],
    readonly x0: number,
    readonly x1: number,
  ) {}

  toX(t: number): number {
    const [a, b] = this.domain;
    return this.x0 + ((t - a) / Math.max(1e-9, b - a)) * (this.x1 - this.x0);
  }

  toT(x: number): number {
    const [a, b] = this.domain;
    return a + ((x - this.x0) / Math.max(1e-9, this.x1 - this.x0)) * (b - a);
  }

  contains(t: number): boolean {
    return t >= this.domain[0] && t <= this.domain[1];
  }

  /** Time labels at round steps, about every 90 px, drawn at `y`. */
  drawAxis(ctx: CanvasRenderingContext2D, y: number, color: string): void {
    const [a, b] = this.domain;
    const step = niceStep((b - a) / Math.max(2, Math.floor((this.x1 - this.x0) / 90)));
    ctx.fillStyle = color;
    ctx.globalAlpha = 0.7;
    ctx.font = '10px var(--vscode-font-family), sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    for (let t = Math.ceil(a / step) * step; t <= b; t += step) ctx.fillText(fmtMs(t), this.toX(t), y);
    ctx.globalAlpha = 1;
  }
}
