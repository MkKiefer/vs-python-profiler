/**
 * Stack samples as runs (profile format 2), the client-side mirror of `SampleRuns` in
 * `python/_vspyprof/collector/store/sample_runs.py`.
 *
 * A run is one thread keeping the same stack and status for `count` consecutive ticks. `ticks`
 * holds the time of every tick, so a time range maps to a range of ticks and every query counts
 * exactly the samples inside it. Format 1 profiles (one row per sample) are converted on load.
 */

/** Longest run the collector writes; queries rely on it to stop scanning early. */
export const MAX_RUN = 255;

/** Sample columns of format 2: typed arrays from `toColumns()`, plain arrays from JSON. */
export interface RunColumns {
  /** time of each tick (ms), for the ticks added by this delta */
  ticks: number[] | Float64Array;
  /** thread id of each thread index, for the threads first seen in this delta */
  threadIds: number[];
  /** first tick of each run (index into all ticks so far) */
  tick: number[] | Int32Array;
  count: number[] | Uint8Array;
  /** index into all thread ids so far */
  thread: number[] | Uint32Array;
  stack: number[] | Int32Array;
  status: number[] | Uint8Array;
}

/** Sample columns of format 1: one row per sample. Only read, from older saved profiles. */
export interface LegacyColumns {
  t: number[];
  tid: number[];
  stack: number[];
  status: number[];
}

export type SampleColumns = RunColumns | LegacyColumns;

/** Receives each run that overlaps a range: its row, and the first and last of its ticks inside the range. */
export type RunVisitor = (row: number, firstTick: number, lastTick: number) => void;

const MIN_CAPACITY = 1024;
/** grow by half: tables only grow, and doubling leaves up to half of a large table unused */
const GROWTH = 1.5;

export function isRunColumns(columns: SampleColumns): columns is RunColumns {
  return 'ticks' in columns;
}

export class SampleTable {
  ticks: Float64Array = new Float64Array(MIN_CAPACITY);
  tickCount = 0;
  threadIds: number[] = [];
  tick: Int32Array = new Int32Array(MIN_CAPACITY);
  count: Uint8Array = new Uint8Array(MIN_CAPACITY);
  thread: Uint32Array = new Uint32Array(MIN_CAPACITY);
  stack: Int32Array = new Int32Array(MIN_CAPACITY);
  status: Uint8Array = new Uint8Array(MIN_CAPACITY);
  /** number of runs */
  length = 0;
  /** number of samples: the runs' counts added up */
  sampleCount = 0;
  private readonly threadIndex = new Map<number, number>();

  /** Append a delta's samples; returns the first new row (rows from there to `length` are new). */
  append(columns: SampleColumns): number {
    const first = this.length;
    if (isRunColumns(columns)) this.appendRuns(columns);
    else this.appendLegacy(columns);
    for (let row = first; row < this.length; row++) this.sampleCount += this.count[row];
    return first;
  }

  /** Thread id of a run. */
  threadId(row: number): number {
    return this.threadIds[this.thread[row]];
  }

  /** Thread index of a thread id, or -1 if it has no samples. */
  indexOfThread(threadId: number): number {
    return this.threadIndex.get(threadId) ?? -1;
  }

  /** Time of the last tick (0 without ticks). */
  get lastTime(): number {
    return this.tickCount ? this.ticks[this.tickCount - 1] : 0;
  }

  /** First tick at or after time `t`. */
  tickAtOrAfter(t: number): number {
    let lo = 0;
    let hi = this.tickCount;
    while (lo < hi) {
      const mid = (lo + hi) >>> 1;
      if (this.ticks[mid] < t) lo = mid + 1;
      else hi = mid;
    }
    return lo;
  }

  /**
   * Visit every run with samples in `[t0, t1)` (the whole table without bounds), with the part of it inside.
   * Runs are ordered by their last tick and at most `MAX_RUN` long, so this is a binary search plus a scan
   * of the runs that overlap the range.
   */
  forEachRun(t0: number | undefined, t1: number | undefined, visit: RunVisitor): void {
    const firstTick = t0 === undefined ? 0 : this.tickAtOrAfter(t0);
    const endTick = t1 === undefined ? this.tickCount : this.tickAtOrAfter(t1);
    if (firstTick >= endTick) return;
    for (let row = this.firstRowEndingAtOrAfter(firstTick); row < this.length; row++) {
      const start = this.tick[row];
      const last = start + this.count[row] - 1;
      if (last - MAX_RUN + 1 >= endTick) break; // this and every later run starts at or after the range's end
      const lo = Math.max(start, firstTick);
      const hi = Math.min(last, endTick - 1);
      if (lo <= hi) visit(row, lo, hi);
    }
  }

  /** Copies of the columns (from the first tick, run and thread), exactly as long as their content. */
  toColumns(): RunColumns {
    const n = this.length;
    return {
      ticks: this.ticks.slice(0, this.tickCount),
      threadIds: this.threadIds.slice(),
      tick: this.tick.slice(0, n),
      count: this.count.slice(0, n),
      thread: this.thread.slice(0, n),
      stack: this.stack.slice(0, n),
      status: this.status.slice(0, n),
    };
  }

  private firstRowEndingAtOrAfter(tick: number): number {
    let lo = 0;
    let hi = this.length;
    while (lo < hi) {
      const mid = (lo + hi) >>> 1;
      if (this.tick[mid] + this.count[mid] - 1 < tick) lo = mid + 1;
      else hi = mid;
    }
    return lo;
  }

  private appendRuns(c: RunColumns): void {
    for (const threadId of c.threadIds) this.internThread(threadId);
    if (this.tickCount === 0 && this.length === 0 && this.adopt(c)) return;
    this.reserveTicks(this.tickCount + c.ticks.length);
    this.ticks.set(c.ticks, this.tickCount);
    this.tickCount += c.ticks.length;
    const n = c.tick.length;
    this.reserveRows(this.length + n);
    this.tick.set(c.tick, this.length);
    this.count.set(c.count, this.length);
    this.thread.set(c.thread, this.length);
    this.stack.set(c.stack, this.length);
    this.status.set(c.status, this.length);
    this.length += n;
  }

  /**
   * Take typed columns over as the table instead of copying them: a dashboard's `init` holds the whole
   * profile, and copying it would hold it twice. The caller hands them over and must not change them.
   */
  private adopt(c: RunColumns): boolean {
    if (
      !(c.ticks instanceof Float64Array) ||
      !(c.tick instanceof Int32Array) ||
      !(c.count instanceof Uint8Array) ||
      !(c.thread instanceof Uint32Array) ||
      !(c.stack instanceof Int32Array) ||
      !(c.status instanceof Uint8Array)
    ) {
      return false;
    }
    this.ticks = c.ticks;
    this.tickCount = c.ticks.length;
    this.tick = c.tick;
    this.count = c.count;
    this.thread = c.thread;
    this.stack = c.stack;
    this.status = c.status;
    this.length = c.tick.length;
    return true;
  }

  /** Format 1: every row is a run of one; rows with the same time share a tick. */
  private appendLegacy(c: LegacyColumns): void {
    const n = c.t.length;
    this.reserveRows(this.length + n);
    this.reserveTicks(this.tickCount + n);
    for (let i = 0; i < n; i++) {
      if (this.tickCount === 0 || this.ticks[this.tickCount - 1] !== c.t[i]) this.ticks[this.tickCount++] = c.t[i];
      const row = this.length++;
      this.tick[row] = this.tickCount - 1;
      this.count[row] = 1;
      this.thread[row] = this.internThread(c.tid[i]);
      this.stack[row] = c.stack[i];
      this.status[row] = c.status[i];
    }
  }

  private internThread(threadId: number): number {
    let index = this.threadIndex.get(threadId);
    if (index === undefined) {
      index = this.threadIds.length;
      this.threadIds.push(threadId);
      this.threadIndex.set(threadId, index);
    }
    return index;
  }

  private reserveTicks(n: number): void {
    if (n <= this.ticks.length) return;
    const ticks = new Float64Array(capacity(this.ticks.length, n));
    ticks.set(this.ticks.subarray(0, this.tickCount));
    this.ticks = ticks;
  }

  private reserveRows(n: number): void {
    if (n <= this.tick.length) return;
    const cap = capacity(this.tick.length, n);
    const used = this.length;
    this.tick = grown(new Int32Array(cap), this.tick.subarray(0, used));
    this.count = grown(new Uint8Array(cap), this.count.subarray(0, used));
    this.thread = grown(new Uint32Array(cap), this.thread.subarray(0, used));
    this.stack = grown(new Int32Array(cap), this.stack.subarray(0, used));
    this.status = grown(new Uint8Array(cap), this.status.subarray(0, used));
  }
}

function capacity(current: number, needed: number): number {
  let cap = Math.max(current, MIN_CAPACITY);
  while (cap < needed) cap = Math.ceil(cap * GROWTH);
  return cap;
}

function grown<A extends Int32Array | Uint8Array | Uint32Array>(target: A, used: A): A {
  target.set(used);
  return target;
}
