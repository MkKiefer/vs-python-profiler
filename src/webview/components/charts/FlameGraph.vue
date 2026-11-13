<script setup lang="ts">
/**
 * Canvas icicle/flame graph: root at the top, width = weight.
 * Click: zoom · double-click: open source · right-click / Alt-click: callers & callees ·
 * Esc / Backspace: zoom out · search dims frames that do not match.
 */
import { ref, shallowRef, watch } from 'vue';
import type { ProfileModel, TreeNode } from '../../../shared/model';
import { fmtPct, shortPath } from '../../../shared/format';
import { fitCanvas, fitText } from '../../charts/canvas';
import { CATEGORY_LABELS, chartToken, frameColor } from '../../charts/colors';
import { useCanvasChart } from '../../composables/useCanvasChart';
import { useTooltipStore } from '../../stores/tooltip';

const props = withDefaults(
  defineProps<{
    model: ProfileModel;
    root: TreeNode;
    format: (weight: number) => string;
    search?: string;
    /** a change resets the zoom (new filters, not new live data) */
    resetKey?: string;
    /** offer callers & callees on right-click */
    focusable?: boolean;
  }>(),
  { search: '', resetKey: '', focusable: true },
);
const emit = defineEmits<{ open: [file: string, line: number]; focus: [fn: number] }>();

const ROW = 18;
const MIN_WIDTH = 0.5;

interface Rect {
  x: number;
  y: number;
  w: number;
  node: TreeNode;
}

const container = ref<HTMLElement | null>(null);
const canvas = ref<HTMLCanvasElement | null>(null);
const tooltip = useTooltipStore();
/** child keys from the root down to the zoomed node */
const zoomPath = ref<number[]>([]);
/** root → zoomed node, for the breadcrumbs */
const chain = shallowRef<TreeNode[]>([]);
let rects: Rect[] = [];
let hover: TreeNode | undefined;

const { schedule } = useCanvasChart(container, draw);
watch(() => [props.root, props.search, zoomPath.value], schedule);
watch(
  () => props.resetKey,
  () => (zoomPath.value = []),
);

function frameName(node: TreeNode): string {
  return props.model.frames[node.frame]?.func ?? 'all';
}

function zoomChain(): TreeNode[] {
  let node = props.root;
  const nodes = [node];
  for (const key of zoomPath.value) {
    const next = node.children.find((child) => child.key === key);
    if (!next) break;
    node = next;
    nodes.push(node);
  }
  return nodes;
}

function pathTo(target: TreeNode): number[] | undefined {
  const walk = (node: TreeNode, acc: number[]): number[] | undefined => {
    if (node === target) return acc;
    for (const child of node.children) {
      const found = walk(child, [...acc, child.key]);
      if (found) return found;
    }
    return undefined;
  };
  return walk(props.root, []);
}

function draw(): void {
  const el = canvas.value;
  const box = container.value;
  if (!el || !box) return;
  const model = props.model;
  const nodes = zoomChain();
  chain.value = nodes;
  const zoom = nodes[nodes.length - 1];
  const W = box.clientWidth || 600;
  let maxDepth = 0;
  const measure = (node: TreeNode, depth: number, w: number): void => {
    maxDepth = Math.max(maxDepth, depth);
    for (const child of node.children) {
      const cw = (child.total / node.total) * w;
      if (cw >= MIN_WIDTH) measure(child, depth + 1, cw);
    }
  };
  measure(zoom, 0, W);
  const H = Math.max(box.clientHeight, (maxDepth + nodes.length + 1) * ROW + 4);
  const ctx = fitCanvas(el, W, H);
  if (!ctx) return;
  ctx.clearRect(0, 0, W, H);
  ctx.font = '11px var(--vscode-editor-font-family), monospace';
  ctx.textBaseline = 'middle';
  rects = [];
  const search = props.search.toLowerCase();
  const textColor = chartToken('flame-text');
  const ancestorText = getComputedStyle(document.body).color;
  const hoverOutline = chartToken('hover-outline');

  const drawRect = (node: TreeNode, x: number, y: number, w: number, ancestor: boolean): void => {
    const frame = node.frame < 0 ? undefined : model.frames[node.frame];
    const label = frame ? frame.func : `all (${props.format(node.total)})`;
    const match = !search || (frame && (frame.func.toLowerCase().includes(search) || frame.file.toLowerCase().includes(search)));
    ctx.fillStyle = frame ? frameColor(frame.cat, frame.func, !match || ancestor) : chartToken('flame-root');
    ctx.fillRect(x, y, Math.max(0.5, w - 1), ROW - 1);
    if (hover === node) {
      ctx.strokeStyle = hoverOutline;
      ctx.lineWidth = 1.5;
      ctx.strokeRect(x + 0.5, y + 0.5, Math.max(0.5, w - 2), ROW - 2);
    }
    if (w > 28) {
      ctx.fillStyle = !frame || ancestor ? ancestorText : textColor;
      const text = fitText(ctx, label, w - 6);
      if (text) ctx.fillText(text, x + 3, y + ROW / 2);
    }
    rects.push({ x, y, w, node });
  };

  // ancestors of the zoomed node, full width
  let y = 0;
  for (let i = 0; i < nodes.length - 1; i++) {
    drawRect(nodes[i], 0, y, W, true);
    y += ROW;
  }
  const layout = (node: TreeNode, x: number, yy: number, w: number): void => {
    drawRect(node, x, yy, w, false);
    let cx = x;
    for (const child of node.children) {
      const cw = (child.total / node.total) * w;
      if (cw < MIN_WIDTH) break; // children are sorted by weight
      layout(child, cx, yy + ROW, cw);
      cx += cw;
    }
  };
  layout(zoom, 0, y, W);
}

function hit(event: MouseEvent): Rect | undefined {
  const box = canvas.value?.getBoundingClientRect();
  if (!box) return undefined;
  const x = event.clientX - box.left;
  const y = event.clientY - box.top;
  for (let i = rects.length - 1; i >= 0; i--) {
    const r = rects[i];
    if (x >= r.x && x < r.x + r.w && y >= r.y && y < r.y + ROW) return r;
  }
  return undefined;
}

function onClick(event: MouseEvent): void {
  const r = hit(event);
  if (!r) return;
  if (event.altKey && props.focusable) {
    emit('focus', r.node.fn);
    return;
  }
  const path = pathTo(r.node);
  if (path) zoomPath.value = path;
}

function onDoubleClick(event: MouseEvent): void {
  const r = hit(event);
  const frame = r ? props.model.frames[r.node.frame] : undefined;
  if (frame) emit('open', frame.file, frame.line);
}

function onContextMenu(event: MouseEvent): void {
  const r = hit(event);
  if (!r || !props.focusable || r.node.frame < 0) return;
  event.preventDefault();
  emit('focus', r.node.fn);
}

function onKey(event: KeyboardEvent): void {
  if (event.key === 'Escape' || event.key === 'Backspace') zoomPath.value = zoomPath.value.slice(0, -1);
}

function onMove(event: MouseEvent): void {
  const node = hit(event)?.node;
  if (node !== hover) {
    hover = node;
    schedule();
  }
  if (!node) {
    tooltip.hide();
    return;
  }
  if (node.frame < 0) {
    tooltip.show(event.clientX, event.clientY, { title: 'all', sub: props.format(node.total) });
    return;
  }
  const frame = props.model.frames[node.frame];
  const all = props.root.total;
  tooltip.show(event.clientX, event.clientY, {
    title: frame.func,
    sub: `${shortPath(frame.file, 3)}:${frame.line} · ${CATEGORY_LABELS[frame.cat]}`,
    rows: [
      { label: 'total', value: `${props.format(node.total)}  ${fmtPct(node.total, all)}` },
      { label: 'self', value: `${props.format(node.self)}  ${fmtPct(node.self, all)}` },
    ],
  });
}

function onLeave(): void {
  hover = undefined;
  tooltip.hide();
  schedule();
}
</script>

<template>
  <div class="flex min-h-0 flex-1 flex-col">
    <nav class="crumbs" aria-label="Flame graph zoom">
      <span v-if="chain.length <= 1" class="muted">
        Click a frame to zoom · double-click to open source<template v-if="focusable"> · right-click for callers/callees</template> · Esc to zoom out
      </span>
      <template v-for="(node, i) in chain" v-else :key="i">
        <span v-if="i" class="muted">›</span>
        <span v-if="i === chain.length - 1">{{ frameName(node) }}</span>
        <button v-else type="button" class="link" @click="zoomPath = zoomPath.slice(0, i)">{{ frameName(node) }}</button>
      </template>
    </nav>
    <div ref="container" class="relative min-h-[200px] flex-1 overflow-auto">
      <canvas
        ref="canvas"
        class="flame-canvas"
        tabindex="0"
        role="img"
        aria-label="Flame graph"
        @click="onClick"
        @dblclick="onDoubleClick"
        @contextmenu="onContextMenu"
        @keydown="onKey"
        @mousemove="onMove"
        @mouseleave="onLeave"
      />
    </div>
  </div>
</template>
