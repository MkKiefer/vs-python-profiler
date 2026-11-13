<script setup lang="ts">
withDefaults(defineProps<{ primary?: boolean; icon?: string; title?: string; disabled?: boolean }>(), {
  primary: false,
  icon: undefined,
  title: undefined,
  disabled: false,
});
defineEmits<{ click: [] }>();
</script>

<template>
  <button type="button" class="btn" :class="{ primary }" :title="title" :disabled="disabled" @click="$emit('click')">
    <span v-if="icon" aria-hidden="true">{{ icon }}</span>
    <slot />
  </button>
</template>
