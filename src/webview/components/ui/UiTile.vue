<script setup lang="ts">
export type TileTone = '' | 'warn' | 'bad';

withDefaults(defineProps<{ label: string; value: string; sub?: string; tone?: TileTone }>(), { sub: '', tone: '' });
</script>

<template>
  <div class="tile" :class="tone" role="group" :aria-label="label">
    <div class="tile-label">{{ label }}</div>
    <div class="tile-value">{{ value }}</div>
    <div v-if="sub" class="tile-sub">{{ sub }}</div>
  </div>
</template>
