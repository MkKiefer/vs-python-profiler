<script setup lang="ts">
withDefaults(defineProps<{ tone?: 'info' | 'warn' }>(), { tone: 'info' });
</script>

<template>
  <div class="banner mb-3" :class="{ warn: tone === 'warn' }" role="status">
    <slot />
  </div>
</template>
