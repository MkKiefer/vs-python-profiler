/**
 * Vitest setup for the dashboard specs: browser APIs jsdom lacks, and the rule
 * that any Vue warning or console error fails the test.
 */
import { afterEach, beforeEach, expect, vi } from 'vitest';

// jsdom has no canvas: charts get no 2D context and skip drawing
HTMLCanvasElement.prototype.getContext = (() => null) as typeof HTMLCanvasElement.prototype.getContext;

class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}
globalThis.ResizeObserver = ResizeObserverStub;

let problems: string[] = [];

beforeEach(() => {
  problems = [];
  for (const level of ['warn', 'error'] as const) {
    vi.spyOn(console, level).mockImplementation((...args: unknown[]) => {
      problems.push(`console.${level}: ${args.map(String).join(' ')}`);
    });
  }
});

afterEach(() => {
  vi.restoreAllMocks();
  document.body.innerHTML = '';
  expect(problems, 'Vue warnings or console errors').toEqual([]);
});
