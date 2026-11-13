<script setup lang="ts">
/** Overview: the ten-second answer, plus insights that link into the detail tabs. */
import { computed } from 'vue';
import { Cat } from '../../shared/model';
import { fmtBytes, fmtCount, fmtMs, fmtPct, maxOf, mean, shortPath } from '../../shared/format';
import { chartColor, frameColor } from '../charts/colors';
import type { Series } from '../charts/series';
import TimeSeriesChart from '../components/charts/TimeSeriesChart.vue';
import UiCard from '../components/ui/UiCard.vue';
import UiTile from '../components/ui/UiTile.vue';
import UiTileGrid from '../components/ui/UiTileGrid.vue';
import { useNavigation } from '../composables/useNavigation';
import { computeInsights } from '../domain/insights';
import { RouteName } from '../router/routeNames';
import { useSessionStore } from '../stores/session';
import { useViewStore } from '../stores/view';

const session = useSessionStore();
const view = useViewStore();
const navigation = useNavigation();

// "hot" means on CPU: wall-clock samples would blame callers of sleep() and I/O
const counts = computed(() => session.model.countStacks({ ...view.filter, source: 'threads', mode: 'cpu' }));
const total = computed(() => session.model.totalWeight(counts.value));

const tracks = computed(() => {
  const m = session.model;
  return { cpu: m.tracks.get('cpu'), rss: m.tracks.get('rss'), traced: m.tracks.get('traced'), lag: m.tracks.get('loopLag') };
});

const tiles = computed(() => {
  const m = session.model;
  const { cpu, rss, lag } = tracks.value;
  const avgCpu = cpu ? mean(cpu.v) : undefined;
  const peakCpu = cpu ? maxOf(cpu.v) : undefined;
  const maxLag = lag ? maxOf(lag.v) : undefined;
  const gcPause = m.gc.reduce((sum, g) => sum + g[1], 0);
  const rate = m.stats.rateHz ? `${m.stats.rateHz.toFixed(0)} Hz` : '';
  const discarded = m.stats.errors ? ` · ${fmtPct(m.stats.errors, m.stats.samples + m.stats.errors, 0)} discarded` : '';
  return [
    { label: 'Duration', value: fmtMs(m.duration), sub: session.live ? 'live' : '' },
    { label: 'Samples', value: fmtCount(m.stats.samples), sub: rate + discarded },
    { label: 'CPU avg', value: avgCpu !== undefined ? `${avgCpu.toFixed(0)}%` : '–', sub: peakCpu !== undefined ? `peak ${peakCpu.toFixed(0)}%` : '' },
    { label: 'Peak RSS', value: fmtBytes(rss ? maxOf(rss.v) : undefined), sub: rss?.v.length ? `now ${fmtBytes(rss.v.at(-1))}` : '' },
    {
      label: 'Max loop lag',
      value: fmtMs(maxLag),
      sub: lag ? '' : 'no asyncio loop seen',
      tone: maxLag !== undefined && maxLag > 100 ? ('bad' as const) : ('' as const),
    },
    { label: 'GC pauses', value: fmtMs(gcPause), sub: `${m.gc.length} collections` },
    { label: 'Threads', value: String(m.threadList().length), sub: '' },
  ];
});

const cpuSeries = computed<Series[]>(() => {
  const { cpu } = tracks.value;
  return cpu ? [{ name: 'CPU %', color: chartColor('orange'), t: cpu.t, v: cpu.v, area: true }] : [];
});
const memorySeries = computed<Series[]>(() => {
  const { rss, traced } = tracks.value;
  const series: Series[] = [];
  if (rss) series.push({ name: 'RSS', color: chartColor('blue'), t: rss.t, v: rss.v, area: true });
  if (traced) series.push({ name: 'traced', color: chartColor('orange'), t: traced.t, v: traced.v });
  return series;
});
const lagSeries = computed<Series[]>(() => {
  const { lag } = tracks.value;
  return lag ? [{ name: 'lag', color: chartColor('red'), t: lag.t, v: lag.v, area: true }] : [];
});
const showLag = computed(() => Boolean(tracks.value.lag) || session.model.tasks.size > 0);

const hottest = computed(() => {
  const m = session.model;
  return m
    .topFunctions(counts.value)
    .filter((f) => m.fns[f.fn].cat !== Cat.Synth)
    .slice(0, 6)
    .map((f) => ({ ...f, info: m.fns[f.fn] }));
});

const allocators = computed(() => {
  const m = session.model;
  const snapshot = m.snapshots.at(-1);
  if (!snapshot) return [];
  return [...snapshot.entries]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 6)
    .map(([sid, size]) => ({ sid, size, frame: m.userLeaf(sid) }));
});

const longestTasks = computed(() => {
  const m = session.model;
  return [...m.tasks.values()]
    .map((task) => ({ task, life: (task.end ?? m.now) - task.start }))
    .sort((a, b) => b.life - a.life)
    .slice(0, 6);
});

const insights = computed(() =>
  computeInsights({ model: session.model, capabilities: session.capabilities, state: session.state, counts: counts.value, total: total.value }),
);

const SEVERITY_ICON = { bad: '●', warn: '▲', info: 'ℹ' } as const;
const percent = (v: number): string => `${v.toFixed(0)}%`;
</script>

<template>
  <div class="flex-1 overflow-auto px-3.5 pt-3 pb-10">
    <UiTileGrid>
      <UiTile v-for="tile in tiles" :key="tile.label" v-bind="tile" />
    </UiTileGrid>
    <div class="grid grid-cols-[repeat(auto-fit,minmax(300px,1fr))] gap-3">
      <UiCard title="CPU" sub="process, 100% = one core">
        <TimeSeriesChart label="CPU" :domain="session.domain" :series="cpuSeries" :selection="view.range" :markers="session.model.markers" :height="110" :y-format="percent" @brush="view.setRange" @clear="view.clearRange" />
      </UiCard>
      <UiCard title="Memory" sub="RSS · traced">
        <TimeSeriesChart label="Memory" :domain="session.domain" :series="memorySeries" :selection="view.range" :markers="session.model.markers" :height="110" :y-format="fmtBytes" @brush="view.setRange" @clear="view.clearRange" />
      </UiCard>
      <UiCard v-if="showLag" title="Event loop lag">
        <TimeSeriesChart label="Event loop lag" :domain="session.domain" :series="lagSeries" :selection="view.range" :height="110" :y-format="fmtMs" @brush="view.setRange" @clear="view.clearRange" />
      </UiCard>
    </div>

    <h2 class="mt-[18px] mb-2 text-[1em] font-semibold">Insights</h2>
    <ul class="m-0 flex list-none flex-col gap-1.5 p-0" aria-label="Insights">
      <li v-for="insight in insights" :key="insight.id" class="insight" :data-testid="`insight-${insight.id}`">
        <span class="severity" :class="insight.severity">{{ SEVERITY_ICON[insight.severity] }}</span>
        <span>
          {{ insight.text }}
          <button v-if="insight.action" type="button" class="link" @click="navigation.follow(insight.action.target)">{{ insight.action.label }}</button>
        </span>
      </li>
      <li v-if="!insights.length" class="insight">
        <span class="severity info">ℹ</span>
        {{ session.live ? 'Collecting data… insights appear as patterns emerge.' : 'Nothing unusual detected.' }}
      </li>
    </ul>

    <div class="mt-3 grid grid-cols-[repeat(auto-fit,minmax(300px,1fr))] gap-3">
      <UiCard title="Hottest functions" sub="self CPU time">
        <table v-if="hottest.length" class="data">
          <tbody>
            <tr v-for="f in hottest" :key="f.fn" class="clickable" :title="`${f.info.file}:${f.info.minLine}`" :data-testid="`hottest-row-${f.fn}`" @click="navigation.focusFunction(f.fn)">
              <td class="num">{{ fmtPct(f.self, total) }}</td>
              <td class="fn"><span class="cat-dot" :style="{ background: frameColor(f.info.cat, f.info.func) }" />{{ f.info.func }}</td>
              <td class="loc">&lrm;{{ shortPath(f.info.file, 1) }}</td>
            </tr>
          </tbody>
        </table>
        <div v-else class="empty">{{ session.live ? 'Collecting samples…' : 'No samples' }}</div>
      </UiCard>
      <UiCard title="Top allocators" sub="latest snapshot">
        <table v-if="allocators.length" class="data">
          <tbody>
            <tr v-for="a in allocators" :key="a.sid" class="clickable" @click="navigation.goTo(RouteName.Memory)">
              <td class="num">{{ fmtBytes(a.size) }}</td>
              <td class="fn">{{ a.frame?.func ?? '?' }}</td>
              <td class="loc">{{ a.frame ? `‎${shortPath(a.frame.file, 1)}:${a.frame.line}` : '' }}</td>
            </tr>
          </tbody>
        </table>
        <div v-else class="empty">{{ session.capabilities.agent ? 'Take a memory snapshot in the Memory tab' : 'No snapshots' }}</div>
      </UiCard>
      <UiCard title="Longest-running tasks">
        <table v-if="longestTasks.length" class="data">
          <tbody>
            <tr v-for="{ task, life } in longestTasks" :key="task.id" class="clickable" @click="navigation.goTo(RouteName.Async)">
              <td class="num">{{ fmtMs(life) }}</td>
              <td class="fn">{{ task.name }}</td>
              <td class="loc">{{ task.state }}</td>
            </tr>
          </tbody>
        </table>
        <div v-else class="empty">No asyncio tasks</div>
      </UiCard>
    </div>
  </div>
</template>
