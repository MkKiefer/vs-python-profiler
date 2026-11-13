<script setup lang="ts">
import type { TabEntry } from '../../composables/useTabs';

defineProps<{ tabs: TabEntry[] }>();
defineEmits<{ select: [tab: TabEntry] }>();
</script>

<template>
  <nav class="bordered-b surface-alt flex gap-0.5 px-2.5" role="tablist" aria-label="Dashboard">
    <button
      v-for="(tab, i) in tabs"
      :key="tab.route"
      type="button"
      class="tab"
      role="tab"
      :aria-selected="tab.active"
      :title="`${tab.label} (${i + 1})`"
      @click="$emit('select', tab)"
    >
      {{ tab.label }}<span v-if="tab.badge" class="badge">{{ tab.badge }}</span>
    </button>
  </nav>
</template>
