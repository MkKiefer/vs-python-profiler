/** Canvas time-series chart with brushing (shared time range), markers and GC ticks. */
import { fitCanvas, h, tooltip } from '../dom';
import { chartColor } from './colors';
import { fmtMs } from '../../shared/format';

export interface Series {
  name: string;
  color: string;
  t: number[];
  v: number[];
  area?: boolean;
  dashed?: boolean;
}

export interface ChartOptions {
  height?: number;
  yFormat?: (v: number) => string;
  yMin?: number;
  yMax?: number;
  onBrush?: (t0: number, t1: number) => void;
  onClearBrush?: () => void;
  bars?: boolean;
}

export interface ChartData {
  domain: [number, number];
  series: Series[];
  selection?: [number, number] | null;
  markers?: [number, string][];
  ticks?: { t: number; color: string; label: string }[];
}

const PAD = { l: 52, r: 10, t: 8, b: 20 };

export class TimeSeriesChart {
  readonly el: HTMLElement;
  private canvas = h('canvas');
  private legend = h('div', { class: 'legend' });
  private data: ChartData | undefined;
  private drag: { x0: number; x1: number } | null = null;
  private hoverX: number | null = null;
  private tip = tooltip();
  private ro: ResizeObserver;

  constructor(private readonly opts: ChartOptions = {}) {
    this.el = h('div', { class: 'chart' }, this.canvas, this.legend);
    this.ro = new ResizeObserver(() => this.draw());
    this.ro.observe(this.el);
    this.canvas.addEventListener('mousedown', (e) => {
      const x = this.localX(e);
      this.drag = { x0: x, x1: x };
    });
    window.addEventListener('mousemove', (e) => {
      if (this.drag) {
        this.drag.x1 = this.localX(e);
        this.draw();
      }
    });
    window.addEventListener('mouseup', () => {
      if (!this.drag || !this.data) return;
      const { x0, x1 } = this.drag;
      this.drag = null;
      if (Math.abs(x1 - x0) > 4) {
        const a = this.xToT(Math.min(x0, x1));
        const b = this.xToT(Math.max(x0, x1));
        this.opts.onBrush?.(a, b);
      }
      this.draw();
    });
    this.canvas.addEventListener('dblclick', () => this.opts.onClearBrush?.());
    this.canvas.addEventListener('mousemove', (e) => {
      this.hoverX = this.localX(e);
      this.draw();
      this.showTip(e);
    });
    this.canvas.addEventListener('mouseleave', () => {
      this.hoverX = null;
      this.tip.hide();
      this.draw();
    });
  }

  private localX(e: MouseEvent): number {
    const r = this.canvas.getBoundingClientRect();
    return Math.max(PAD.l, Math.min(r.width - PAD.r, e.clientX - r.left));
  }

  private width(): number {
    return this.el.clientWidth || 400;
  }

  private xToT(x: number): number {
    const [t0, t1] = this.data?.domain ?? [0, 1];
    return t0 + ((x - PAD.l) / (this.width() - PAD.l - PAD.r)) * (t1 - t0);
  }

  private tToX(t: number): number {
    const [t0, t1] = this.data?.domain ?? [0, 1];
    return PAD.l + ((t - t0) / Math.max(1e-9, t1 - t0)) * (this.width() - PAD.l - PAD.r);
  }

  setData(d: ChartData): void {
    this.data = d;
    this.legend.replaceChildren();
    for (const s of d.series) {
      const i = h('i');
      i.style.background = s.color;
      this.legend.appendChild(h('span', null, i, s.name));
    }
    this.draw();
  }

  draw(): void {
    if (!this.data) return;
    const W = this.width();
    const H = this.opts.height ?? 120;
    const ctx = fitCanvas(this.canvas, W, H);
    ctx.clearRect(0, 0, W, H);
    const { series, domain } = this.data;
    const fg = chartColor('foreground');
    const grid = chartColor('lines');
    const fmt = this.opts.yFormat ?? ((v: number) => v.toFixed(0));

    let yMax = this.opts.yMax ?? 0;
    let yMin = this.opts.yMin ?? 0;
    if (this.opts.yMax === undefined) {
      for (const s of series) for (let i = 0; i < s.v.length; i++) if (s.t[i] >= domain[0] && s.t[i] <= domain[1]) yMax = Math.max(yMax, s.v[i]);
      yMax = yMax ? yMax * 1.1 : 1;
    }
    if (this.opts.yMin === undefined) yMin = 0;
    const plotH = H - PAD.t - PAD.b;
    const yToPx = (v: number) => PAD.t + plotH - ((v - yMin) / Math.max(1e-9, yMax - yMin)) * plotH;

    // grid + y labels
    ctx.font = '10px var(--vscode-font-family), sans-serif';
    ctx.fillStyle = fg;
    ctx.globalAlpha = 0.7;
    ctx.strokeStyle = grid;
    ctx.lineWidth = 1;
    for (let i = 0; i <= 3; i++) {
      const v = yMin + ((yMax - yMin) * i) / 3;
      const y = Math.round(yToPx(v)) + 0.5;
      ctx.beginPath();
      ctx.moveTo(PAD.l, y);
      ctx.lineTo(W - PAD.r, y);
      ctx.stroke();
      ctx.textAlign = 'right';
      ctx.textBaseline = 'middle';
      ctx.fillText(fmt(v), PAD.l - 6, y);
    }
    // x labels
    const span = domain[1] - domain[0];
    const step = niceStep(span / Math.max(2, Math.floor((W - PAD.l) / 90)));
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    for (let t = Math.ceil(domain[0] / step) * step; t <= domain[1]; t += step) {
      ctx.fillText(fmtMs(t), this.tToX(t), H - PAD.b + 4);
    }
    ctx.globalAlpha = 1;

    ctx.save();
    ctx.beginPath();
    ctx.rect(PAD.l, PAD.t, W - PAD.l - PAD.r, plotH);
    ctx.clip();
    // ticks (gc etc.)
    for (const tk of this.data.ticks ?? []) {
      if (tk.t < domain[0] || tk.t > domain[1]) continue;
      ctx.fillStyle = tk.color;
      ctx.fillRect(this.tToX(tk.t) - 0.5, PAD.t + plotH - 6, 1.5, 6);
    }
    // series
    for (const s of series) {
      if (!s.t.length) continue;
      ctx.strokeStyle = s.color;
      ctx.lineWidth = 1.5;
      ctx.setLineDash(s.dashed ? [4, 3] : []);
      if (this.opts.bars) {
        ctx.fillStyle = s.color;
        const bw = Math.max(1, (W - PAD.l - PAD.r) / Math.max(1, s.t.length) - 1);
        for (let i = 0; i < s.t.length; i++) {
          const x = this.tToX(s.t[i]);
          const y = yToPx(s.v[i]);
          ctx.fillRect(x - bw / 2, y, bw, PAD.t + plotH - y);
        }
        continue;
      }
      ctx.beginPath();
      let started = false;
      for (let i = 0; i < s.t.length; i++) {
        const x = this.tToX(s.t[i]);
        const y = yToPx(s.v[i]);
        if (!started) {
          ctx.moveTo(x, y);
          started = true;
        } else ctx.lineTo(x, y);
      }
      ctx.stroke();
      if (s.area) {
        ctx.lineTo(this.tToX(s.t[s.t.length - 1]), yToPx(yMin));
        ctx.lineTo(this.tToX(s.t[0]), yToPx(yMin));
        ctx.closePath();
        ctx.globalAlpha = 0.15;
        ctx.fillStyle = s.color;
        ctx.fill();
        ctx.globalAlpha = 1;
      }
    }
    ctx.setLineDash([]);
    // markers
    for (const [t, label] of this.data.markers ?? []) {
      if (t < domain[0] || t > domain[1]) continue;
      const x = Math.round(this.tToX(t)) + 0.5;
      ctx.strokeStyle = chartColor('purple');
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(x, PAD.t);
      ctx.lineTo(x, PAD.t + plotH);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = chartColor('purple');
      ctx.textAlign = 'left';
      ctx.textBaseline = 'top';
      ctx.fillText(label, x + 3, PAD.t);
    }
    // selection
    const sel = this.drag
      ? [this.xToT(Math.min(this.drag.x0, this.drag.x1)), this.xToT(Math.max(this.drag.x0, this.drag.x1))]
      : this.data.selection;
    if (sel) {
      const x0 = this.tToX(sel[0]);
      const x1 = this.tToX(sel[1]);
      ctx.fillStyle = 'rgba(128,128,128,0.25)';
      ctx.fillRect(PAD.l, PAD.t, x0 - PAD.l, plotH);
      ctx.fillRect(x1, PAD.t, W - PAD.r - x1, plotH);
      ctx.strokeStyle = chartColor('blue');
      ctx.strokeRect(x0, PAD.t, x1 - x0, plotH);
    }
    if (this.hoverX !== null && !this.drag) {
      ctx.strokeStyle = fg;
      ctx.globalAlpha = 0.4;
      ctx.beginPath();
      ctx.moveTo(this.hoverX + 0.5, PAD.t);
      ctx.lineTo(this.hoverX + 0.5, PAD.t + plotH);
      ctx.stroke();
      ctx.globalAlpha = 1;
    }
    ctx.restore();
  }

  private showTip(e: MouseEvent): void {
    if (!this.data || this.hoverX === null) return;
    const t = this.xToT(this.hoverX);
    const fmt = this.opts.yFormat ?? ((v: number) => v.toFixed(1));
    const rows = this.data.series
      .map((s) => {
        const i = nearest(s.t, t);
        return i < 0 ? null : h('tr', null, h('td', null, h('span', { style: `color:${s.color}` }, '■ '), s.name), h('td', null, fmt(s.v[i])));
      })
      .filter(Boolean);
    this.tip.show(e.clientX, e.clientY, h('div', null, h('div', { class: 'tt-title' }, fmtMs(t)), h('table', null, ...rows), h('div', { class: 'tt-sub' }, 'drag to select a time range · double-click to reset')));
  }

  dispose(): void {
    this.ro.disconnect();
  }
}

function nearest(ts: number[], t: number): number {
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

export function niceStep(raw: number): number {
  const p = Math.pow(10, Math.floor(Math.log10(Math.max(raw, 1e-9))));
  const n = raw / p;
  return (n < 1.5 ? 1 : n < 3.5 ? 2 : n < 7.5 ? 5 : 10) * p;
}
