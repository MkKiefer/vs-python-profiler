<script setup lang="ts">
/** Dashboard shell: header, tabs, the routed tab view, tooltip and toasts. */
import { onBeforeUnmount, onMounted, watch } from 'vue';
import { RouterView, useRoute, useRouter } from 'vue-router';
import DashboardHeader from './components/layout/DashboardHeader.vue';
import TabBar from './components/layout/TabBar.vue';
import UiToasts from './components/ui/UiToasts.vue';
import UiTooltip from './components/ui/UiTooltip.vue';
import { useNavigation } from './composables/useNavigation';
import { useTabs, type TabEntry } from './composables/useTabs';
import { useHostClient } from './services/hostClientKey';
import { useSessionStore } from './stores/session';
import { useViewStore } from './stores/view';

const host = useHostClient();
const session = useSessionStore();
const view = useViewStore();
const router = useRouter();
const route = useRoute();
const navigation = useNavigation();
const tabs = useTabs();

// reopen where the panel was left
const saved = host.loadState();
if (saved) {
  view.restore(saved);
  if (saved.route) void router.replace(saved.route);
}

watch(
  () => view.persisted(route.fullPath),
  (state) => host.saveState(state),
  { deep: true },
);

function select(tab: TabEntry): void {
  void router.push(tab.target);
}

/** Keys 1–5 switch tabs (not while typing). */
function onKey(event: KeyboardEvent): void {
  if (event.target instanceof HTMLInputElement || event.target instanceof HTMLSelectElement) return;
  if (event.ctrlKey || event.metaKey || event.altKey) return;
  const tab = tabs.value[Number(event.key) - 1];
  if (tab) select(tab);
}

let disconnect: (() => void) | undefined;
let stopReveal: (() => void) | undefined;

onMounted(() => {
  stopReveal = host.onEvent((event) => {
    if (event.type === 'reveal') navigation.focusFunction(event.fn);
  });
  disconnect = session.connect();
  window.addEventListener('keydown', onKey);
});

onBeforeUnmount(() => {
  stopReveal?.();
  disconnect?.();
  window.removeEventListener('keydown', onKey);
});
</script>

<template>
  <div class="flex h-full flex-col">
    <template v-if="session.loaded">
      <DashboardHeader />
      <TabBar :tabs="tabs" @select="select" />
      <RouterView />
    </template>
    <div v-else class="muted p-6">Loading profile…</div>
    <UiTooltip />
    <UiToasts />
  </div>
</template>
