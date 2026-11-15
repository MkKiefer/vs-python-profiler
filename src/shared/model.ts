/**
 * ProfileModel: the client-side mirror of the collector's store.
 *
 * Shared by the extension host (hotspots, editor heat, CodeLens) and the
 * dashboard webview (all charts). It is fed by `applyDelta()` – live deltas
 * and saved `.vspyprof` files have the same shape.
 */

export const enum Cat {
  User = 0,
  Lib = 1,
  Std = 2,
  Synth = 3,
}

/** Thread status bits of a sample (`_remote_debugging.THREAD_STATUS_*`). */
export const STATUS_HAS_GIL = 1;
export const STATUS_ON_CPU = 2;
export const STATUS_GIL_REQUESTED = 8;

const DEFAULT_RATE_HZ = 1000;

export type Mode = 'wall' | 'cpu' | 'gil';
export type Source = 'threads' | 'async';

export interface Columns {
  t: number[];
  tid: number[];
  stack: number[];
  status: number[];
}

export interface TaskRec {
  id: number;
  name: string;
  parent: number | null;
  thread: number;
  start: number;
  end: number | null;
  stack: number;
  state: 'running' | 'waiting' | 'done';
}

export interface SnapshotRec {
  id: number;
  label: string;
  t: number;
  totalSize: number;
  totalCount: number;
  otherSize: number;
  otherCount: number;
  traced: number;
  peak: number;
  takeMs?: number;
  entries: [number, number, number][]; // [stack, size, count]
}

export interface EventRec {
  t: number;
  kind: string;
  message: string;
  [k: string]: unknown;
}

/** Session facts recorded by the collector (`ProfileMeta` in `collector/store/profile_meta.py`). */
export interface ProfileMeta {
  pid?: number;
  python?: string;
  implementation?: string;
  freeThreaded?: boolean;
  platform?: string;
  startedAt?: number;
  label?: string | null;
  agent?: boolean;
  executable?: string | null;
  argv?: string[];
  cwd?: string | null;
  options?: { rateHz?: number };
}

export interface ObjectCounts {
  t: number;
  counts: [string, number][];
}

export type GcRecord = [t: number, durationMs: number, generation: number, collected: number, heapSize: number];
export type TaskEvent = [t: number, task: number, state: string];
export type Marker = [t: number, name: string];

export interface Delta {
  now: number;
  frames: [string, string, number, number][];
  stacks: [number, number][];
  samples: Columns;
  asyncSamples: Columns;
  tracks: Record<string, [number, number][]>;
  gc: GcRecord[];
  markers: Marker[];
  events: EventRec[];
  taskEvents: TaskEvent[];
  tasks: TaskRec[];
  threads: Record<string, string>;
  snapshots: SnapshotRec[];
  objectCounts: ObjectCounts[];
  meta?: ProfileMeta;
  stats?: SamplingStats;
  format?: string;
}

export interface SamplingStats {
  samples: number;
  errors: number;
  rateHz: number;
}

export interface LineHeat {
  self: number;
  total: number;
}

export interface SnapshotDiffRow {
  sid: number;
  dSize: number;
  dCount: number;
  size: number;
  count: number;
}

export interface Frame {
  file: string;
  func: string;
  line: number;
  cat: Cat;
  fn: number;
}

export interface Fn {
  id: number;
  file: string;
  func: string;
  cat: Cat;
  minLine: number;
}

export interface Filter {
  t0?: number;
  t1?: number;
  mode?: Mode;
  threads?: Set<number> | null;
  source?: Source;
}

export interface TreeNode {
  key: number; // fn id or frame id (byLine)
  fn: number;
  frame: number;
  total: number;
  self: number;
  children: TreeNode[];
}

export interface TreeOptions {
  inverted?: boolean;
  byLine?: boolean;
  hideLibs?: boolean;
  /** re-root at a function: 'callees' (fn → leaf) or 'callers' (fn → root) */
  focusFn?: number;
  focus?: 'callees' | 'callers';
}

export interface FnStat {
  fn: number;
  self: number;
  total: number;
}

class SampleTable {
  t = new Float64Array(1024);
  tid = new Float64Array(1024);
  stack = new Int32Array(1024);
  status = new Uint8Array(1024);
  length = 0;

  append(c: Columns): void {
    const n = c.t.length;
    if (!n) return;
    this.reserve(this.length + n);
    const base = this.length;
    for (let i = 0; i < n; i++) {
      this.t[base + i] = c.t[i];
      this.tid[base + i] = c.tid[i];
      this.stack[base + i] = c.stack[i];
      this.status[base + i] = c.status[i];
    }
    this.length += n;
  }

  private reserve(n: number): void {
    if (n <= this.t.length) return;
    let cap = this.t.length;
    while (cap < n) cap *= 2;
    const used = this.length;
    const t = new Float64Array(cap);
    t.set(this.t.subarray(0, used));
    const tid = new Float64Array(cap);
    tid.set(this.tid.subarray(0, used));
    const stack = new Int32Array(cap);
    stack.set(this.stack.subarray(0, used));
    const status = new Uint8Array(cap);
    status.set(this.status.subarray(0, used));
    this.t = t;
    this.tid = tid;
    this.stack = stack;
    this.status = status;
  }

  /** first index with t >= value */
  lowerBound(value: number): number {
    let lo = 0;
    let hi = this.length;
    while (lo < hi) {
      const mid = (lo + hi) >>> 1;
      if (this.t[mid] < value) lo = mid + 1;
      else hi = mid;
    }
    return lo;
  }

  toColumns(): Columns {
    const n = this.length;
    return {
      t: Array.from(this.t.subarray(0, n)),
      tid: Array.from(this.tid.subarray(0, n)),
      stack: Array.from(this.stack.subarray(0, n)),
      status: Array.from(this.status.subarray(0, n)),
    };
  }
}

export class ProfileModel {
  frames: Frame[] = [];
  fns: Fn[] = [];
  private fnIndex = new Map<string, number>();
  stackParent: number[] = [];
  stackFrame: number[] = [];
  samples = new SampleTable();
  asyncSamples = new SampleTable();
  tracks = new Map<string, { t: number[]; v: number[] }>();
  gc: GcRecord[] = [];
  markers: Marker[] = [];
  events: EventRec[] = [];
  threads = new Map<number, string>();
  threadSampleCounts = new Map<number, number>();
  tasks = new Map<number, TaskRec>();
  taskEvents: TaskEvent[] = [];
  snapshots: SnapshotRec[] = [];
  objectCounts: ObjectCounts[] = [];
  meta: ProfileMeta = {};
  stats: SamplingStats = { samples: 0, errors: 0, rateHz: 0 };
  now = 0;
  /** bumps on every applied delta; use for memoisation */
  version = 0;

  private pathCache = new Map<number, number[]>();

  applyDelta(d: Delta): void {
    for (const [file, func, line, cat] of d.frames) {
      const key = file + '\u0000' + func;
      let fn = this.fnIndex.get(key);
      if (fn === undefined) {
        fn = this.fns.length;
        this.fns.push({ id: fn, file, func, cat, minLine: line || Number.MAX_SAFE_INTEGER });
        this.fnIndex.set(key, fn);
      } else if (line && line < this.fns[fn].minLine) {
        this.fns[fn].minLine = line;
      }
      this.frames.push({ file, func, line, cat, fn });
    }
    for (const [parent, frame] of d.stacks) {
      this.stackParent.push(parent);
      this.stackFrame.push(frame);
    }
    this.samples.append(d.samples);
    this.asyncSamples.append(d.asyncSamples);
    for (const tid of d.samples.tid) {
      this.threadSampleCounts.set(tid, (this.threadSampleCounts.get(tid) ?? 0) + 1);
    }
    for (const [name, pts] of Object.entries(d.tracks)) {
      let tr = this.tracks.get(name);
      if (!tr) this.tracks.set(name, (tr = { t: [], v: [] }));
      for (const [t, v] of pts) {
        tr.t.push(t);
        tr.v.push(v);
      }
    }
    this.gc.push(...d.gc);
    this.markers.push(...d.markers);
    this.events.push(...d.events);
    this.taskEvents.push(...d.taskEvents);
    for (const t of d.tasks) this.tasks.set(t.id, t);
    for (const [k, v] of Object.entries(d.threads)) this.threads.set(Number(k), v);
    for (const s of d.snapshots) {
      const i = this.snapshots.findIndex((x) => x.id === s.id);
      if (i >= 0) this.snapshots[i] = s;
      else this.snapshots.push(s);
    }
    this.objectCounts.push(...d.objectCounts);
    if (d.meta) this.meta = { ...this.meta, ...d.meta };
    if (d.stats) this.stats = d.stats;
    this.now = Math.max(this.now, d.now ?? 0);
    this.version++;
  }

  /** Serialise everything back into one delta (for webview init and saving). */
  toDelta(): Delta {
    const tracks: Record<string, [number, number][]> = {};
    for (const [k, tr] of this.tracks) tracks[k] = tr.t.map((t, i) => [t, tr.v[i]]);
    return {
      now: this.now,
      frames: this.frames.map((f) => [f.file, f.func, f.line, f.cat]),
      stacks: this.stackParent.map((p, i) => [p, this.stackFrame[i]]),
      samples: this.samples.toColumns(),
      asyncSamples: this.asyncSamples.toColumns(),
      tracks,
      gc: this.gc,
      markers: this.markers,
      events: this.events,
      taskEvents: this.taskEvents,
      tasks: [...this.tasks.values()],
      threads: Object.fromEntries([...this.threads].map(([k, v]) => [String(k), v])),
      snapshots: this.snapshots,
      objectCounts: this.objectCounts,
      meta: this.meta,
      stats: this.stats,
      format: 'vspyprof',
    };
  }

  /** Configured sampling rate (the measured one is `stats.rateHz`). */
  get rateHz(): number {
    const rate = Number(this.meta.options?.rateHz);
    return rate > 0 ? rate : DEFAULT_RATE_HZ;
  }

  /** Approximate time one sample stands for, per thread. */
  get sampleIntervalMs(): number {
    return 1000 / this.rateHz;
  }

  get duration(): number {
    const n = this.samples.length;
    const last = n ? this.samples.t[n - 1] : 0;
    return Math.max(this.now, last);
  }

  /** frame ids root → leaf for a stack id (memoised) */
  path(sid: number): number[] {
    const cached = this.pathCache.get(sid);
    if (cached) return cached;
    const out: number[] = [];
    let s = sid;
    while (s >= 0) {
      out.push(this.stackFrame[s]);
      s = this.stackParent[s];
    }
    out.reverse();
    if (this.pathCache.size > 500_000) this.pathCache.clear();
    this.pathCache.set(sid, out);
    return out;
  }

  threadName(tid: number): string {
    return this.threads.get(tid) ?? `Thread ${tid}`;
  }

  // ------------------------------------------------------------- queries
  countStacks(f: Filter = {}): Map<number, number> {
    const table = f.source === 'async' ? this.asyncSamples : this.samples;
    const counts = new Map<number, number>();
    const start = f.t0 !== undefined ? table.lowerBound(f.t0) : 0;
    const end = f.t1 !== undefined ? table.lowerBound(f.t1) : table.length;
    const mask = f.source === 'async' ? 0 : f.mode === 'cpu' ? STATUS_ON_CPU : f.mode === 'gil' ? STATUS_HAS_GIL : 0;
    const threads = f.threads && f.threads.size ? f.threads : null;
    for (let i = start; i < end; i++) {
      if (mask && !(table.status[i] & mask)) continue;
      if (threads && !threads.has(table.tid[i])) continue;
      const s = table.stack[i];
      counts.set(s, (counts.get(s) ?? 0) + 1);
    }
    return counts;
  }

  totalWeight(counts: Map<number, number>): number {
    let n = 0;
    for (const v of counts.values()) n += v;
    return n;
  }

  private visiblePath(sid: number, opts: TreeOptions): number[] {
    let frames = this.path(sid);
    if (opts.hideLibs) {
      const kept: number[] = [];
      let prevUser = true; // keep the entry frame into a library, collapse the rest
      for (const fr of frames) {
        const isUser = this.frames[fr].cat === Cat.User;
        if (isUser || prevUser) kept.push(fr);
        prevUser = isUser;
      }
      frames = kept.length ? kept : frames.slice(-1);
    }
    return frames;
  }

  buildTree(counts: Map<number, number>, opts: TreeOptions = {}): TreeNode {
    const root: TreeNode = { key: -1, fn: -1, frame: -1, total: 0, self: 0, children: [] };
    const childMaps = new Map<TreeNode, Map<number, TreeNode>>();
    const childOf = (node: TreeNode, frame: number): TreeNode => {
      const fn = this.frames[frame].fn;
      const key = opts.byLine ? frame : fn;
      let m = childMaps.get(node);
      if (!m) childMaps.set(node, (m = new Map<number, TreeNode>()));
      let c = m.get(key);
      if (!c) {
        c = { key, fn, frame, total: 0, self: 0, children: [] };
        m.set(key, c);
        node.children.push(c);
      }
      return c;
    };
    for (const [sid, w] of counts) {
      let frames = this.visiblePath(sid, opts);
      if (opts.focusFn !== undefined) {
        const idx = frames.findIndex((fr) => this.frames[fr].fn === opts.focusFn);
        if (idx < 0) continue;
        frames = opts.focus === 'callers' ? frames.slice(0, idx + 1).reverse() : frames.slice(idx);
      } else if (opts.inverted) {
        frames = frames.slice().reverse();
      }
      root.total += w;
      let node = root;
      for (const fr of frames) {
        node = childOf(node, fr);
        node.total += w;
      }
      node.self += w;
    }
    const sort = (n: TreeNode): void => {
      n.children.sort((a, b) => b.total - a.total);
      n.children.forEach(sort);
    };
    sort(root);
    return root;
  }

  topFunctions(counts: Map<number, number>, hideLibs = false): FnStat[] {
    const self = new Map<number, number>();
    const total = new Map<number, number>();
    const seen = new Set<number>();
    for (const [sid, w] of counts) {
      const frames = this.path(sid);
      if (!frames.length) continue;
      let leaf = frames[frames.length - 1];
      if (hideLibs) {
        for (let i = frames.length - 1; i >= 0; i--) {
          if (this.frames[frames[i]].cat === Cat.User) {
            leaf = frames[i];
            break;
          }
        }
      }
      const lf = this.frames[leaf].fn;
      self.set(lf, (self.get(lf) ?? 0) + w);
      seen.clear();
      for (const fr of frames) {
        const fn = this.frames[fr].fn;
        if (seen.has(fn)) continue;
        seen.add(fn);
        total.set(fn, (total.get(fn) ?? 0) + w);
      }
    }
    const out: FnStat[] = [];
    for (const [fn, t] of total) {
      if (hideLibs && this.fns[fn].cat !== Cat.User && !self.get(fn)) continue;
      out.push({ fn, self: self.get(fn) ?? 0, total: t });
    }
    out.sort((a, b) => b.self - a.self || b.total - a.total);
    return out;
  }

  /** per file → line → {self,total} weights (for editor heat) */
  lineHeat(counts: Map<number, number>): Map<string, Map<number, LineHeat>> {
    const out = new Map<string, Map<number, LineHeat>>();
    const seen = new Set<string>();
    for (const [sid, w] of counts) {
      const frames = this.path(sid);
      seen.clear();
      for (let i = 0; i < frames.length; i++) {
        const f = this.frames[frames[i]];
        if (!f.line || f.cat === Cat.Synth) continue;
        const k = f.file + ':' + f.line;
        let byLine = out.get(f.file);
        if (!byLine) out.set(f.file, (byLine = new Map<number, LineHeat>()));
        let rec = byLine.get(f.line);
        if (!rec) byLine.set(f.line, (rec = { self: 0, total: 0 }));
        if (!seen.has(k)) {
          rec.total += w;
          seen.add(k);
        }
        if (i === frames.length - 1) rec.self += w;
      }
    }
    return out;
  }

  /** samples per bucket, optionally split by status (for timelines) */
  histogram(
    buckets: number,
    t0: number,
    t1: number,
    opts: { source?: Source; tid?: number; mode?: Mode } = {},
  ): Float64Array {
    const table = opts.source === 'async' ? this.asyncSamples : this.samples;
    const out = new Float64Array(buckets);
    const span = Math.max(1e-6, t1 - t0);
    const start = table.lowerBound(t0);
    const end = table.lowerBound(t1);
    const mask = opts.mode === 'cpu' ? STATUS_ON_CPU : opts.mode === 'gil' ? STATUS_HAS_GIL : 0;
    for (let i = start; i < end; i++) {
      if (opts.tid !== undefined && table.tid[i] !== opts.tid) continue;
      if (mask && !(table.status[i] & mask)) continue;
      const b = Math.min(buckets - 1, Math.floor(((table.t[i] - t0) / span) * buckets));
      out[b]++;
    }
    return out;
  }

  threadList(): { tid: number; name: string; samples: number }[] {
    return [...this.threadSampleCounts]
      .map(([tid, samples]) => ({ tid, name: this.threadName(tid), samples }))
      .sort((a, b) => b.samples - a.samples);
  }

  snapshotCounts(id: number, weight: 'size' | 'count' = 'size'): Map<number, number> {
    const s = this.snapshots.find((x) => x.id === id);
    const m = new Map<number, number>();
    if (!s) return m;
    for (const [sid, size, count] of s.entries) {
      if (sid < 0) continue;
      m.set(sid, (m.get(sid) ?? 0) + (weight === 'size' ? size : count));
    }
    return m;
  }

  /** allocation diff between two snapshots, by stack */
  snapshotDiff(a: number, b: number): SnapshotDiffRow[] {
    const A = this.snapshots.find((x) => x.id === a);
    const B = this.snapshots.find((x) => x.id === b);
    if (!A || !B) return [];
    const bySid = (s: SnapshotRec) => new Map(s.entries.map(([sid, size, count]): [number, [number, number]] => [sid, [size, count]]));
    const ma = bySid(A);
    const mb = bySid(B);
    const rows: SnapshotDiffRow[] = [];
    for (const sid of new Set([...ma.keys(), ...mb.keys()])) {
      const [sa, ca] = ma.get(sid) ?? [0, 0];
      const [sb, cb] = mb.get(sid) ?? [0, 0];
      if (sa === sb && ca === cb) continue;
      rows.push({ sid, dSize: sb - sa, dCount: cb - ca, size: sb, count: cb });
    }
    rows.sort((x, y) => Math.abs(y.dSize) - Math.abs(x.dSize));
    return rows;
  }

  /** leaf-most user frame of a stack (for "where" columns) */
  userLeaf(sid: number): Frame | undefined {
    const p = this.path(sid);
    for (let i = p.length - 1; i >= 0; i--) {
      const f = this.frames[p[i]];
      if (f.cat === Cat.User) return f;
    }
    return p.length ? this.frames[p[p.length - 1]] : undefined;
  }

  trackRange(name: string, t0: number, t1: number): { t: number[]; v: number[] } {
    const tr = this.tracks.get(name);
    if (!tr) return { t: [], v: [] };
    let lo = 0;
    while (lo < tr.t.length && tr.t[lo] < t0) lo++;
    let hi = lo;
    while (hi < tr.t.length && tr.t[hi] <= t1) hi++;
    return { t: tr.t.slice(lo, hi), v: tr.v.slice(lo, hi) };
  }

  lastValue(name: string): number | undefined {
    const tr = this.tracks.get(name);
    return tr && tr.v.length ? tr.v[tr.v.length - 1] : undefined;
  }
}
