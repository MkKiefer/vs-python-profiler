import { onBeforeUnmount, ref, type Ref } from 'vue';

export interface TimeBrushOptions {
  /** x of a pointer event in canvas pixels, clamped to the plot */
  localX: (event: MouseEvent) => number;
  /** canvas x → time */
  xToT: (x: number) => number;
  /** brushing may start here (outside labels) */
  canStart?: (x: number) => boolean;
  onBrush: (t0: number, t1: number) => void;
  /** redraw while dragging */
  onDrag: () => void;
}

/** Minimum drag in pixels that counts as a selection rather than a click. */
const MIN_DRAG_PX = 4;

/**
 * Drag-to-select a time range on a chart. Window listeners exist only while
 * a drag is in progress.
 */
export function useTimeBrush(options: TimeBrushOptions): { drag: Ref<{ x0: number; x1: number } | null>; start: (event: MouseEvent) => void } {
  const drag = ref<{ x0: number; x1: number } | null>(null);

  function move(event: MouseEvent): void {
    if (!drag.value) return;
    drag.value = { x0: drag.value.x0, x1: options.localX(event) };
    options.onDrag();
  }

  function end(): void {
    window.removeEventListener('mousemove', move);
    window.removeEventListener('mouseup', end);
    const current = drag.value;
    drag.value = null;
    options.onDrag();
    if (!current || Math.abs(current.x1 - current.x0) <= MIN_DRAG_PX) return;
    options.onBrush(options.xToT(Math.min(current.x0, current.x1)), options.xToT(Math.max(current.x0, current.x1)));
  }

  function start(event: MouseEvent): void {
    const x = options.localX(event);
    if (options.canStart && !options.canStart(x)) return;
    drag.value = { x0: x, x1: x };
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', end);
  }

  onBeforeUnmount(() => {
    window.removeEventListener('mousemove', move);
    window.removeEventListener('mouseup', end);
  });

  return { drag, start };
}
