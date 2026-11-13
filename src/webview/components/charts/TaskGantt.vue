<script setup lang="ts">
/** asyncio tasks: one row per task, coloured by running / awaiting. Drag to select a time range. */
import { computed, ref, watch } from 'vue';
import type { TaskRec } from '../../../shared/model';
import { fmtMs } from '../../../shared/format';
import { fitCanvas, truncate } from '../../charts/canvas';
import { chartColor, chartToken } from '../../charts/colors';
import { TimeScale } from '../../charts/timeScale';
import { useCanvasChart } from '../../composables/useCanvasChart';
import { useTimeBrush } from '../../composables/useTimeBrush';
import { useSessionStore } from '../../stores/session';
import { useTooltipStore } from '../../stores/tooltip';

const props = withDefaults(defineProps<{ domain: [number, number]; maxRows?: number }>(), { maxRows: 250 });
const emit = defineEmits<{ brush: [t0: number, t1: number]; clear: [] }>();

const LABEL_W = 170;
const ROW_H = 16;

type Segment = [t0: number, t1: number, state: string];

const container = ref<HTMLElement | null>(null);
const canvas = ref<HTMLCanvasElement | null>(null);
const tooltip = useTooltipStore();
const session = useSessionStore();

/** Tasks alive in the domain: the longest-lived ones, ordered by start. */
const tasks = computed<TaskRec[]>(() => {
  const { model } = session;
  const { domain } = props;
  const visible = [...model.tasks.values()].filter((t) => (t.end ?? model.now) >= domain[0] && t.start <= domain[1]);
  const life = (t: TaskRec): number => (t.end ?? model.now) - t.start;
  visible.sort((a, b) => life(b) - life(a));
  return visible.slice(0, props.maxRows).sort((a, b) => a.start - b.start);
});

/** Running / waiting intervals per task, from the task state events. */
const segments = computed(() => {
  const { model } = session;
  const ids = new Set(tasks.value.map((t) => t.id));
  const byTask = new Map<number, Segment[]>();
  const open = new Map<number, [number, string]>();
  const add = (id: number, segment: Segment): void => {
    const list = byTask.get(id);
    if (list) list.push(segment);
    else byTask.set(id, [segment]);
  };
  for (const [t, id, state] of model.taskEvents) {
    if (!ids.has(id)) continue;
    const previous = open.get(id);
    if (previous) add(id, [previous[0], t, previous[1]]);
    if (state === 'done') open.delete(id);
    else open.set(id, [t, state]);
  }
  for (const [id, [t0, state]] of open) add(id, [t0, model.now, state]);
  return byTask;
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
watch(segments, schedule);

function draw(): void {
  if (!canvas.value) return;
  const W = width();
  const rows = tasks.value;
  const H = Math.max(60, rows.length * ROW_H + 24);
  const ctx = fitCanvas(canvas.value, W, H);
  if (!ctx) return;
  ctx.clearRect(0, 0, W, H);
  const x = scale();
  const running = chartColor('green');
  const waiting = chartColor('yellow');
  const fg = chartColor('foreground');
  ctx.font = '11px var(--vscode-font-family), sans-serif';
  ctx.textBaseline = 'middle';
  rows.forEach((task, i) => {
    const y = i * ROW_H;
    ctx.fillStyle = fg;
    ctx.textAlign = 'left';
    ctx.globalAlpha = task.end === null ? 1 : 0.65;
    ctx.fillText(truncate(task.name, 24), 4, y + ROW_H / 2);
    const own = segments.value.get(task.id) ?? [[task.start, task.end ?? session.model.now, 'waiting']];
    for (const [a, b, state] of own) {
      const x0 = Math.max(LABEL_W, x.toX(a));
      const x1 = Math.min(W - 8, x.toX(b));
      if (x1 < LABEL_W || x0 > W - 8) continue;
      ctx.fillStyle = state === 'running' ? running : waiting;
      ctx.globalAlpha = state === 'running' ? 0.95 : 0.35;
      ctx.fillRect(x0, y + 3, Math.max(1, x1 - x0), ROW_H - 6);
    }
    ctx.globalAlpha = 1;
  });
  x.drawAxis(ctx, rows.length * ROW_H + 6, fg);
  const drag = brush.drag.value;
  if (drag) {
    ctx.fillStyle = chartToken('brush');
    ctx.fillRect(Math.min(drag.x0, drag.x1), 0, Math.abs(drag.x1 - drag.x0), H);
  }
}

function onHover(event: MouseEvent): void {
  const top = canvas.value?.getBoundingClientRect().top ?? 0;
  const task = tasks.value[Math.floor((event.clientY - top) / ROW_H)];
  if (!task) {
    tooltip.hide();
    return;
  }
  const { model } = session;
  const where = task.stack >= 0 ? model.userLeaf(task.stack) : undefined;
  const parent = task.parent !== null ? model.tasks.get(task.parent)?.name : undefined;
  tooltip.show(event.clientX, event.clientY, {
    title: task.name,
    sub: where ? `awaiting in ${where.func} (${where.file.split(/[\\/]/).pop()}:${where.line})` : undefined,
    rows: [
      { label: 'state', value: task.state },
      { label: 'started', value: fmtMs(task.start) },
      { label: 'lifetime', value: fmtMs((task.end ?? model.now) - task.start) },
      ...(parent ? [{ label: 'awaited by', value: parent }] : []),
    ],
  });
}
</script>

<template>
  <div ref="container" class="chart">
    <canvas
      ref="canvas"
      role="img"
      aria-label="Task timeline"
      @mousedown="brush.start"
      @mousemove="onHover"
      @mouseleave="tooltip.hide()"
      @dblclick="emit('clear')"
    />
  </div>
</template>
