<script setup lang="ts">
/** Callers and callees of one function: /cpu/focus/:fn. */
import { computed } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { shortPath } from '../../shared/format';
import { frameColor } from '../charts/colors';
import CallTree from '../components/charts/CallTree.vue';
import FlameGraph from '../components/charts/FlameGraph.vue';
import CpuToolbar from '../components/cpu/CpuToolbar.vue';
import { useCpuProfile } from '../composables/useCpuProfile';
import { useNavigation } from '../composables/useNavigation';
import { RouteName } from '../router/routeNames';
import { useSessionStore } from '../stores/session';
import { useViewStore } from '../stores/view';

const route = useRoute();
const router = useRouter();
const session = useSessionStore();
const view = useViewStore();
const navigation = useNavigation();
const { counts, treeOptions } = useCpuProfile();

const fnId = computed(() => Number(route.params.fn));
const fn = computed(() => session.model.fns[fnId.value]);
const resetKey = computed(() => `${fnId.value}:${view.structureKey}`);
const callers = computed(() => session.model.buildTree(counts.value, { ...treeOptions.value, focusFn: fnId.value, focus: 'callers' }));
const callees = computed(() => session.model.buildTree(counts.value, { ...treeOptions.value, focusFn: fnId.value, focus: 'callees' }));

function clearFocus(): void {
  void router.push({ name: RouteName.Cpu });
}
</script>

<template>
  <div class="flex min-h-0 flex-1 flex-col overflow-hidden">
    <CpuToolbar :kind="null" />
    <template v-if="fn">
      <div class="crumbs" data-testid="focus-banner">
        <span class="cat-dot" :style="{ background: frameColor(fn.cat, fn.func) }" />
        <b>{{ fn.func }}</b>
        <span class="muted">{{ shortPath(fn.file, 3) }}:{{ fn.minLine }}</span>
        <button type="button" class="link" @click="session.openSource(fn.file, fn.minLine)">open source</button>
        <span class="flex-1" />
        <button type="button" class="link" @click="clearFocus">✕ clear focus</button>
      </div>
      <div class="grid min-h-0 flex-1 grid-cols-2">
        <section class="split-pane" aria-label="Callers">
          <h4>Callers (who calls it)</h4>
          <CallTree
            testid="callers"
            :model="session.model"
            :root="callers"
            :format="session.fmtSamples"
            :reset-key="resetKey"
            @open="session.openSource"
            @focus="navigation.focusFunction"
          />
        </section>
        <section class="split-pane" aria-label="Callees">
          <h4>Callees (what it spends time in)</h4>
          <FlameGraph
            :model="session.model"
            :root="callees"
            :format="session.fmtSamples"
            :search="view.search"
            :reset-key="resetKey"
            @open="session.openSource"
            @focus="navigation.focusFunction"
          />
        </section>
      </div>
    </template>
    <div v-else class="empty">
      This function is not in the profile.
      <button type="button" class="link" @click="clearFocus">Back to the flame graph</button>
    </div>
  </div>
</template>
