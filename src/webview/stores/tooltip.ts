import { defineStore } from 'pinia';
import { ref } from 'vue';

export interface TooltipRow {
  label: string;
  value: string;
  /** colour swatch before the label (a series colour) */
  swatch?: string;
}

export interface TooltipContent {
  title: string;
  sub?: string;
  rows?: TooltipRow[];
  hint?: string;
}

/** The one hover tooltip shared by every chart. */
export const useTooltipStore = defineStore('tooltip', () => {
  const content = ref<TooltipContent | null>(null);
  const x = ref(0);
  const y = ref(0);

  function show(clientX: number, clientY: number, next: TooltipContent): void {
    x.value = clientX;
    y.value = clientY;
    content.value = next;
  }

  function hide(): void {
    content.value = null;
  }

  return { content, x, y, show, hide };
});
