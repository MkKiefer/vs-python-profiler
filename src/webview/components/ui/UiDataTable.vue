<script setup lang="ts" generic="R">
import { computed, ref } from 'vue';
import type { Column } from './dataTable';

const props = withDefaults(
  defineProps<{
    columns: Column<R>[];
    rows: R[];
    rowKey: (row: R) => string | number;
    /** prefix of the row test ids: `<testid>-row-<key>` */
    testid: string;
    sortKey?: string;
    limit?: number;
    empty?: string;
    /** rows react to clicks (select/activate) */
    clickable?: boolean;
  }>(),
  { sortKey: undefined, limit: 500, empty: 'No data', clickable: false },
);
const emit = defineEmits<{ select: [row: R]; activate: [row: R] }>();
defineSlots<Record<`cell-${string}`, (props: { row: R }) => unknown>>();

const sortBy = ref(props.sortKey ?? props.columns[0]?.key ?? '');
const ascending = ref(false);
const selected = ref<string | number | undefined>(undefined);

const sorted = computed(() => {
  const column = props.columns.find((c) => c.key === sortBy.value);
  if (!column) return props.rows;
  const direction = ascending.value ? 1 : -1;
  return [...props.rows].sort((a, b) => {
    const va = column.value(a);
    const vb = column.value(b);
    const d = typeof va === 'number' && typeof vb === 'number' ? va - vb : String(va).localeCompare(String(vb));
    return d * direction;
  });
});
const shown = computed(() => sorted.value.slice(0, props.limit));
const hidden = computed(() => sorted.value.length - shown.value.length);

/** Largest absolute value per bar column, over the shown rows. */
const barMax = computed(() => {
  const max = new Map<string, number>();
  for (const column of props.columns) {
    if (!column.bar) continue;
    let m = 1e-9;
    for (const row of shown.value) m = Math.max(m, Math.abs(Number(column.value(row))) || 0);
    max.set(column.key, m);
  }
  return max;
});

function sortOn(column: Column<R>): void {
  if (sortBy.value === column.key) ascending.value = !ascending.value;
  else {
    sortBy.value = column.key;
    ascending.value = !column.numeric;
  }
}

function ariaSort(column: Column<R>): 'ascending' | 'descending' | 'none' {
  if (column.key !== sortBy.value) return 'none';
  return ascending.value ? 'ascending' : 'descending';
}

function cellText(column: Column<R>, row: R): string {
  return column.text ? column.text(row) : String(column.value(row));
}

function barStyle(column: Column<R>, row: R): { width: string } {
  const v = Math.abs(Number(column.value(row))) || 0;
  return { width: `${Math.min(100, (v / (barMax.value.get(column.key) ?? 1)) * 100)}%` };
}

function select(row: R): void {
  if (!props.clickable) return;
  selected.value = props.rowKey(row);
  emit('select', row);
}

function activate(row: R): void {
  if (props.clickable) emit('activate', row);
}
</script>

<template>
  <div class="flex-1 overflow-auto">
    <table class="data">
      <thead>
        <tr>
          <th
            v-for="column in columns"
            :key="column.key"
            :class="{ num: column.numeric }"
            :title="column.title"
            :aria-sort="ariaSort(column)"
            @click="sortOn(column)"
          >
            {{ column.label }}
          </th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="row in shown"
          :key="rowKey(row)"
          :class="{ clickable }"
          :aria-selected="clickable ? rowKey(row) === selected : undefined"
          :data-testid="`${testid}-row-${rowKey(row)}`"
          @click="select(row)"
          @dblclick="activate(row)"
        >
          <td
            v-for="column in columns"
            :key="column.key"
            :class="[column.cellClass, { num: column.numeric, 'bar-cell': column.bar }]"
          >
            <div v-if="column.bar" class="bar" :class="{ negative: Number(column.value(row)) < 0 }" :style="barStyle(column, row)" />
            <span>
              <slot :name="`cell-${column.key}`" :row="row">{{ cellText(column, row) }}</slot>
            </span>
          </td>
        </tr>
        <tr v-if="!shown.length">
          <td :colspan="columns.length" class="empty">{{ empty }}</td>
        </tr>
        <tr v-else-if="hidden > 0">
          <td :colspan="columns.length" class="muted">… {{ hidden }} more rows</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
