<script setup lang="ts">
/** Memory tab: RSS and traced memory over time, snapshots and diffs, object counts, GC. */
import { computed } from 'vue';
import { fmtBytes, fmtCount, fmtMs, maxOf } from '../../shared/format';
import { chartColor } from '../charts/colors';
import type { Marker, Series, Tick } from '../charts/series';
import TimeSeriesChart from '../components/charts/TimeSeriesChart.vue';
import SnapshotPanel from '../components/memory/SnapshotPanel.vue';
import type { Column } from '../components/ui/dataTable';
import UiBanner from '../components/ui/UiBanner.vue';
import UiButton from '../components/ui/UiButton.vue';
import UiCard from '../components/ui/UiCard.vue';
import UiDataTable from '../components/ui/UiDataTable.vue';
import UiTile from '../components/ui/UiTile.vue';
import UiTileGrid from '../components/ui/UiTileGrid.vue';
import { useSessionStore } from '../stores/session';
import { useViewStore } from '../stores/view';

interface GcRow {
  gen: number;
  n: number;
  total: number;
  max: number;
  collected: number;
}

interface ObjectRow {
  name: string;
  count: number;
  delta: number;
}

const session = useSessionStore();
const view = useViewStore();

const tracks = computed(() => {
  const m = session.model;
  return { rss: m.tracks.get('rss'), traced: m.tracks.get('traced'), peak: m.tracks.get('tracedPeak') };
});

const tiles = computed(() => {
  const m = session.model;
  const { rss, traced } = tracks.value;
  const now = rss?.v.at(-1);
  const peak = rss ? maxOf(rss.v) : undefined;
  const start = rss?.v[0];
  const growth = now !== undefined && start ? now - start : undefined;
  const gcPause = m.gc.reduce((sum, g) => sum + g[1], 0);
  return [
    { label: 'RSS now', value: fmtBytes(now), sub: peak ? `peak ${fmtBytes(peak)}` : '', tone: '' as const },
    {
      label: 'Growth',
      value: growth !== undefined ? fmtBytes(growth, true) : '–',
      sub: 'since start',
      tone: growth !== undefined && start && growth > start * 0.5 ? ('warn' as const) : ('' as const),
    },
    {
      label: 'Traced (tracemalloc)',
      value: traced ? fmtBytes(traced.v.at(-1)) : 'off',
      sub: traced ? `peak ${fmtBytes(m.lastValue('tracedPeak'))}` : 'start memory tracing',
      tone: '' as const,
    },
    { label: 'GC pauses', value: fmtMs(gcPause), sub: `${m.gc.length} collections`, tone: gcPause > m.duration * 0.05 ? ('warn' as const) : ('' as const) },
    { label: 'Snapshots', value: String(m.snapshots.length), sub: '', tone: '' as const },
  ];
});

const series = computed<Series[]>(() => {
  const { rss, traced, peak } = tracks.value;
  const out: Series[] = [];
  if (rss) out.push({ name: 'RSS', color: chartColor('blue'), t: rss.t, v: rss.v, area: true });
  if (traced) out.push({ name: 'traced', color: chartColor('orange'), t: traced.t, v: traced.v });
  if (peak) out.push({ name: 'traced peak', color: chartColor('red'), t: peak.t, v: peak.v, dashed: true });
  return out;
});
const snapshotMarkers = computed<Marker[]>(() => session.model.snapshots.map((s) => [s.t, s.label]));
const gcTicks = computed<Tick[]>(() => session.model.gc.map((g) => ({ t: g[0], color: chartColor('purple') })));

const gcRows = computed<GcRow[]>(() => {
  const byGen = new Map<number, GcRow>();
  for (const [, duration, gen, collected] of session.model.gc) {
    const row = byGen.get(gen) ?? { gen, n: 0, total: 0, max: 0, collected: 0 };
    row.n++;
    row.total += duration;
    row.max = Math.max(row.max, duration);
    row.collected += collected;
    byGen.set(gen, row);
  }
  return [...byGen.values()];
});

const objectRows = computed<ObjectRow[]>(() => {
  const counts = session.model.objectCounts;
  const last = counts.at(-1);
  if (!last) return [];
  const previous = counts.length > 1 ? new Map(counts[counts.length - 2].counts) : undefined;
  return last.counts.map(([name, count]) => ({ name, count, delta: previous ? count - (previous.get(name) ?? 0) : 0 }));
});

const gcColumns: Column<GcRow>[] = [
  { key: 'gen', label: 'Gen', value: (r) => r.gen },
  { key: 'n', label: 'Collections', numeric: true, value: (r) => r.n },
  { key: 'total', label: 'Total pause', numeric: true, bar: true, value: (r) => r.total, text: (r) => fmtMs(r.total) },
  { key: 'max', label: 'Max pause', numeric: true, value: (r) => r.max, text: (r) => fmtMs(r.max) },
  { key: 'collected', label: 'Collected', numeric: true, value: (r) => r.collected, text: (r) => fmtCount(r.collected) },
];
const objectColumns: Column<ObjectRow>[] = [
  { key: 'count', label: 'Objects', numeric: true, bar: true, value: (r) => r.count, text: (r) => fmtCount(r.count) },
  { key: 'delta', label: 'Δ since previous', numeric: true, value: (r) => r.delta, text: (r) => (r.delta > 0 ? '+' : '') + fmtCount(r.delta) },
  { key: 'name', label: 'Type', value: (r) => r.name },
];
</script>

<template>
  <div class="flex-1 overflow-auto px-3.5 pt-3 pb-10">
    <template v-if="session.live">
      <UiBanner v-if="!session.capabilities.agent" tone="warn">
        ⚠ The in-process agent is not connected, so only OS memory (RSS) and GC stats are available. Snapshots need the agent (start the
        program with the profiler, or attach with injection enabled).
      </UiBanner>
      <UiBanner v-else>
        <UiButton
          :primary="!session.capabilities.tracemalloc"
          :title="session.capabilities.tracemalloc ? undefined : 'tracemalloc adds CPU and memory overhead to the target'"
          :disabled="session.isRunning('tracemalloc')"
          @click="session.run('tracemalloc', { enabled: !session.capabilities.tracemalloc })"
        >
          {{ session.capabilities.tracemalloc ? 'Stop memory tracing' : 'Start memory tracing' }}
        </UiButton>
        <UiButton icon="📷" :primary="session.capabilities.tracemalloc" :disabled="session.isRunning('snapshot')" @click="session.run('snapshot', {})">
          Take snapshot
        </UiButton>
        <span class="muted">
          {{
            session.capabilities.tracemalloc
              ? 'Leak hunting: take a snapshot, let the program run, take another, then compare.'
              : 'Memory tracing is off. Start it, exercise your program, then take snapshots.'
          }}
        </span>
      </UiBanner>
    </template>
    <UiBanner v-else-if="!session.model.snapshots.length">
      <span class="muted">This profile has no memory snapshots. Live sessions can trace allocations with tracemalloc.</span>
    </UiBanner>

    <UiTileGrid>
      <UiTile v-for="tile in tiles" :key="tile.label" v-bind="tile" />
    </UiTileGrid>
    <UiCard title="Memory over time" sub="RSS (OS) · traced (tracemalloc) · GC ticks · snapshots">
      <TimeSeriesChart label="Memory over time" :domain="session.domain" :series="series" :selection="view.range" :markers="snapshotMarkers" :ticks="gcTicks" :height="170" :y-format="fmtBytes" @brush="view.setRange" @clear="view.clearRange" />
    </UiCard>
    <SnapshotPanel />
    <div class="mt-3 grid grid-cols-[repeat(auto-fit,minmax(380px,1fr))] gap-3">
      <UiCard title="Live objects by type">
        <template v-if="session.live && session.capabilities.agent" #actions>
          <UiButton title="Walks gc.get_objects() in the target (pauses it briefly)" :disabled="session.isRunning('objectCounts')" @click="session.run('objectCounts', {})">
            Count objects
          </UiButton>
        </template>
        <div class="max-h-[320px] overflow-auto">
          <UiDataTable testid="objects" :columns="objectColumns" :rows="objectRows" :row-key="(r) => r.name" empty="No object counts recorded" />
        </div>
      </UiCard>
      <UiCard title="Garbage collector">
        <UiDataTable testid="gc" :columns="gcColumns" :rows="gcRows" :row-key="(r) => r.gen" sort-key="gen" empty="No GC collections recorded" />
      </UiCard>
    </div>
  </div>
</template>
