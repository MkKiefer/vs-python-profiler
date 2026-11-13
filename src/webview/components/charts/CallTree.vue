<script setup lang="ts">
/** Expandable call tree (top-down, bottom-up or focused) with share bars. */
import { computed, ref, watch } from 'vue';
import type { Frame, ProfileModel, TreeNode } from '../../../shared/model';
import { fmtPct, shortPath } from '../../../shared/format';
import { frameColor } from '../../charts/colors';

const props = withDefaults(
  defineProps<{
    model: ProfileModel;
    root: TreeNode;
    format: (weight: number) => string;
    weightLabel?: string;
    /** a change collapses the tree and re-opens the hot path */
    resetKey?: string;
    /** prefix of the row test ids */
    testid: string;
  }>(),
  { weightLabel: 'Time', resetKey: '' },
);
const emit = defineEmits<{ open: [file: string, line: number]; focus: [fn: number] }>();

/** Children shown per node; the rest is summarised. */
const CHILD_LIMIT = 200;
/** The hot path opens while the heaviest child carries this share of its parent. */
const HOT_SHARE = 0.4;

interface NodeRow {
  kind: 'node';
  path: string;
  node: TreeNode;
  frame: Frame;
  depth: number;
  open: boolean;
}

interface MoreRow {
  kind: 'more';
  path: string;
  depth: number;
  hidden: number;
}

const expanded = ref(new Set<string>());
let hotPathOpened = false;

watch(
  () => props.resetKey,
  () => {
    expanded.value = new Set();
    hotPathOpened = false;
  },
);

watch(
  () => props.root,
  (root) => {
    if (hotPathOpened || !root.children.length) return;
    let node = root;
    let path = '';
    for (let depth = 0; depth < 30 && node.children.length; depth++) {
      const child = node.children[0];
      path += `/${child.key}`;
      expanded.value.add(path);
      if (child.total < node.total * HOT_SHARE) break;
      node = child;
    }
    hotPathOpened = true;
  },
  { immediate: true },
);

const all = computed(() => props.root.total || 1);

const rows = computed(() => {
  const out: (NodeRow | MoreRow)[] = [];
  const walk = (node: TreeNode, depth: number, path: string): void => {
    for (const child of node.children.slice(0, CHILD_LIMIT)) {
      const childPath = `${path}/${child.key}`;
      const open = expanded.value.has(childPath);
      out.push({ kind: 'node', path: childPath, node: child, frame: props.model.frames[child.frame], depth, open });
      if (open) walk(child, depth + 1, childPath);
    }
    if (node.children.length > CHILD_LIMIT) {
      out.push({ kind: 'more', path: `${path}/…`, depth, hidden: node.children.length - CHILD_LIMIT });
    }
  };
  walk(props.root, 0, '');
  return out;
});

function toggle(row: NodeRow): void {
  if (!row.node.children.length) return;
  if (expanded.value.has(row.path)) expanded.value.delete(row.path);
  else expanded.value.add(row.path);
}

function focus(event: MouseEvent, row: NodeRow): void {
  event.preventDefault();
  emit('focus', row.node.fn);
}
</script>

<template>
  <div class="flex-1 overflow-auto">
    <table class="data">
      <thead>
        <tr>
          <th class="num" title="Share of all samples in this frame and below">Total</th>
          <th class="num" title="Share of samples where this frame was executing">Self</th>
          <th class="num">{{ weightLabel }}</th>
          <th>Function</th>
          <th>Location</th>
        </tr>
      </thead>
      <tbody>
        <template v-for="row in rows" :key="row.path">
          <tr
            v-if="row.kind === 'node'"
            class="clickable"
            :aria-expanded="row.node.children.length ? row.open : undefined"
            :data-testid="`${testid}-row-${row.path}`"
            @click="toggle(row)"
            @dblclick="emit('open', row.frame.file, row.frame.line)"
            @contextmenu="focus($event, row)"
          >
            <td class="bar-cell num">
              <div class="bar" :style="{ width: `${(row.node.total / all) * 100}%` }" />
              <span>{{ fmtPct(row.node.total, all) }}</span>
            </td>
            <td class="num">{{ fmtPct(row.node.self, all) }}</td>
            <td class="num">{{ format(row.node.total) }}</td>
            <td class="fn" :title="row.frame.func">
              <span :style="{ paddingLeft: `${row.depth * 14}px` }" />
              <span class="twisty">{{ row.node.children.length ? (row.open ? '▾' : '▸') : '' }}</span>
              <span class="cat-dot" :style="{ background: frameColor(row.frame.cat, row.frame.func) }" />{{ row.frame.func }}
            </td>
            <td class="loc" :title="`${row.frame.file}:${row.frame.line}`">&lrm;{{ shortPath(row.frame.file, 3) }}:{{ row.frame.line }}</td>
          </tr>
          <tr v-else>
            <td colspan="5" class="muted">
              <span :style="{ paddingLeft: `${row.depth * 14 + 14}px` }">… {{ row.hidden }} more</span>
            </td>
          </tr>
        </template>
        <tr v-if="!rows.length">
          <td colspan="5" class="empty">No samples in this selection</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
