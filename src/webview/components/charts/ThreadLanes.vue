<script setup lang="ts">
/** Threads × time: on-CPU share (orange), waiting for the GIL (red underline), GC pauses and markers. */
import { computed, ref, watch } from 'vue';
import { fmtMs } from '../../../shared/format';
import { fitCanvas, truncate } from '../../charts/canvas';
import { chartColor, chartToken } from '../../charts/colors';
import { TimeScale } from '../../charts/timeScale';
import { useCanvasChart } from '../../composables/useCanvasChart';
import { useTimeBrush } from '../../composables/useTimeBrush';
import { useSessionStore } from '../../stores/session';
import { useTooltipStore } from '../../stores/tooltip';

const props = defineProps<{ domain: [number, number] }>();
const emit = defineEmits<{ brush: [t0: number, t1: number]; clear: [] }>();

const LABEL_W = 170;
const LANE = 22;
const MAX_LANES = 40;

interface Lane {
  tid: number;
  name: string;
  wall: Float64Array;
  cpu: Float64Array;
  gilWait: Float64Array;
}

const container = ref<HTMLElement | null>(null);
const canvas = ref<HTMLCanvasElement | null>(null);
const tooltip = useTooltipStore();
const session = useSessionStore();
/** plot width in pixels; bucket count follows it */
const plotWidth = ref(600);

const buckets = computed(() => Math.max(20, Math.floor(plotWidth.value / 3)));

const lanes = computed<Lane[]>(() => {
  const { model } = session;
  const { domain } = props;
  const n = buckets.value;
  return model
    .threadList()
    .slice(0, MAX_LANES)
    .map(({ tid, name }) => ({
      tid,
      name,
      wall: model.histogram(n, domain[0], domain[1], { tid }),
      cpu: model.histogram(n, domain[0], domain[1], { tid, mode: 'cpu' }),
      gilWait: model.histogram(n, domain[0], domain[1], { tid, waitingForGil: true }),
    }));
});

function width(): number {
  return container.value?.clientWidth || 600;
}

function scale(): TimeScale {
  return new TimeScale(props.domain, LABEL_W, width() - 8);
}

function localX(event: MouseEvent): number {
  return event.clientX - (canvas.value?.getBoundingClientRect().left ?? 0);
}

const { schedule } = useCanvasChart(container, draw);
const brush = useTimeBrush({
  localX,
  xToT: (x) => scale().toT(x),
  canStart: (x) => x >= LABEL_W,
  onBrush: (a, b) => emit('brush', a, b),
  onDrag: schedule,
});
watch(lanes, schedule);

function draw(): void {
  if (!canvas.value) return;
  const W = width();
  plotWidth.value = W - LABEL_W - 8;
  const rows = lanes.value;
  const n = buckets.value;
  const H = rows.length * LANE + 46;
  const ctx = fitCanvas(canvas.value, W, H);
  if (!ctx) return;
  ctx.clearRect(0, 0, W, H);
  const x = scale();
  const bw = (W - LABEL_W - 8) / n;
  const orange = chartColor('orange');
  const red = chartColor('red');
  const purple = chartColor('purple');
  const fg = chartColor('foreground');
  ctx.font = '11px var(--vscode-font-family), sans-serif';
  ctx.textBaseline = 'middle';
  rows.forEach((lane, li) => {
    const y = li * LANE;
    ctx.fillStyle = fg;
    ctx.textAlign = 'left';
    ctx.fillText(truncate(lane.name, 24), 4, y + LANE / 2);
    for (let b = 0; b < n; b++) {
      const wall = lane.wall[b];
      if (!wall) continue;
      const bx = LABEL_W + b * bw;
      // sampled at all: faint bar; on-CPU share: intensity
      ctx.globalAlpha = 0.15;
      ctx.fillStyle = fg;
      ctx.fillRect(bx, y + 4, Math.max(1, bw), LANE - 8);
      const cpuShare = lane.cpu[b] / wall;
      if (cpuShare > 0) {
        ctx.globalAlpha = 0.25 + 0.75 * cpuShare;
        ctx.fillStyle = orange;
        ctx.fillRect(bx, y + 4, Math.max(1, bw), LANE - 8);
      }
      const waitShare = lane.gilWait[b] / wall;
      if (waitShare > 0.05) {
        ctx.globalAlpha = 0.3 + 0.7 * waitShare;
        ctx.fillStyle = red;
        ctx.fillRect(bx, y + LANE - 7, Math.max(1, bw), 3);
      }
    }
    ctx.globalAlpha = 1;
  });
  // GC pauses and markers
  const gy = rows.length * LANE + 2;
  ctx.fillStyle = fg;
  ctx.fillText('GC pauses', 4, gy + 7);
  ctx.fillStyle = purple;
  for (const [t, duration] of session.model.gc) {
    if (!x.contains(t)) continue;
    ctx.fillRect(x.toX(t), gy + 2, Math.max(1.5, x.toX(t + duration) - x.toX(t)), 10);
  }
  for (const [t, label] of session.model.markers) {
    if (!x.contains(t)) continue;
    const px = Math.round(x.toX(t)) + 0.5;
    ctx.strokeStyle = purple;
    ctx.setLineDash([3, 3]);
    ctx.beginPath();
    ctx.moveTo(px, 0);
    ctx.lineTo(px, gy + 14);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillText(label, px + 3, gy + 7);
  }
  x.drawAxis(ctx, gy + 20, fg);
  const drag = brush.drag.value;
  if (drag) {
    ctx.fillStyle = chartToken('brush');
    ctx.fillRect(Math.min(drag.x0, drag.x1), 0, Math.abs(drag.x1 - drag.x0), H);
  }
}

function onHover(event: MouseEvent): void {
  const box = canvas.value?.getBoundingClientRect();
  const lane = lanes.value[Math.floor((event.clientY - (box?.top ?? 0)) / LANE)];
  const px = event.clientX - (box?.left ?? 0);
  if (!lane || px < LABEL_W) {
    tooltip.hide();
    return;
  }
  const b = Math.floor((px - LABEL_W) / ((width() - LABEL_W - 8) / buckets.value));
  const wall = lane.wall[b] ?? 0;
  const share = (part: number): string => (wall ? `${Math.round((100 * part) / wall)}%` : '–');
  tooltip.show(event.clientX, event.clientY, {
    title: lane.name,
    sub: `${fmtMs(scale().toT(px))} · tid ${lane.tid}`,
    rows: [
      { label: 'samples', value: String(wall) },
      { label: 'on CPU', value: share(lane.cpu[b] ?? 0) },
      { label: 'waiting for GIL', value: share(lane.gilWait[b] ?? 0) },
    ],
  });
}
</script>

<template>
  <div ref="container" class="chart">
    <canvas
      ref="canvas"
      role="img"
      aria-label="Thread activity"
      @mousedown="brush.start"
      @mousemove="onHover"
      @mouseleave="tooltip.hide()"
      @dblclick="emit('clear')"
    />
  </div>
</template>
