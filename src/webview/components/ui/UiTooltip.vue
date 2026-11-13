<script setup lang="ts">
import { ref, watch } from 'vue';
import { useTooltipStore } from '../../stores/tooltip';

const tooltip = useTooltipStore();
const el = ref<HTMLElement | null>(null);
const left = ref(0);
const top = ref(0);

// place next to the pointer, flipped to stay inside the window
watch(
  () => [tooltip.content, tooltip.x, tooltip.y],
  () => {
    const box = el.value?.getBoundingClientRect();
    const width = box?.width ?? 0;
    const height = box?.height ?? 0;
    left.value = Math.max(4, Math.min(window.innerWidth - width - 8, tooltip.x + 14));
    top.value = Math.max(4, tooltip.y + height + 20 > window.innerHeight ? tooltip.y - height - 10 : tooltip.y + 16);
  },
  { flush: 'post' },
);
</script>

<template>
  <div v-if="tooltip.content" ref="el" class="tooltip" role="tooltip" :style="{ left: `${left}px`, top: `${top}px` }">
    <div class="tooltip-title">{{ tooltip.content.title }}</div>
    <div v-if="tooltip.content.sub" class="tooltip-sub">{{ tooltip.content.sub }}</div>
    <table v-if="tooltip.content.rows?.length">
      <tbody>
        <tr v-for="row in tooltip.content.rows" :key="row.label">
          <td>
            <span v-if="row.swatch" :style="{ color: row.swatch }">■ </span>{{ row.label }}
          </td>
          <td>{{ row.value }}</td>
        </tr>
      </tbody>
    </table>
    <div v-if="tooltip.content.hint" class="tooltip-sub">{{ tooltip.content.hint }}</div>
  </div>
</template>
