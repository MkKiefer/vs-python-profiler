<script setup lang="ts">
/** Snapshot picker, comparison and the allocation flame graph of the selected snapshot (or growth between two). */
import { computed, watch } from 'vue';
import type { SnapshotDiffRow, SnapshotRec } from '../../../shared/model';
import { fmtBytes, fmtCount, fmtMs, shortPath } from '../../../shared/format';
import { useSessionStore } from '../../stores/session';
import { useViewStore, type MemoryWeight } from '../../stores/view';
import FlameGraph from '../charts/FlameGraph.vue';
import type { Column } from '../ui/dataTable';
import UiCard from '../ui/UiCard.vue';
import UiDataTable from '../ui/UiDataTable.vue';
import UiSegmented, { type SegmentOption } from '../ui/UiSegmented.vue';

interface SiteRow {
  sid: number;
  size: number;
  count: number;
}

const session = useSessionStore();
const view = useViewStore();

const WEIGHTS: SegmentOption<MemoryWeight>[] = [
  { value: 'size', label: 'Bytes' },
  { value: 'count', label: 'Blocks' },
];

// a copy: live deltas push into the model's array in place, and a computed that returned the same
// array after a redraw would look unchanged to Vue, so a new snapshot only showed after a remount
const snapshots = computed(() => [...session.model.snapshots]);

// once a second snapshot exists, compare with the first by default
watch(
  () => snapshots.value.length,
  (count, previous) => {
    if (count >= 2 && (previous ?? 0) < 2 && view.memoryBaseline === undefined) view.memoryBaseline = snapshots.value[0].id;
  },
  { immediate: true },
);

const snapshot = computed<SnapshotRec | undefined>(
  () => snapshots.value.find((s) => s.id === view.memorySnapshot) ?? snapshots.value.at(-1),
);
const baseline = computed<SnapshotRec | undefined>(() =>
  view.memoryBaseline !== undefined && view.memoryBaseline !== snapshot.value?.id
    ? snapshots.value.find((s) => s.id === view.memoryBaseline)
    : undefined,
);

const selectedId = computed({
  get: () => snapshot.value?.id ?? 0,
  set: (id: number) => (view.memorySnapshot = id),
});
const baselineId = computed({
  get: () => (view.memoryBaseline === undefined ? '' : String(view.memoryBaseline)),
  set: (id: string) => (view.memoryBaseline = id === '' ? undefined : Number(id)),
});

const diffRows = computed<SnapshotDiffRow[]>(() =>
  snapshot.value && baseline.value ? session.model.snapshotDiff(baseline.value.id, snapshot.value.id) : [],
);
const siteRows = computed<SiteRow[]>(() => snapshot.value?.entries.map(([sid, size, count]) => ({ sid, size, count })) ?? []);

const flameRoot = computed(() => {
  const model = session.model;
  if (!snapshot.value) return model.buildTree(new Map());
  if (baseline.value) {
    const grown = new Map<number, number>();
    for (const row of diffRows.value) {
      const weight = view.memoryWeight === 'size' ? row.dSize : row.dCount;
      if (weight > 0) grown.set(row.sid, weight);
    }
    return model.buildTree(grown);
  }
  return model.buildTree(model.snapshotCounts(snapshot.value.id, view.memoryWeight));
});
const formatWeight = (w: number): string => (view.memoryWeight === 'size' ? fmtBytes(w) : fmtCount(w));

function label(s: SnapshotRec): string {
  return `${s.label} · ${fmtMs(s.t)} · ${fmtBytes(s.totalSize)}`;
}

function site(sid: number) {
  return session.model.userLeaf(sid);
}

function openSite(row: { sid: number }): void {
  const frame = site(row.sid);
  if (frame) session.openSource(frame.file, frame.line);
}

const siteColumns: Column<SiteRow>[] = [
  { key: 'size', label: 'Size', numeric: true, bar: true, value: (r) => r.size, text: (r) => fmtBytes(r.size) },
  { key: 'count', label: 'Blocks', numeric: true, value: (r) => r.count, text: (r) => fmtCount(r.count) },
  { key: 'site', label: 'Allocated at', cellClass: 'fn', value: (r) => site(r.sid)?.func ?? '' },
];
const diffColumns: Column<SnapshotDiffRow>[] = [
  { key: 'dSize', label: 'Δ Size', numeric: true, bar: true, value: (r) => r.dSize, text: (r) => fmtBytes(r.dSize, true) },
  { key: 'dCount', label: 'Δ Blocks', numeric: true, value: (r) => r.dCount, text: (r) => (r.dCount > 0 ? '+' : '') + fmtCount(r.dCount) },
  { key: 'size', label: 'Now', numeric: true, value: (r) => r.size, text: (r) => fmtBytes(r.size) },
  { key: 'site', label: 'Allocated at', cellClass: 'fn', value: (r) => site(r.sid)?.func ?? '' },
];
</script>

<template>
  <template v-if="snapshot">
    <div class="flex flex-wrap items-center gap-x-3.5 gap-y-2 py-2">
      <label class="flex items-center gap-1.5">
        <span class="muted text-[0.85em]">Snapshot</span>
        <select v-model.number="selectedId">
          <option v-for="s in snapshots" :key="s.id" :value="s.id">{{ label(s) }}</option>
        </select>
      </label>
      <label class="flex items-center gap-1.5">
        <span class="muted text-[0.85em]">compare with</span>
        <select v-model="baselineId">
          <option value="">— none —</option>
          <option v-for="s in snapshots" :key="s.id" :value="String(s.id)">{{ label(s) }}</option>
        </select>
      </label>
      <UiSegmented v-model="view.memoryWeight" :options="WEIGHTS" label="Weight" />
    </div>
    <div class="grid grid-cols-[repeat(auto-fit,minmax(380px,1fr))] gap-3">
      <UiCard
        v-if="baseline"
        :title="`Growth ${baseline.label} → ${snapshot.label}`"
        :sub="`${fmtBytes(snapshot.totalSize - baseline.totalSize, true)} in ${fmtMs(snapshot.t - baseline.t)}`"
        class="flex max-h-[420px] flex-col"
      >
        <UiDataTable testid="snapshot-diff" clickable :columns="diffColumns" :rows="diffRows" :row-key="(r) => r.sid" empty="No differences between the two snapshots" @select="openSite">
          <template #cell-site="{ row }">
            <template v-if="site(row.sid)"><b>{{ site(row.sid)?.func }}</b><span class="muted ml-1.5">{{ shortPath(site(row.sid)?.file ?? '', 2) }}:{{ site(row.sid)?.line }}</span></template>
            <template v-else>?</template>
          </template>
        </UiDataTable>
      </UiCard>
      <UiCard
        v-else
        :title="`Top allocation sites · ${snapshot.label}`"
        :sub="`${fmtBytes(snapshot.totalSize)} in ${fmtCount(snapshot.totalCount)} blocks`"
        class="flex max-h-[420px] flex-col"
      >
        <UiDataTable testid="snapshot-sites" clickable :columns="siteColumns" :rows="siteRows" :row-key="(r) => r.sid" empty="Take a snapshot to see allocation sites" @select="openSite" @activate="openSite">
          <template #cell-site="{ row }">
            <template v-if="site(row.sid)"><b>{{ site(row.sid)?.func }}</b><span class="muted ml-1.5">{{ shortPath(site(row.sid)?.file ?? '', 2) }}:{{ site(row.sid)?.line }}</span></template>
            <template v-else>?</template>
          </template>
        </UiDataTable>
      </UiCard>
      <UiCard
        title="Allocation flame graph"
        :sub="baseline ? 'only allocations that grew between the snapshots' : 'live memory by call stack at the selected snapshot'"
        class="flex h-[420px] flex-col"
      >
        <FlameGraph :model="session.model" :root="flameRoot" :format="formatWeight" :focusable="false" :reset-key="`${snapshot.id}:${baseline?.id}:${view.memoryWeight}`" @open="session.openSource" />
      </UiCard>
    </div>
  </template>
</template>
