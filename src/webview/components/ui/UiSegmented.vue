<script setup lang="ts" generic="T extends string">
export interface SegmentOption<V extends string> {
  value: V;
  label: string;
  title?: string;
}

defineProps<{ options: readonly SegmentOption<T>[]; label: string }>();
const model = defineModel<T>({ required: true });
</script>

<template>
  <div class="seg" role="radiogroup" :aria-label="label">
    <button
      v-for="option in options"
      :key="option.value"
      type="button"
      role="radio"
      :aria-checked="option.value === model"
      :title="option.title"
      @click="model = option.value"
    >
      {{ option.label }}
    </button>
  </div>
</template>
