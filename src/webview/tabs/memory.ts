/** Memory tab: RSS / traced memory over time, snapshots, diffs, allocation flame graph, object counts, GC. */
import { button, h, segmented, tile } from '../dom';
import type { App, Tab } from '../app';
import { TimeSeriesChart } from '../components/timeseries';
import { chartColor } from '../components/colors';
import { FlameGraph } from '../components/flamegraph';
import { DataTable } from '../components/table';
import { fmtBytes, fmtCount, fmtMs, shortPath } from '../../shared/format';
import type { SnapshotRec } from '../../shared/model';

type DiffRow = { sid: number; dSize: number; dCount: number; size: number; count: number };
type SiteRow = { sid: number; size: number; count: number };

export class MemoryTab implements Tab {
  readonly el = h('div', { class: 'content' });
  private chart: TimeSeriesChart;
  private actions = h('div', { class: 'banner' });
  private tiles = h('div', { class: 'grid tiles' });
  private snapBar = h('div', { class: 'toolbar', style: 'padding:8px 0;border:none' });
  private detail = h('div', { class: 'grid two' });
  private flame: FlameGraph;
  private flameCard = h('div', { class: 'card', style: 'height:420px;display:flex;flex-direction:column;padding:0' });
  private sites: DataTable<SiteRow>;
  private diff: DataTable<DiffRow>;
  private objects: DataTable<{ name: string; count: number; delta: number }>;
  private gcTable: DataTable<{ gen: number; n: number; total: number; max: number; collected: number }>;
  private weight: 'size' | 'count' = 'size';
  private lastSnapCount = -1;

  constructor(private readonly app: App) {
    this.chart = new TimeSeriesChart({
      height: 170,
      yFormat: (v) => fmtBytes(v),
      onBrush: (a, b) => app.setRange(a, b),
      onClearBrush: () => app.clearRange(),
    });
    this.flame = new FlameGraph({ format: (w) => (this.weight === 'size' ? fmtBytes(w) : fmtCount(w)), onOpen: (f, l) => app.open(f, l) });
    const where = (sid: number) => {
      const f = app.model.userLeaf(sid);
      return f ? h('span', null, h('b', null, f.func), h('span', { class: 'muted' }, ` ${shortPath(f.file, 2)}:${f.line}`)) : '?';
    };
    const openSid = (sid: number) => {
      const f = app.model.userLeaf(sid);
      if (f) app.open(f.file, f.line);
    };
    this.sites = new DataTable<SiteRow>(
      [
        { label: 'Size', num: true, bar: true, value: (r) => r.size, render: (r) => fmtBytes(r.size) },
        { label: 'Blocks', num: true, value: (r) => r.count, render: (r) => fmtCount(r.count) },
        { label: 'Allocated at', cls: 'fn', value: (r) => app.model.userLeaf(r.sid)?.func ?? '', render: (r) => where(r.sid) },
      ],
      { onDblClick: (r) => openSid(r.sid), onClick: (r) => openSid(r.sid), empty: 'Take a snapshot to see allocation sites' },
    );
    this.diff = new DataTable<DiffRow>(
      [
        { label: 'Δ Size', num: true, bar: true, value: (r) => r.dSize, render: (r) => fmtBytes(r.dSize, true) },
        { label: 'Δ Blocks', num: true, value: (r) => r.dCount, render: (r) => (r.dCount > 0 ? '+' : '') + fmtCount(r.dCount) },
        { label: 'Now', num: true, value: (r) => r.size, render: (r) => fmtBytes(r.size) },
        { label: 'Allocated at', cls: 'fn', value: (r) => app.model.userLeaf(r.sid)?.func ?? '', render: (r) => where(r.sid) },
      ],
      { onClick: (r) => openSid(r.sid), empty: 'No differences between the two snapshots' },
    );
    this.objects = new DataTable(
      [
        { label: 'Objects', num: true, bar: true, value: (r) => r.count, render: (r) => fmtCount(r.count) },
        { label: 'Δ since previous', num: true, value: (r) => r.delta, render: (r) => (r.delta > 0 ? '+' : '') + fmtCount(r.delta) },
        { label: 'Type', value: (r) => r.name },
      ],
      { empty: 'Click "Count objects" to list live objects by type' },
    );
    this.gcTable = new DataTable(
      [
        { label: 'Gen', value: (r) => r.gen },
        { label: 'Collections', num: true, value: (r) => r.n },
        { label: 'Total pause', num: true, bar: true, value: (r) => r.total, render: (r) => fmtMs(r.total) },
        { label: 'Max pause', num: true, value: (r) => r.max, render: (r) => fmtMs(r.max) },
        { label: 'Collected', num: true, value: (r) => r.collected, render: (r) => fmtCount(r.collected) },
      ],
      { sortCol: 0, empty: 'No GC collections recorded' },
    );
    this.flameCard.append(h('h3', { style: 'padding:10px 12px 0' }, 'Allocation flame graph', h('span', { class: 'sub' }, 'live memory by call stack at the selected snapshot')), this.flame.el);
    this.el.append(
      this.actions,
      this.tiles,
      h('div', { class: 'card' }, h('h3', null, 'Memory over time', h('span', { class: 'sub' }, 'RSS (OS) · traced (tracemalloc) · GC ticks · snapshots')), this.chart.el),
      this.snapBar,
      this.detail,
      h(
        'div',
        { class: 'grid two', style: 'margin-top:12px' },
        h('div', { class: 'card' }, h('h3', null, 'Live objects by type', h('span', { class: 'actions' }, button('Count objects', () => app.command('objectCounts'), { title: 'Walks gc.get_objects() in the target (pauses it briefly)' }))), h('div', { style: 'max-height:320px;overflow:auto' }, this.objects.el)),
        h('div', { class: 'card' }, h('h3', null, 'Garbage collector'), this.gcTable.el),
      ),
    );
  }

  update(full: boolean): void {
    const app = this.app;
    const m = app.model;
    this.renderActions();
    // tiles
    const rss = m.tracks.get('rss');
    const traced = m.tracks.get('traced');
    const rssNow = rss?.v.at(-1);
    const rssPeak = rss ? Math.max(...rss.v) : undefined;
    const rssStart = rss?.v[0];
    const growth = rssNow !== undefined && rssStart ? rssNow - rssStart : undefined;
    const gcPause = m.gc.reduce((a, g) => a + g[1], 0);
    this.tiles.replaceChildren(
      tile('RSS now', fmtBytes(rssNow), rssPeak ? `peak ${fmtBytes(rssPeak)}` : ''),
      tile('Growth', growth !== undefined ? fmtBytes(growth, true) : '–', 'since start', growth !== undefined && rssStart && growth > rssStart * 0.5 ? 'warn' : ''),
      tile('Traced (tracemalloc)', traced ? fmtBytes(traced.v.at(-1)) : 'off', traced ? `peak ${fmtBytes(m.lastValue('tracedPeak'))}` : 'start memory tracing'),
      tile('GC pauses', fmtMs(gcPause), `${m.gc.length} collections`, gcPause > m.duration * 0.05 ? 'warn' : ''),
      tile('Snapshots', String(m.snapshots.length)),
    );
    // chart
    const domain = app.domain();
    const series = [];
    if (rss) series.push({ name: 'RSS', color: chartColor('blue'), t: rss.t, v: rss.v, area: true });
    if (traced) series.push({ name: 'traced', color: chartColor('orange'), t: traced.t, v: traced.v });
    const peak = m.tracks.get('tracedPeak');
    if (peak) series.push({ name: 'traced peak', color: chartColor('red'), t: peak.t, v: peak.v, dashed: true });
    this.chart.setData({
      domain,
      series,
      selection: app.range,
      markers: m.snapshots.map((s) => [s.t, s.label] as [number, string]),
      ticks: m.gc.map((g) => ({ t: g[0], color: chartColor('purple'), label: 'gc' })),
    });
    // gc table
    const byGen = new Map<number, { gen: number; n: number; total: number; max: number; collected: number }>();
    for (const [, dur, gen, collected] of m.gc) {
      let r = byGen.get(gen);
      if (!r) byGen.set(gen, (r = { gen, n: 0, total: 0, max: 0, collected: 0 }));
      r.n++;
      r.total += dur;
      r.max = Math.max(r.max, dur);
      r.collected += collected;
    }
    this.gcTable.setRows([...byGen.values()]);
    // objects
    const oc = m.objectCounts;
    if (oc.length) {
      const last = oc[oc.length - 1];
      const prev = oc.length > 1 ? new Map(oc[oc.length - 2].counts) : new Map<string, number>();
      this.objects.setRows(last.counts.map(([name, count]) => ({ name, count, delta: prev.size ? count - (prev.get(name) ?? 0) : 0 })));
    }
    // snapshots
    if (full || m.snapshots.length !== this.lastSnapCount) {
      if (m.snapshots.length && (app.memSnap === undefined || !m.snapshots.some((s) => s.id === app.memSnap))) {
        app.memSnap = m.snapshots[m.snapshots.length - 1].id;
        if (m.snapshots.length > 1 && app.memBase === undefined) app.memBase = m.snapshots[0].id;
      }
      this.lastSnapCount = m.snapshots.length;
      this.renderSnapshots();
    }
  }

  private renderActions(): void {
    const app = this.app;
    const { caps } = app;
    if (!caps.live) {
      this.actions.style.display = app.model.snapshots.length ? 'none' : 'flex';
      this.actions.replaceChildren(h('span', { class: 'muted' }, 'This profile has no memory snapshots. Live sessions can trace allocations with tracemalloc.'));
      return;
    }
    this.actions.style.display = 'flex';
    if (!caps.agent) {
      this.actions.className = 'banner warn';
      this.actions.replaceChildren(
        h('span', null, '⚠ The in-process agent is not connected, so only OS memory (RSS) and GC stats are available. ' +
          'Snapshots need the agent (start the program with the profiler, or attach with injection enabled).'),
      );
      return;
    }
    this.actions.className = 'banner';
    this.actions.replaceChildren(
      caps.tracemalloc
        ? button('Stop memory tracing', () => app.command('tracemalloc', { enabled: false }))
        : button('Start memory tracing', () => app.command('tracemalloc', { enabled: true }), { primary: true, title: 'tracemalloc adds CPU and memory overhead to the target' }),
      button('Take snapshot', () => app.command('snapshot'), { primary: caps.tracemalloc, icon: '📷' }),
      h('span', { class: 'muted' }, caps.tracemalloc
        ? 'Leak hunting: take a snapshot, let the program run, take another, then compare.'
        : 'Memory tracing is off. Start it, exercise your program, then take snapshots.'),
    );
  }

  private renderSnapshots(): void {
    const app = this.app;
    const snaps = app.model.snapshots;
    if (!snaps.length) {
      this.snapBar.replaceChildren();
      this.detail.replaceChildren();
      return;
    }
    const opt = (s: SnapshotRec) => h('option', { value: String(s.id) }, `${s.label} · ${fmtMs(s.t)} · ${fmtBytes(s.totalSize)}`);
    const snapSel = h('select', null, snaps.map(opt));
    snapSel.value = String(app.memSnap);
    snapSel.addEventListener('change', () => {
      app.memSnap = Number(snapSel.value);
      this.renderSnapshots();
    });
    const baseSel = h('select', null, h('option', { value: '' }, '— none —'), snaps.map(opt));
    baseSel.value = app.memBase !== undefined ? String(app.memBase) : '';
    baseSel.addEventListener('change', () => {
      app.memBase = baseSel.value ? Number(baseSel.value) : undefined;
      this.renderSnapshots();
    });
    this.snapBar.replaceChildren(
      h('div', { class: 'group' }, h('span', { class: 'label' }, 'Snapshot'), snapSel),
      h('div', { class: 'group' }, h('span', { class: 'label' }, 'compare with'), baseSel),
      segmented([{ value: 'size', label: 'Bytes' }, { value: 'count', label: 'Blocks' }], this.weight, (v) => {
        this.weight = v as 'size' | 'count';
        this.renderSnapshots();
      }),
    );
    const snap = snaps.find((s) => s.id === app.memSnap)!;
    const base = app.memBase !== undefined && app.memBase !== app.memSnap ? snaps.find((s) => s.id === app.memBase) : undefined;

    if (base) {
      const rows = app.model.snapshotDiff(base.id, snap.id);
      const grow = new Map<number, number>();
      for (const r of rows) {
        const w = this.weight === 'size' ? r.dSize : r.dCount;
        if (w > 0) grow.set(r.sid, w);
      }
      this.flame.setData(app.model, app.model.buildTree(grow));
      const totalDiff = snap.totalSize - base.totalSize;
      this.detail.replaceChildren(
        h(
          'div',
          { class: 'card', style: 'max-height:420px;display:flex;flex-direction:column' },
          h('h3', null, `Growth ${base.label} → ${snap.label}`, h('span', { class: 'sub' }, `${fmtBytes(totalDiff, true)} in ${fmtMs(snap.t - base.t)}`)),
          this.diff.el,
        ),
        this.flameCard,
      );
      this.diff.setRows(rows);
      (this.flameCard.querySelector('h3 .sub') as HTMLElement).textContent = 'only allocations that grew between the snapshots';
    } else {
      const counts = app.model.snapshotCounts(snap.id, this.weight);
      this.flame.setData(app.model, app.model.buildTree(counts));
      this.sites.setRows(snap.entries.map(([sid, size, count]) => ({ sid, size, count })));
      this.detail.replaceChildren(
        h(
          'div',
          { class: 'card', style: 'max-height:420px;display:flex;flex-direction:column' },
          h('h3', null, `Top allocation sites · ${snap.label}`, h('span', { class: 'sub' }, `${fmtBytes(snap.totalSize)} in ${fmtCount(snap.totalCount)} blocks`)),
          this.sites.el,
        ),
        this.flameCard,
      );
      (this.flameCard.querySelector('h3 .sub') as HTMLElement).textContent = 'live memory by call stack at the selected snapshot';
    }
  }
}
