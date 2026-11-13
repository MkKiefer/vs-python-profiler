<script setup lang="ts">
/** Session title, state, the selected time range and the session actions. */
import { computed } from 'vue';
import { fmtMs } from '../../../shared/format';
import { useSessionStore } from '../../stores/session';
import { useViewStore } from '../../stores/view';
import UiButton from '../ui/UiButton.vue';

const session = useSessionStore();
const view = useViewStore();

const meta = computed(() => {
  const m = session.model.meta;
  return [
    m.pid ? `PID ${m.pid}` : '',
    m.python ? `Python ${m.python}${m.freeThreaded ? 't' : ''}` : '',
    m.platform ? String(m.platform) : '',
  ]
    .filter(Boolean)
    .join(' · ');
});

const stateLabel = computed(() => (session.state === 'file' ? 'saved profile' : session.state));
</script>

<template>
  <header class="bordered-b surface-alt flex flex-wrap items-center gap-2.5 px-3.5 py-2">
    <span class="max-w-[40vw] truncate text-[1.1em] font-semibold" :title="session.label">{{ session.label }}</span>
    <span class="pill" :class="session.state" data-testid="session-state">{{ stateLabel }}</span>
    <span class="muted text-[0.9em] whitespace-nowrap">{{ meta }}</span>
    <span v-if="view.range" class="range-chip" data-testid="range-chip">
      {{ fmtMs(view.range[0]) }} – {{ fmtMs(view.range[1]) }}
      <button type="button" title="Clear time range" aria-label="Clear time range" @click="view.clearRange()">✕</button>
    </span>
    <span class="flex-1" />
    <template v-if="session.live">
      <UiButton icon="⚑" title="Drop a named marker on the timeline" :disabled="session.isRunning('mark')" @click="session.run('mark', {})">
        Marker
      </UiButton>
      <UiButton
        v-if="session.capabilities.agent"
        icon="📷"
        title="Take a memory snapshot (starts tracemalloc if needed)"
        :disabled="session.isRunning('snapshot')"
        @click="session.run('snapshot', {})"
      >
        Snapshot
      </UiButton>
      <UiButton primary icon="■" :disabled="session.isRunning('stop')" @click="session.run('stop', {})">Stop</UiButton>
    </template>
    <UiButton title="Save as .pyprof" :disabled="session.isRunning('save')" @click="session.run('save', {})">Save</UiButton>
    <UiButton title="Export to speedscope" :disabled="session.isRunning('exportSpeedscope')" @click="session.run('exportSpeedscope', {})">
      Export
    </UiButton>
  </header>
</template>
