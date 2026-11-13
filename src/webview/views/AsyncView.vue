<script setup lang="ts">
/** Async tab: event-loop lag, task timeline, task list and asyncio debug events. */
import { computed } from 'vue';
import type { EventRec, TaskRec } from '../../shared/model';
import { fmtCount, fmtMs, maxOf, percentile } from '../../shared/format';
import { chartColor } from '../charts/colors';
import type { Series } from '../charts/series';
import TaskGantt from '../components/charts/TaskGantt.vue';
import TimeSeriesChart from '../components/charts/TimeSeriesChart.vue';
import type { Column } from '../components/ui/dataTable';
import UiBanner from '../components/ui/UiBanner.vue';
import UiButton from '../components/ui/UiButton.vue';
import UiCard from '../components/ui/UiCard.vue';
import UiDataTable from '../components/ui/UiDataTable.vue';
import UiTile from '../components/ui/UiTile.vue';
import UiTileGrid from '../components/ui/UiTileGrid.vue';
import { useNavigation } from '../composables/useNavigation';
import { RouteName } from '../router/routeNames';
import { useSessionStore } from '../stores/session';
import { useViewStore } from '../stores/view';

const EVENT_KINDS = new Set(['slow-callback', 'never-awaited', 'task-destroyed-pending', 'exception-never-retrieved', 'asyncio']);

type TaskRow = TaskRec & { life: number };

const session = useSessionStore();
const view = useViewStore();
const navigation = useNavigation();

const lagTrack = computed(() => session.model.tracks.get('loopLag'));
const allTasks = computed(() => [...session.model.tasks.values()]);
const events = computed(() => session.model.events.filter((e) => EVENT_KINDS.has(e.kind)));

const tiles = computed(() => {
  const lag = lagTrack.value;
  const p99 = lag ? percentile(lag.v, 0.99) : undefined;
  const maxLag = lag ? maxOf(lag.v) : undefined;
  const slow = events.value.filter((e) => e.kind === 'slow-callback').length;
  const never = events.value.filter((e) => e.kind === 'never-awaited').length;
  return [
    { label: 'Tasks alive', value: fmtCount(allTasks.value.filter((t) => t.end === null).length), sub: `${fmtCount(allTasks.value.length)} seen`, tone: '' as const },
    {
      label: 'Loop lag p99',
      value: fmtMs(p99),
      sub: maxLag !== undefined ? `max ${fmtMs(maxLag)}` : 'needs agent',
      tone: p99 !== undefined && p99 > 100 ? ('bad' as const) : p99 !== undefined && p99 > 20 ? ('warn' as const) : ('' as const),
    },
    { label: 'Slow callbacks', value: String(slow), sub: session.capabilities.asyncioDebug ? '' : 'debug mode off', tone: slow ? ('warn' as const) : ('' as const) },
    { label: 'Never awaited', value: String(never), sub: '', tone: never ? ('bad' as const) : ('' as const) },
  ];
});

const lagSeries = computed<Series[]>(() => {
  const lag = lagTrack.value;
  return lag ? [{ name: 'loop lag', color: chartColor('red'), t: lag.t, v: lag.v, area: true }] : [];
});

const taskRows = computed<TaskRow[]>(() => allTasks.value.map((t) => ({ ...t, life: (t.end ?? session.model.now) - t.start })));

function awaitingIn(task: TaskRec) {
  return task.stack >= 0 ? session.model.userLeaf(task.stack) : undefined;
}

/** The most specific text of a debug event: the offending handle if asyncio reported one. */
function detail(event: EventRec): string {
  return typeof event.handle === 'string' ? event.handle : event.message;
}

function openEvent(event: EventRec): void {
  if (typeof event.file === 'string') {
    session.openSource(event.file, Number(event.line ?? 1));
    return;
  }
  const match = detail(event).match(/at (.+?):(\d+)/);
  if (match) session.openSource(match[1], Number(match[2]));
}

const eventColumns: Column<EventRec>[] = [
  { key: 'time', label: 'Time', numeric: true, value: (e) => e.t, text: (e) => fmtMs(e.t) },
  { key: 'kind', label: 'Kind', value: (e) => e.kind },
  { key: 'blocked', label: 'Blocked', numeric: true, value: (e) => Number(e.seconds ?? 0), text: (e) => (e.seconds ? fmtMs(Number(e.seconds) * 1000) : '') },
  { key: 'details', label: 'Details', cellClass: 'msg', value: (e) => e.message },
];

const taskColumns = computed<Column<TaskRow>[]>(() => [
  { key: 'life', label: 'Lifetime', numeric: true, bar: true, value: (t) => t.life, text: (t) => fmtMs(t.life) },
  { key: 'name', label: 'Task', value: (t) => t.name },
  { key: 'state', label: 'State', value: (t) => t.state },
  { key: 'awaiting', label: 'Awaiting in', cellClass: 'fn', value: (t) => awaitingIn(t)?.func ?? '' },
]);

function showAsyncFlame(): void {
  view.source = 'async';
  navigation.goTo(RouteName.Cpu);
}
</script>

<template>
  <div class="flex-1 overflow-auto px-3.5 pt-3 pb-10">
    <UiBanner v-if="session.live">
      <template v-if="session.capabilities.agent">
        <UiButton
          :primary="!session.capabilities.asyncioDebug"
          :disabled="session.isRunning('asyncioDebug')"
          @click="session.run('asyncioDebug', { enabled: !session.capabilities.asyncioDebug })"
        >
          {{ session.capabilities.asyncioDebug ? 'Disable asyncio debug' : 'Enable asyncio debug' }}
        </UiButton>
        <span class="muted">
          {{
            session.capabilities.asyncioDebug
              ? 'Debug mode is on: slow callbacks, never-awaited coroutines and destroyed pending tasks are reported below.'
              : 'Turn on asyncio debug mode to catch slow callbacks and coroutines that were never awaited (small overhead).'
          }}
        </span>
      </template>
      <span v-else class="muted">Task graphs are read from outside the process. Loop lag and asyncio debug need the in-process agent.</span>
    </UiBanner>
    <UiTileGrid>
      <UiTile v-for="tile in tiles" :key="tile.label" v-bind="tile" />
    </UiTileGrid>
    <UiCard title="Event loop lag" sub="how long a callback had to wait to run — spikes mean something blocked the loop">
      <TimeSeriesChart label="Event loop lag" :domain="session.domain" :series="lagSeries" :selection="view.range" :markers="session.model.markers" :height="130" :y-format="fmtMs" @brush="view.setRange" @clear="view.clearRange" />
    </UiCard>
    <UiCard title="Task timeline" class="mt-3">
      <template #sub>
        <span :style="{ color: chartColor('green') }">■ running </span>
        <span :style="{ color: chartColor('yellow') }">■ awaiting</span>
      </template>
      <div class="max-h-[420px] overflow-auto">
        <TaskGantt :domain="view.range ?? session.domain" @brush="view.setRange" @clear="view.clearRange" />
      </div>
    </UiCard>
    <div class="mt-3 grid grid-cols-[repeat(auto-fit,minmax(380px,1fr))] gap-3">
      <UiCard title="asyncio debug events" class="flex max-h-[380px] flex-col">
        <UiDataTable
          testid="async-events"
          clickable
          :columns="eventColumns"
          :rows="events"
          :row-key="(e) => `${e.t}-${e.kind}-${e.message}`"
          empty="No asyncio debug events. Enable asyncio debug mode to detect slow callbacks and never-awaited coroutines."
          @select="openEvent"
          @activate="openEvent"
        >
          <template #cell-kind="{ row }"><span class="kind" :class="row.kind">{{ row.kind }}</span></template>
          <template #cell-details="{ row }"><span class="mono">{{ detail(row).slice(0, 400) }}</span></template>
        </UiDataTable>
      </UiCard>
      <UiCard title="Tasks" class="flex max-h-[380px] flex-col">
        <template #actions>
          <UiButton @click="showAsyncFlame">Async-aware flame graph</UiButton>
        </template>
        <UiDataTable testid="tasks" :columns="taskColumns" :rows="taskRows" :row-key="(t) => t.id" :limit="300" empty="No asyncio tasks seen yet">
          <template #cell-awaiting="{ row }">
            <button v-if="awaitingIn(row)" type="button" class="link" @click="session.openSource(awaitingIn(row)?.file ?? '', awaitingIn(row)?.line ?? 1)">
              {{ awaitingIn(row)?.func }}:{{ awaitingIn(row)?.line }}
            </button>
          </template>
        </UiDataTable>
      </UiCard>
    </div>
  </div>
</template>
