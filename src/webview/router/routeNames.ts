/** Every route of the dashboard; call sites navigate by name, never by path. */
export enum RouteName {
  Overview = 'overview',
  Cpu = 'cpu',
  /** callers and callees of one function: /cpu/focus/:fn */
  CpuFocus = 'cpu-focus',
  Memory = 'memory',
  Async = 'async',
  Timeline = 'timeline',
}

/** The views of the CPU tab, carried in the `?view=` query. */
export type CpuViewKind = 'flame' | 'tree' | 'inverted' | 'top';

export const CPU_VIEW_KINDS: readonly CpuViewKind[] = ['flame', 'tree', 'inverted', 'top'];

export function cpuViewKind(value: unknown): CpuViewKind {
  return CPU_VIEW_KINDS.find((kind) => kind === value) ?? 'flame';
}
