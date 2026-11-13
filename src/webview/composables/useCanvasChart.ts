import { onBeforeUnmount, onMounted, type Ref } from 'vue';

/**
 * Redraw a canvas chart when its container resizes, at most once per frame.
 * Returns `schedule()` for redraws caused by new data or interaction.
 */
export function useCanvasChart(container: Readonly<Ref<HTMLElement | null>>, draw: () => void): { schedule: () => void } {
  let frame = 0;
  let observer: ResizeObserver | undefined;

  function schedule(): void {
    if (frame) return;
    frame = requestAnimationFrame(() => {
      frame = 0;
      draw();
    });
  }

  onMounted(() => {
    observer = new ResizeObserver(schedule);
    if (container.value) observer.observe(container.value);
    schedule();
  });

  onBeforeUnmount(() => {
    observer?.disconnect();
    if (frame) cancelAnimationFrame(frame);
  });

  return { schedule };
}
