import { defineStore } from 'pinia';
import { ref } from 'vue';

export interface Notification {
  id: number;
  text: string;
}

const VISIBLE_MS = 6000;

/** Toasts for failed commands and other things the user must not miss. */
export const useNotificationsStore = defineStore('notifications', () => {
  const items = ref<Notification[]>([]);
  let nextId = 1;

  function dismiss(id: number): void {
    items.value = items.value.filter((item) => item.id !== id);
  }

  function error(text: string): void {
    const id = nextId++;
    items.value = [...items.value, { id, text }];
    setTimeout(() => dismiss(id), VISIBLE_MS);
  }

  return { items, error, dismiss };
});
