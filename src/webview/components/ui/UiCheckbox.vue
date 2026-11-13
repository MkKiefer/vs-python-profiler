<script setup lang="ts">
withDefaults(defineProps<{ label: string; title?: string }>(), { title: undefined });
const checked = defineModel<boolean>({ required: true });
</script>

<template>
  <label class="inline-flex cursor-pointer items-center gap-1 whitespace-nowrap" :title="title">
    <input v-model="checked" type="checkbox" />
    {{ label }}
  </label>
</template>
