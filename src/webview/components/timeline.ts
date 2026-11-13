/** Canvas timelines: asyncio task Gantt and per-thread activity lanes. */
import { fitCanvas, h, tooltip } from '../dom';
import { chartColor } from './colors';
import type { ProfileModel, TaskRec } from '../../shared/model';
import { STATUS_GIL_REQUESTED, STATUS_HAS_GIL } from '../../shared/model';
import { fmtMs } from '../../shared/format';
import { niceStep } from './timeseries';

const LABEL_W = 170;
const ROW_H = 16;

abstract class CanvasTimeline {
  readonly el: HTMLElement;
  protected canvas = h('canvas');
  protected tip = tooltip();
  protected domain: [number, number] = [0, 1];
  protected model: ProfileModel | undefined;
  private ro: ResizeObserver;
  private drag: { x0: number; x1: number } | null = null;

  constructor(protected readonly onBrush?: (t0: number, t1: number) => void, protected readonly onClear?: () => void) {
    this.el = h('div', { class: 'chart' }, this.canvas);
    this.ro = new ResizeObserver(() => this.draw());
    this.ro.observe(this.el);
    this.canvas.addEventListener('mousemove', (e) => {
      if (this.drag) {
        this.drag.x1 = this.localX(e);
        this.draw();
        this.drawBrush();
        return;
      }
      this.onHover(e);
    });
    this.canvas.addEventListener('mouseleave', () => this.tip.hide());
    this.canvas.addEventListener('mousedown', (e) => {
      const x = this.localX(e);
      if (x >= LABEL_W) this.drag = { x0: x, x1: x };
    });
    window.addEventListener('mouseup', () => {
      if (!this.drag) return;
      const { x0, x1 } = this.drag;
      this.drag = null;
      if (Math.abs(x1 - x0) > 4) this.onBrush?.(this.xToT(Math.min(x0, x1)), this.xToT(Math.max(x0, x1)));
      this.draw();
    });
    this.canvas.addEventListener('dblclick', () => this.onClear?.());
  }

  protected localX(e: MouseEvent): number {
    return e.clientX - this.canvas.getBoundingClientRect().left;
  }
  protected width(): number {
    return this.el.clientWidth || 600;
  }
  protected tToX(t: number): number {
    const [a, b] = this.domain;
    return LABEL_W + ((t - a) / Math.max(1e-9, b - a)) * (this.width() - LABEL_W - 8);
  }
  protected xToT(x: number): number {
    const [a, b] = this.domain;
    return a + ((x - LABEL_W) / (this.width() - LABEL_W - 8)) * (b - a);
  }

  protected axis(ctx: CanvasRenderingContext2D, y: number): void {
    const [a, b] = this.domain;
    const step = niceStep((b - a) / Math.max(2, Math.floor((this.width() - LABEL_W) / 90)));
    ctx.fillStyle = chartColor('foreground');
    ctx.globalAlpha = 0.7;
    ctx.font = '10px var(--vscode-font-family), sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    for (let t = Math.ceil(a / step) * step; t <= b; t += step) ctx.fillText(fmtMs(t), this.tToX(t), y);
    ctx.globalAlpha = 1;
  }

  private drawBrush(): void {
    if (!this.drag) return;
    const ctx = this.canvas.getContext('2d');
    if (!ctx) return;
    const x0 = Math.min(this.drag.x0, this.drag.x1);
    const x1 = Math.max(this.drag.x0, this.drag.x1);
    ctx.fillStyle = 'rgba(55,148,255,0.2)';
    ctx.fillRect(x0, 0, x1 - x0, this.canvas.clientHeight);
  }

  abstract draw(): void;
  protected abstract onHover(e: MouseEvent): void;

  dispose(): void {
    this.ro.disconnect();
  }
}

/** Asyncio tasks: one row per task, colored by running / waiting state. */
export class TaskGantt extends CanvasTimeline {
  private tasks: TaskRec[] = [];
  private segments = new Map<number, [number, number, string][]>();

  setData(model: ProfileModel, domain: [number, number], maxRows = 250): void {
    this.model = model;
    this.domain = domain;
    const all = [...model.tasks.values()].filter((t) => (t.end ?? model.now) >= domain[0] && t.start <= domain[1]);
    // longest-lived first, then by start
    all.sort((a, b) => (b.end ?? model.now) - b.start - ((a.end ?? model.now) - a.start));
    this.tasks = all.slice(0, maxRows).sort((a, b) => a.start - b.start);
    const ids = new Set(this.tasks.map((t) => t.id));
    const seg = new Map<number, [number, number, string][]>();
    const open = new Map<number, [number, string]>();
    for (const [t, id, state] of model.taskEvents) {
      if (!ids.has(id)) continue;
      const prev = open.get(id);
      if (prev) {
        let arr = seg.get(id);
        if (!arr) seg.set(id, (arr = []));
        arr.push([prev[0], t, prev[1]]);
      }
      if (state === 'done') open.delete(id);
      else open.set(id, [t, state]);
    }
    for (const [id, [t0, state]] of open) {
      let arr = seg.get(id);
      if (!arr) seg.set(id, (arr = []));
      arr.push([t0, model.now, state]);
    }
    this.segments = seg;
    this.draw();
  }

  draw(): void {
    if (!this.model) return;
    const now = this.model.now;
    const W = this.width();
    const H = Math.max(60, this.tasks.length * ROW_H + 24);
    const ctx = fitCanvas(this.canvas, W, H);
    ctx.clearRect(0, 0, W, H);
    const running = chartColor('green');
    const waiting = chartColor('yellow');
    ctx.font = '11px var(--vscode-font-family), sans-serif';
    ctx.textBaseline = 'middle';
    this.tasks.forEach((t, i) => {
      const y = i * ROW_H;
      ctx.fillStyle = chartColor('foreground');
      ctx.textAlign = 'left';
      ctx.globalAlpha = t.end === null ? 1 : 0.65;
      ctx.fillText(t.name.length > 24 ? t.name.slice(0, 23) + '…' : t.name, 4, y + ROW_H / 2);
      ctx.globalAlpha = 1;
      const segs = this.segments.get(t.id) ?? [[t.start, t.end ?? now, 'waiting']];
      for (const [a, b, st] of segs) {
        const x0 = Math.max(LABEL_W, this.tToX(a));
        const x1 = Math.min(W - 8, this.tToX(b));
        if (x1 < LABEL_W || x0 > W - 8) continue;
        ctx.fillStyle = st === 'running' ? running : waiting;
        ctx.globalAlpha = st === 'running' ? 0.95 : 0.35;
        ctx.fillRect(x0, y + 3, Math.max(1, x1 - x0), ROW_H - 6);
      }
      ctx.globalAlpha = 1;
    });
    this.axis(ctx, this.tasks.length * ROW_H + 6);
  }

  protected onHover(e: MouseEvent): void {
    const r = this.canvas.getBoundingClientRect();
    const i = Math.floor((e.clientY - r.top) / ROW_H);
    const t = this.tasks[i];
    if (!t || !this.model) {
      this.tip.hide();
      return;
    }
    const where = t.stack >= 0 ? this.model.userLeaf(t.stack) : undefined;
    const parent = t.parent !== null ? this.model.tasks.get(t.parent)?.name : undefined;
    this.tip.show(
      e.clientX,
      e.clientY,
      h(
        'div',
        null,
        h('div', { class: 'tt-title' }, t.name),
        h('div', { class: 'tt-sub' }, where ? `awaiting in ${where.func} (${where.file.split(/[\\/]/).pop()}:${where.line})` : ''),
        h(
          'table',
          null,
          h('tr', null, h('td', null, 'state'), h('td', null, t.state)),
          h('tr', null, h('td', null, 'started'), h('td', null, fmtMs(t.start))),
          h('tr', null, h('td', null, 'lifetime'), h('td', null, fmtMs((t.end ?? this.model.now) - t.start))),
          parent ? h('tr', null, h('td', null, 'awaited by'), h('td', null, parent)) : null,
        ),
      ),
    );
  }
}

/** Threads × time heat strips: on-CPU (orange), holding GIL, waiting for GIL (red), idle. */
export class ThreadLanes extends CanvasTimeline {
  private lanes: { tid: number; name: string; cpu: Float64Array; wall: Float64Array; gilWait: Float64Array }[] = [];
  private buckets = 0;
  private gc: [number, number][] = [];
  private markers: [number, string][] = [];

  setData(model: ProfileModel, domain: [number, number]): void {
    this.model = model;
    this.domain = domain;
    this.buckets = Math.max(20, Math.floor((this.width() - LABEL_W - 8) / 3));
    const gilWaitMask = STATUS_GIL_REQUESTED;
    this.lanes = model.threadList().slice(0, 40).map(({ tid, name }) => {
      const wall = model.histogram(this.buckets, domain[0], domain[1], { tid });
      const cpu = model.histogram(this.buckets, domain[0], domain[1], { tid, mode: 'cpu' });
      const gilWait = new Float64Array(this.buckets);
      const tbl = model.samples;
      const start = tbl.lowerBound(domain[0]);
      const end = tbl.lowerBound(domain[1]);
      const span = Math.max(1e-9, domain[1] - domain[0]);
      for (let i = start; i < end; i++) {
        if (tbl.tid[i] !== tid) continue;
        const st = tbl.status[i];
        if (st & gilWaitMask && !(st & STATUS_HAS_GIL)) {
          gilWait[Math.min(this.buckets - 1, Math.floor(((tbl.t[i] - domain[0]) / span) * this.buckets))]++;
        }
      }
      return { tid, name, cpu, wall, gilWait };
    });
    this.gc = model.gc.map((g) => [g[0], g[1]]);
    this.markers = model.markers;
    this.draw();
  }

  draw(): void {
    if (!this.model) return;
    const W = this.width();
    const LANE = 22;
    const H = this.lanes.length * LANE + 46;
    const ctx = fitCanvas(this.canvas, W, H);
    ctx.clearRect(0, 0, W, H);
    const bw = (W - LABEL_W - 8) / Math.max(1, this.buckets);
    const orange = chartColor('orange');
    const red = chartColor('red');
    const fg = chartColor('foreground');
    ctx.font = '11px var(--vscode-font-family), sans-serif';
    ctx.textBaseline = 'middle';
    this.lanes.forEach((lane, li) => {
      const y = li * LANE;
      ctx.fillStyle = fg;
      ctx.textAlign = 'left';
      ctx.fillText(lane.name.length > 24 ? lane.name.slice(0, 23) + '…' : lane.name, 4, y + LANE / 2);
      let max = 0;
      for (const v of lane.wall) max = Math.max(max, v);
      for (let b = 0; b < this.buckets; b++) {
        const wall = lane.wall[b];
        if (!wall) continue;
        const x = LABEL_W + b * bw;
        // presence (sampled at all) as faint bar, on-CPU share as intensity
        ctx.globalAlpha = 0.15;
        ctx.fillStyle = fg;
        ctx.fillRect(x, y + 4, Math.max(1, bw), LANE - 8);
        const cpuShare = lane.cpu[b] / wall;
        if (cpuShare > 0) {
          ctx.globalAlpha = 0.25 + 0.75 * cpuShare;
          ctx.fillStyle = orange;
          ctx.fillRect(x, y + 4, Math.max(1, bw), LANE - 8);
        }
        const waitShare = lane.gilWait[b] / wall;
        if (waitShare > 0.05) {
          ctx.globalAlpha = 0.3 + 0.7 * waitShare;
          ctx.fillStyle = red;
          ctx.fillRect(x, y + LANE - 7, Math.max(1, bw), 3);
        }
      }
      ctx.globalAlpha = 1;
    });
    // gc + markers row
    const gy = this.lanes.length * LANE + 2;
    ctx.fillStyle = fg;
    ctx.fillText('GC pauses', 4, gy + 7);
    ctx.fillStyle = chartColor('purple');
    for (const [t, dur] of this.gc) {
      if (t < this.domain[0] || t > this.domain[1]) continue;
      ctx.fillRect(this.tToX(t), gy + 2, Math.max(1.5, this.tToX(t + dur) - this.tToX(t)), 10);
    }
    for (const [t, label] of this.markers) {
      if (t < this.domain[0] || t > this.domain[1]) continue;
      const x = Math.round(this.tToX(t)) + 0.5;
      ctx.strokeStyle = chartColor('purple');
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, gy + 14);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillText(label, x + 3, gy + 7);
    }
    this.axis(ctx, gy + 20);
  }

  protected onHover(e: MouseEvent): void {
    const r = this.canvas.getBoundingClientRect();
    const li = Math.floor((e.clientY - r.top) / 22);
    const lane = this.lanes[li];
    const x = e.clientX - r.left;
    if (!lane || x < LABEL_W) {
      this.tip.hide();
      return;
    }
    const bw = (this.width() - LABEL_W - 8) / this.buckets;
    const b = Math.floor((x - LABEL_W) / bw);
    const wall = lane.wall[b] ?? 0;
    this.tip.show(
      e.clientX,
      e.clientY,
      h(
        'div',
        null,
        h('div', { class: 'tt-title' }, lane.name),
        h('div', { class: 'tt-sub' }, `${fmtMs(this.xToT(x))} · tid ${lane.tid}`),
        h(
          'table',
          null,
          h('tr', null, h('td', null, 'samples'), h('td', null, String(wall))),
          h('tr', null, h('td', null, 'on CPU'), h('td', null, wall ? `${Math.round((100 * lane.cpu[b]) / wall)}%` : '–')),
          h('tr', null, h('td', null, 'waiting for GIL'), h('td', null, wall ? `${Math.round((100 * lane.gilWait[b]) / wall)}%` : '–')),
        ),
      ),
    );
  }
}

