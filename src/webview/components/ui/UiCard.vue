<script setup lang="ts">
withDefaults(defineProps<{ title: string; sub?: string }>(), { sub: '' });
</script>

<template>
  <section class="card" :aria-label="title">
    <h3 class="card-title">
      {{ title }}
      <span v-if="sub || $slots.sub" class="card-sub"><slot name="sub">{{ sub }}</slot></span>
      <span v-if="$slots.actions" class="ml-auto flex gap-1.5"><slot name="actions" /></span>
    </h3>
    <slot />
  </section>
</template>
