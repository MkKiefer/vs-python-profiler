<script setup lang="ts">
/** CPU tab controls: view kind, sample mode, grouping, threads, library folding and search. */
import { computed } from 'vue';
import type { Mode, Source } from '../../../shared/model';
import type { CpuViewKind } from '../../router/routeNames';
import { useSessionStore } from '../../stores/session';
import { useViewStore } from '../../stores/view';
import UiCheckbox from '../ui/UiCheckbox.vue';
import UiDropdown from '../ui/UiDropdown.vue';
import UiSegmented, { type SegmentOption } from '../ui/UiSegmented.vue';

/** `null` on the callers/callees view, which has no kind switch. */
const kind = defineModel<CpuViewKind | null>('kind', { required: true });

const session = useSessionStore();
const view = useViewStore();

const KINDS: SegmentOption<CpuViewKind>[] = [
  { value: 'flame', label: 'Flame graph' },
  { value: 'tree', label: 'Call tree' },
  { value: 'inverted', label: 'Bottom-up', title: 'Inverted tree: where time is spent, then who called it' },
  { value: 'top', label: 'Top functions' },
];
const MODES: SegmentOption<Mode>[] = [
  { value: 'wall', label: 'Wall', title: 'All samples, including waiting/sleeping (latency)' },
  { value: 'cpu', label: 'CPU', title: 'Only samples where the thread was running on a CPU' },
  { value: 'gil', label: 'GIL', title: 'Only samples where the thread held the GIL' },
];
const SOURCES: SegmentOption<Source>[] = [
  { value: 'threads', label: 'Threads' },
  { value: 'async', label: 'Async tasks', title: 'Async-aware stacks: coroutine chains per asyncio task' },
];

const kindModel = computed<CpuViewKind>({
  get: () => kind.value ?? 'flame',
  set: (value) => (kind.value = value),
});
const threads = computed(() => session.model.threadList());
const threadLabel = computed(() => {
  const n = view.threads.length;
  return n ? `${n} thread${n > 1 ? 's' : ''}` : 'All threads';
});
</script>

<template>
  <div class="bordered-b flex flex-wrap items-center gap-x-3.5 gap-y-2 px-3.5 py-2">
    <UiSegmented v-if="kind !== null" v-model="kindModel" :options="KINDS" label="View" />
    <div class="flex items-center gap-1.5">
      <span class="muted text-[0.85em]">Mode</span>
      <UiSegmented v-model="view.mode" :options="MODES" label="Mode" />
    </div>
    <div class="flex items-center gap-1.5">
      <span class="muted text-[0.85em]">Group by</span>
      <UiSegmented v-model="view.source" :options="SOURCES" label="Group by" />
    </div>
    <UiDropdown :label="threadLabel">
      <UiCheckbox
        v-for="t in threads"
        :key="t.tid"
        :model-value="view.threads.includes(t.tid)"
        :label="`${t.name} (${t.samples})`"
        @update:model-value="(included: boolean) => view.setThread(t.tid, included)"
      />
    </UiDropdown>
    <UiCheckbox v-model="view.hideLibs" label="Hide libraries" title="Collapse stdlib and site-packages frames into the call that entered them" />
    <UiCheckbox v-model="view.byLine" label="By line" title="Split functions by line number" />
    <input v-model="view.search" type="search" class="w-[200px]" placeholder="Search functions / files" aria-label="Search functions / files" />
  </div>
</template>
