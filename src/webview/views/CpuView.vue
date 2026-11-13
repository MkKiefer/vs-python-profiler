<script setup lang="ts">
/** CPU tab: flame graph, call tree, bottom-up tree or top functions (`?view=`). */
import { computed } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import type { FnStat } from '../../shared/model';
import { fmtPct, shortPath } from '../../shared/format';
import { frameColor } from '../charts/colors';
import CallTree from '../components/charts/CallTree.vue';
import FlameGraph from '../components/charts/FlameGraph.vue';
import CategoryLegend from '../components/cpu/CategoryLegend.vue';
import CpuToolbar from '../components/cpu/CpuToolbar.vue';
import type { Column } from '../components/ui/dataTable';
import UiDataTable from '../components/ui/UiDataTable.vue';
import { useCpuProfile } from '../composables/useCpuProfile';
import { useNavigation } from '../composables/useNavigation';
import { cpuViewKind, type CpuViewKind } from '../router/routeNames';
import { useSessionStore } from '../stores/session';
import { useViewStore } from '../stores/view';

const route = useRoute();
const router = useRouter();
const session = useSessionStore();
const view = useViewStore();
const navigation = useNavigation();
const { counts, total, treeOptions } = useCpuProfile();

const kind = computed<CpuViewKind | null>({
  get: () => cpuViewKind(route.query.view),
  set: (value) => void router.replace({ query: { view: value ?? undefined } }),
});

const tree = computed(() =>
  session.model.buildTree(counts.value, { ...treeOptions.value, inverted: kind.value === 'inverted' }),
);
const resetKey = computed(() => `${kind.value}:${view.structureKey}`);
const summary = computed(() => `${total.value.toLocaleString()} samples ≈ ${session.fmtSamples(total.value)} of thread time`);

const topRows = computed(() => session.model.topFunctions(counts.value, view.hideLibs).slice(0, 1000));
const fn = (row: FnStat) => session.model.fns[row.fn];
const topColumns = computed<Column<FnStat>[]>(() => [
  { key: 'self', label: 'Self', numeric: true, bar: true, value: (r) => r.self, text: (r) => fmtPct(r.self, total.value) },
  { key: 'total', label: 'Total', numeric: true, value: (r) => r.total, text: (r) => fmtPct(r.total, total.value) },
  { key: 'selfTime', label: 'Self time', numeric: true, value: (r) => r.self, text: (r) => session.fmtSamples(r.self) },
  { key: 'totalTime', label: 'Total time', numeric: true, value: (r) => r.total, text: (r) => session.fmtSamples(r.total) },
  { key: 'function', label: 'Function', cellClass: 'fn', value: (r) => fn(r).func },
  { key: 'location', label: 'Location', cellClass: 'loc', value: (r) => fn(r).file, text: (r) => `‎${shortPath(fn(r).file, 3)}:${fn(r).minLine}` },
]);

function openFn(row: FnStat): void {
  session.openSource(fn(row).file, fn(row).minLine);
}
</script>

<template>
  <div class="flex min-h-0 flex-1 flex-col overflow-hidden">
    <CpuToolbar v-model:kind="kind" />
    <template v-if="kind === 'flame'">
      <CategoryLegend :summary="summary" />
      <FlameGraph
        :model="session.model"
        :root="tree"
        :format="session.fmtSamples"
        :search="view.search"
        :reset-key="resetKey"
        @open="session.openSource"
        @focus="navigation.focusFunction"
      />
    </template>
    <CallTree
      v-else-if="kind === 'tree' || kind === 'inverted'"
      testid="call-tree"
      :model="session.model"
      :root="tree"
      :format="session.fmtSamples"
      :reset-key="resetKey"
      @open="session.openSource"
      @focus="navigation.focusFunction"
    />
    <UiDataTable
      v-else
      testid="top-functions"
      clickable
      :columns="topColumns"
      :rows="topRows"
      :row-key="(r) => r.fn"
      empty="No samples in this selection"
      @select="(r) => navigation.focusFunction(r.fn)"
      @activate="openFn"
    >
      <template #cell-function="{ row }">
        <span class="cat-dot" :style="{ background: frameColor(fn(row).cat, fn(row).func) }" />{{ fn(row).func }}
      </template>
    </UiDataTable>
  </div>
</template>
