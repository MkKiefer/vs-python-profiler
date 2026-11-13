<script setup lang="ts">
/** Canvas time-series chart: lines, areas or bars, markers, GC ticks and brushing a time range. */
import { ref, watch } from 'vue';
import { fmtMs } from '../../../shared/format';
import { fitCanvas, nearestIndex } from '../../charts/canvas';
import { chartColor, chartToken } from '../../charts/colors';
import type { Marker, Series, Tick } from '../../charts/series';
import { TimeScale } from '../../charts/timeScale';
import { useCanvasChart } from '../../composables/useCanvasChart';
import { useTimeBrush } from '../../composables/useTimeBrush';
import { useTooltipStore } from '../../stores/tooltip';

const props = withDefaults(
  defineProps<{
    label: string;
    domain: [number, number];
    series: Series[];
    selection?: [number, number] | null;
    markers?: Marker[];
    ticks?: Tick[];
    height?: number;
    yFormat?: (v: number) => string;
    bars?: boolean;
  }>(),
  { selection: null, markers: () => [], ticks: () => [], height: 120, yFormat: (v: number) => v.toFixed(0), bars: false },
);
const emit = defineEmits<{ brush: [t0: number, t1: number]; clear: [] }>();

const PAD = { l: 52, r: 10, t: 8, b: 20 };

const container = ref<HTMLElement | null>(null);
const canvas = ref<HTMLCanvasElement | null>(null);
const tooltip = useTooltipStore();
let hoverX: number | null = null;

function width(): number {
  return container.value?.clientWidth || 400;
}

function scale(): TimeScale {
  return new TimeScale(props.domain, PAD.l, width() - PAD.r);
}

function localX(event: MouseEvent): number {
  const left = canvas.value?.getBoundingClientRect().left ?? 0;
  return Math.max(PAD.l, Math.min(width() - PAD.r, event.clientX - left));
}

const { schedule } = useCanvasChart(container, draw);
const brush = useTimeBrush({ localX, xToT: (x) => scale().toT(x), onBrush: (a, b) => emit('brush', a, b), onDrag: schedule });

watch(() => [props.series, props.domain, props.selection, props.markers, props.ticks], schedule);

function draw(): void {
  if (!canvas.value) return;
  const W = width();
  const H = props.height;
  const ctx = fitCanvas(canvas.value, W, H);
  if (!ctx) return;
  ctx.clearRect(0, 0, W, H);
  const { series, domain } = props;
  const x = scale();
  const fg = chartColor('foreground');
  const plotH = H - PAD.t - PAD.b;

  let yMax = 0;
  for (const s of series) for (let i = 0; i < s.v.length; i++) if (x.contains(s.t[i])) yMax = Math.max(yMax, s.v[i]);
  yMax = yMax ? yMax * 1.1 : 1;
  const yToPx = (v: number): number => PAD.t + plotH - (v / yMax) * plotH;

  // grid and y labels
  ctx.font = '10px var(--vscode-font-family), sans-serif';
  ctx.fillStyle = fg;
  ctx.globalAlpha = 0.7;
  ctx.strokeStyle = chartColor('lines');
  ctx.lineWidth = 1;
  ctx.textAlign = 'right';
  ctx.textBaseline = 'middle';
  for (let i = 0; i <= 3; i++) {
    const v = (yMax * i) / 3;
    const y = Math.round(yToPx(v)) + 0.5;
    ctx.beginPath();
    ctx.moveTo(PAD.l, y);
    ctx.lineTo(W - PAD.r, y);
    ctx.stroke();
    ctx.fillText(props.yFormat(v), PAD.l - 6, y);
  }
  ctx.globalAlpha = 1;
  x.drawAxis(ctx, H - PAD.b + 4, fg);

  ctx.save();
  ctx.beginPath();
  ctx.rect(PAD.l, PAD.t, W - PAD.l - PAD.r, plotH);
  ctx.clip();
  for (const tick of props.ticks) {
    if (!x.contains(tick.t)) continue;
    ctx.fillStyle = tick.color;
    ctx.fillRect(x.toX(tick.t) - 0.5, PAD.t + plotH - 6, 1.5, 6);
  }
  for (const s of series) drawSeries(ctx, s, x, yToPx, plotH, W);
  ctx.setLineDash([]);
  drawMarkers(ctx, x, plotH, domain);
  drawSelection(ctx, x, plotH, W);
  if (hoverX !== null && !brush.drag.value) {
    ctx.strokeStyle = fg;
    ctx.globalAlpha = 0.4;
    ctx.beginPath();
    ctx.moveTo(hoverX + 0.5, PAD.t);
    ctx.lineTo(hoverX + 0.5, PAD.t + plotH);
    ctx.stroke();
    ctx.globalAlpha = 1;
  }
  ctx.restore();
}

function drawSeries(ctx: CanvasRenderingContext2D, s: Series, x: TimeScale, yToPx: (v: number) => number, plotH: number, W: number): void {
  if (!s.t.length) return;
  ctx.strokeStyle = s.color;
  ctx.lineWidth = 1.5;
  ctx.setLineDash(s.dashed ? [4, 3] : []);
  if (props.bars) {
    ctx.fillStyle = s.color;
    const bw = Math.max(1, (W - PAD.l - PAD.r) / Math.max(1, s.t.length) - 1);
    for (let i = 0; i < s.t.length; i++) {
      const y = yToPx(s.v[i]);
      ctx.fillRect(x.toX(s.t[i]) - bw / 2, y, bw, PAD.t + plotH - y);
    }
    return;
  }
  ctx.beginPath();
  for (let i = 0; i < s.t.length; i++) {
    if (i === 0) ctx.moveTo(x.toX(s.t[i]), yToPx(s.v[i]));
    else ctx.lineTo(x.toX(s.t[i]), yToPx(s.v[i]));
  }
  ctx.stroke();
  if (s.area) {
    ctx.lineTo(x.toX(s.t[s.t.length - 1]), yToPx(0));
    ctx.lineTo(x.toX(s.t[0]), yToPx(0));
    ctx.closePath();
    ctx.globalAlpha = 0.15;
    ctx.fillStyle = s.color;
    ctx.fill();
    ctx.globalAlpha = 1;
  }
}

function drawMarkers(ctx: CanvasRenderingContext2D, x: TimeScale, plotH: number, domain: [number, number]): void {
  const color = chartColor('purple');
  for (const [t, label] of props.markers) {
    if (t < domain[0] || t > domain[1]) continue;
    const px = Math.round(x.toX(t)) + 0.5;
    ctx.strokeStyle = color;
    ctx.setLineDash([3, 3]);
    ctx.beginPath();
    ctx.moveTo(px, PAD.t);
    ctx.lineTo(px, PAD.t + plotH);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = color;
    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';
    ctx.fillText(label, px + 3, PAD.t);
  }
}

function drawSelection(ctx: CanvasRenderingContext2D, x: TimeScale, plotH: number, W: number): void {
  const drag = brush.drag.value;
  const selection = drag ? [x.toT(Math.min(drag.x0, drag.x1)), x.toT(Math.max(drag.x0, drag.x1))] : props.selection;
  if (!selection) return;
  const x0 = x.toX(selection[0]);
  const x1 = x.toX(selection[1]);
  ctx.fillStyle = chartToken('outside-selection');
  ctx.fillRect(PAD.l, PAD.t, x0 - PAD.l, plotH);
  ctx.fillRect(x1, PAD.t, W - PAD.r - x1, plotH);
  ctx.strokeStyle = chartColor('blue');
  ctx.strokeRect(x0, PAD.t, x1 - x0, plotH);
}

function onHover(event: MouseEvent): void {
  hoverX = localX(event);
  schedule();
  const t = scale().toT(hoverX);
  const rows = props.series.flatMap((s) => {
    const i = nearestIndex(s.t, t);
    return i < 0 ? [] : [{ label: s.name, value: props.yFormat(s.v[i]), swatch: s.color }];
  });
  tooltip.show(event.clientX, event.clientY, { title: fmtMs(t), rows, hint: 'drag to select a time range · double-click to reset' });
}

function onLeave(): void {
  hoverX = null;
  tooltip.hide();
  schedule();
}
</script>

<template>
  <div ref="container" class="chart">
    <canvas
      ref="canvas"
      role="img"
      :aria-label="label"
      @mousedown="brush.start"
      @mousemove="onHover"
      @mouseleave="onLeave"
      @dblclick="emit('clear')"
    />
    <div class="legend">
      <span v-for="s in series" :key="s.name"><i class="legend-line" :style="{ background: s.color }" />{{ s.name }}</span>
    </div>
  </div>
</template>
