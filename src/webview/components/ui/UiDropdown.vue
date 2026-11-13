<script setup lang="ts">
defineProps<{ label: string }>();
</script>

<template>
  <details class="dropdown">
    <summary class="btn">{{ label }} ▾</summary>
    <div class="dropdown-menu" role="group" :aria-label="label">
      <slot />
    </div>
  </details>
</template>
