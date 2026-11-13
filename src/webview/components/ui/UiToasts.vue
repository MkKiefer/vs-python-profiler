<script setup lang="ts">
import { useNotificationsStore } from '../../stores/notifications';

const notifications = useNotificationsStore();
</script>

<template>
  <div class="fixed right-3 bottom-3 z-50 flex max-w-[480px] flex-col gap-2" aria-live="assertive">
    <div v-for="item in notifications.items" :key="item.id" class="banner warn" role="alert" :data-testid="`toast-${item.id}`">
      <span class="flex-1">{{ item.text }}</span>
      <button type="button" class="link" aria-label="Dismiss" @click="notifications.dismiss(item.id)">✕</button>
    </div>
  </div>
</template>
