import type { Marker } from '../../shared/model';

export interface Series {
  name: string;
  color: string;
  t: number[];
  v: number[];
  area?: boolean;
  dashed?: boolean;
}

/** A short vertical tick at the bottom of the plot (GC collections). */
export interface Tick {
  t: number;
  color: string;
}

export type { Marker };
