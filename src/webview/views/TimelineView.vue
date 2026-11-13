<script setup lang="ts">
/** Timeline: every track on one time axis, zoomed to the selected range. */
import { computed } from 'vue';
import { fmtBytes, fmtMs } from '../../shared/format';
import { chartColor } from '../charts/colors';
import type { Series, Tick } from '../charts/series';
import ThreadLanes from '../components/charts/ThreadLanes.vue';
import TimeSeriesChart from '../components/charts/TimeSeriesChart.vue';
import UiBanner from '../components/ui/UiBanner.vue';
import UiCard from '../components/ui/UiCard.vue';
import { useSessionStore } from '../stores/session';
import { useViewStore } from '../stores/view';

const BUCKETS = 120;

const session = useSessionStore();
const view = useViewStore();

const domain = computed<[number, number]>(() => view.range ?? session.domain);

const samples = computed<Series[]>(() => {
  const [t0, t1] = domain.value;
  const histogram = session.model.histogram(BUCKETS, t0, t1, { mode: view.mode, source: view.source });
  const step = (t1 - t0) / BUCKETS;
  return [
    {
      name: `${view.mode} samples`,
      color: chartColor('orange'),
      t: Array.from(histogram, (_, i) => t0 + (i + 0.5) * step),
      v: Array.from(histogram),
    },
  ];
});

function track(name: string): { t: number[]; v: number[] } {
  return session.model.trackRange(name, domain.value[0], domain.value[1]);
}

const cpu = computed<Series[]>(() => [{ name: 'CPU %', color: chartColor('orange'), ...track('cpu'), area: true }]);
const memory = computed<Series[]>(() => {
  const traced = track('traced');
  return [
    { name: 'RSS', color: chartColor('blue'), ...track('rss'), area: true },
    ...(traced.t.length ? [{ name: 'traced', color: chartColor('orange'), ...traced }] : []),
  ];
});
const lag = computed<Series[]>(() => [{ name: 'loop lag', color: chartColor('red'), ...track('loopLag'), area: true }]);
const gcTicks = computed<Tick[]>(() => session.model.gc.map((g) => ({ t: g[0], color: chartColor('purple') })));
const percent = (v: number): string => `${v.toFixed(0)}%`;
const count = (v: number): string => v.toFixed(0);
</script>

<template>
  <div class="flex-1 overflow-auto px-3.5 pt-3 pb-10">
    <UiBanner>
      <span class="muted">
        Drag on any track to zoom every tab (and the editor heat map) to that time range. Double-click to reset. Orange = on CPU, red underline =
        waiting for the GIL, purple = GC.
      </span>
    </UiBanner>
    <div class="flex flex-col gap-3">
      <UiCard title="Threads">
        <ThreadLanes :domain="domain" @brush="view.setRange" @clear="view.clearRange" />
      </UiCard>
      <UiCard title="Samples per bucket" sub="activity in the current mode">
        <TimeSeriesChart label="Samples per bucket" bars :domain="domain" :series="samples" :markers="session.model.markers" :height="90" :y-format="count" @brush="view.setRange" @clear="view.clearRange" />
      </UiCard>
      <UiCard title="CPU">
        <TimeSeriesChart label="CPU" :domain="domain" :series="cpu" :markers="session.model.markers" :height="90" :y-format="percent" @brush="view.setRange" @clear="view.clearRange" />
      </UiCard>
      <UiCard title="Memory">
        <TimeSeriesChart label="Memory" :domain="domain" :series="memory" :markers="session.model.markers" :ticks="gcTicks" :height="90" :y-format="fmtBytes" @brush="view.setRange" @clear="view.clearRange" />
      </UiCard>
      <UiCard title="Event loop lag">
        <TimeSeriesChart label="Event loop lag" :domain="domain" :series="lag" :markers="session.model.markers" :height="90" :y-format="fmtMs" @brush="view.setRange" @clear="view.clearRange" />
      </UiCard>
    </div>
  </div>
</template>
