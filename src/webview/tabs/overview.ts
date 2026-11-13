/** Overview: the 10-second answer + automatic insights that link into the detail tabs. */
import { h, tile } from '../dom';
import type { App, Tab } from '../app';
import { TimeSeriesChart } from '../components/timeseries';
import { chartColor, frameColor } from '../components/colors';
import { Cat, STATUS_GIL_REQUESTED, STATUS_HAS_GIL } from '../../shared/model';
import { fmtBytes, fmtCount, fmtMs, fmtPct, maxOf, mean, shortPath } from '../../shared/format';

interface Insight {
  sev: 'bad' | 'warn' | 'info';
  text: string;
  action?: [string, () => void];
}

export class OverviewTab implements Tab {
  readonly el = h('div', { class: 'content' });
  private tiles = h('div', { class: 'grid tiles' });
  private cpu: TimeSeriesChart;
  private mem: TimeSeriesChart;
  private lag: TimeSeriesChart;
  private lagCard: HTMLElement;
  private insights = h('ul', { class: 'insights' });
  private hot = h('div');
  private alloc = h('div');
  private tasks = h('div');

  constructor(private readonly app: App) {
    const brush = { onBrush: (a: number, b: number) => app.setRange(a, b), onClearBrush: () => app.clearRange() };
    this.cpu = new TimeSeriesChart({ height: 110, yFormat: (v) => `${v.toFixed(0)}%`, ...brush });
    this.mem = new TimeSeriesChart({ height: 110, yFormat: (v) => fmtBytes(v), ...brush });
    this.lag = new TimeSeriesChart({ height: 110, yFormat: (v) => fmtMs(v), ...brush });
    this.lagCard = h('div', { class: 'card' }, h('h3', null, 'Event loop lag'), this.lag.el);
    this.el.append(
      this.tiles,
      h(
        'div',
        { class: 'grid three' },
        h('div', { class: 'card' }, h('h3', null, 'CPU', h('span', { class: 'sub' }, 'process, 100% = one core')), this.cpu.el),
        h('div', { class: 'card' }, h('h3', null, 'Memory', h('span', { class: 'sub' }, 'RSS · traced')), this.mem.el),
        this.lagCard,
      ),
      h('div', { class: 'section-title' }, 'Insights'),
      this.insights,
      h(
        'div',
        { class: 'grid three', style: 'margin-top:12px' },
        h('div', { class: 'card' }, h('h3', null, 'Hottest functions', h('span', { class: 'sub' }, 'self CPU time')), this.hot),
        h('div', { class: 'card' }, h('h3', null, 'Top allocators', h('span', { class: 'sub' }, 'latest snapshot')), this.alloc),
        h('div', { class: 'card' }, h('h3', null, 'Longest-running tasks'), this.tasks),
      ),
    );
  }

  update(): void {
    const app = this.app;
    const m = app.model;
    const domain = app.domain();
    // "hot" means CPU: wall-clock samples would blame callers of sleep()/IO for idle time
    const counts = m.countStacks({ ...app.filter(), source: 'threads', mode: 'cpu' });
    const total = m.totalWeight(counts);

    // tiles
    const cpu = m.tracks.get('cpu');
    const avgCpu = cpu ? mean(cpu.v) : undefined;
    const peakCpu = cpu ? maxOf(cpu.v) : undefined;
    const rss = m.tracks.get('rss');
    const lag = m.tracks.get('loopLag');
    const maxLag = lag ? maxOf(lag.v) : undefined;
    const gcPause = m.gc.reduce((a, g) => a + g[1], 0);
    this.tiles.replaceChildren(
      tile('Duration', fmtMs(m.duration), app.caps.live ? 'live' : ''),
      tile('Samples', fmtCount(m.stats.samples), `${m.stats.rateHz ? m.stats.rateHz.toFixed(0) + ' Hz' : ''}${m.stats.errors ? ` · ${fmtPct(m.stats.errors, m.stats.samples + m.stats.errors, 0)} discarded` : ''}`),
      tile('CPU avg', avgCpu !== undefined ? `${avgCpu.toFixed(0)}%` : '–', peakCpu !== undefined ? `peak ${peakCpu.toFixed(0)}%` : ''),
      tile('Peak RSS', fmtBytes(rss ? maxOf(rss.v) : undefined), rss?.v.length ? `now ${fmtBytes(rss.v.at(-1))}` : ''),
      tile('Max loop lag', fmtMs(maxLag), lag ? '' : 'no asyncio loop seen', maxLag !== undefined && maxLag > 100 ? 'bad' : ''),
      tile('GC pauses', fmtMs(gcPause), `${m.gc.length} collections`),
      tile('Threads', String(m.threadList().length)),
    );

    // charts
    this.cpu.setData({ domain, series: cpu ? [{ name: 'CPU %', color: chartColor('orange'), t: cpu.t, v: cpu.v, area: true }] : [], selection: app.range, markers: m.markers });
    const memSeries = [];
    if (rss) memSeries.push({ name: 'RSS', color: chartColor('blue'), t: rss.t, v: rss.v, area: true });
    const traced = m.tracks.get('traced');
    if (traced) memSeries.push({ name: 'traced', color: chartColor('orange'), t: traced.t, v: traced.v });
    this.mem.setData({ domain, series: memSeries, selection: app.range, markers: m.markers });
    this.lagCard.style.display = lag || m.tasks.size ? '' : 'none';
    this.lag.setData({ domain, series: lag ? [{ name: 'lag', color: chartColor('red'), t: lag.t, v: lag.v, area: true }] : [], selection: app.range });

    // hottest functions
    const top = m.topFunctions(counts).filter((f) => m.fns[f.fn].cat !== Cat.Synth).slice(0, 6);
    this.hot.replaceChildren(
      top.length
        ? h(
            'table',
            { class: 'data' },
            h('tbody', null, top.map((f) => {
              const fn = m.fns[f.fn];
              const dot = h('span', { class: 'cat-dot' });
              dot.style.background = frameColor(fn.cat, fn.func);
              return h(
                'tr',
                { style: 'cursor:pointer', onclick: () => app.focus(f.fn), title: `${fn.file}:${fn.minLine}` },
                h('td', { class: 'num' }, fmtPct(f.self, total)),
                h('td', { class: 'fn' }, dot, fn.func),
                h('td', { class: 'loc' }, `‎${shortPath(fn.file, 1)}`),
              );
            })),
          )
        : h('div', { class: 'empty' }, app.caps.live ? 'Collecting samples…' : 'No samples'),
    );

    // allocators
    const snap = m.snapshots.at(-1);
    if (snap) {
      const rows = [...snap.entries].sort((a, b) => b[1] - a[1]).slice(0, 6);
      this.alloc.replaceChildren(
        h('table', { class: 'data' }, h('tbody', null, rows.map(([sid, size]) => {
          const f = m.userLeaf(sid);
          return h('tr', { style: 'cursor:pointer', onclick: () => { app.tab = 'memory'; app.changed(true); } },
            h('td', { class: 'num' }, fmtBytes(size)),
            h('td', { class: 'fn' }, f?.func ?? '?'),
            h('td', { class: 'loc' }, f ? `‎${shortPath(f.file, 1)}:${f.line}` : ''));
        }))),
      );
    } else {
      this.alloc.replaceChildren(h('div', { class: 'empty' }, app.caps.agent ? 'Take a memory snapshot in the Memory tab' : 'No snapshots'));
    }

    // tasks
    const tasks = [...m.tasks.values()].map((t) => ({ t, life: (t.end ?? m.now) - t.start })).sort((a, b) => b.life - a.life).slice(0, 6);
    this.tasks.replaceChildren(
      tasks.length
        ? h('table', { class: 'data' }, h('tbody', null, tasks.map(({ t, life }) =>
            h('tr', { style: 'cursor:pointer', onclick: () => { app.tab = 'async'; app.changed(true); } },
              h('td', { class: 'num' }, fmtMs(life)), h('td', { class: 'fn' }, t.name), h('td', { class: 'loc' }, t.state)))))
        : h('div', { class: 'empty' }, 'No asyncio tasks'),
    );

    // insights
    const ins = this.computeInsights(total, counts);
    this.insights.replaceChildren(
      ...(ins.length
        ? ins.map((i) =>
            h('li', null, h('span', { class: `sev ${i.sev}` }, i.sev === 'bad' ? '●' : i.sev === 'warn' ? '▲' : 'ℹ'), h('span', null, i.text, ' ', i.action ? h('a', { onclick: i.action[1] }, i.action[0]) : null)),
          )
        : [h('li', null, h('span', { class: 'sev info' }, 'ℹ'), app.caps.live ? 'Collecting data… insights appear as patterns emerge.' : 'Nothing unusual detected.')]),
    );
  }

  private computeInsights(total: number, counts: Map<number, number>): Insight[] {
    const app = this.app;
    const m = app.model;
    const out: Insight[] = [];
    const goto = (tab: typeof app.tab) => () => {
      app.tab = tab;
      app.changed(true);
    };

    // hot function
    const top = m.topFunctions(counts).find((f) => m.fns[f.fn].cat === Cat.User);
    if (top && total > 200 && top.self / total > 0.25) {
      out.push({ sev: 'warn', text: `${m.fns[top.fn].func} uses ${fmtPct(top.self, total)} of CPU time in its own code (not in functions it calls).`, action: ['Show callers & callees', () => app.focus(top.fn)] });
    }
    // GIL contention
    let waiting = 0;
    let all = 0;
    const s = m.samples;
    for (let i = 0; i < s.length; i++) {
      const st = s.status[i];
      all++;
      if (st & STATUS_GIL_REQUESTED && !(st & STATUS_HAS_GIL)) waiting++;
    }
    // needs ≥2 sampled threads: with one thread, GIL waits are our own agent (snapshots)
    if (m.threadList().length >= 2 && all > 500 && waiting / all > 0.15) {
      out.push({ sev: 'warn', text: `Threads were waiting for the GIL in ${fmtPct(waiting, all)} of samples — CPU-bound threads contend for the interpreter.`, action: ['Open timeline', goto('timeline')] });
    }
    // memory growth
    const rss = m.tracks.get('rss');
    if (rss && rss.v.length >= 8) {
      const n = rss.v.length;
      const first = mean(rss.v.slice(0, Math.max(3, n / 10))) ?? 0;
      const last = mean(rss.v.slice(-Math.max(3, n / 10))) ?? 0;
      const rising = monotonicShare(rss.v);
      if (last > first * 1.3 && last - first > 20 * 1024 * 1024 && rising > 0.6) {
        out.push({
          sev: 'bad',
          text: `Memory grew steadily from ${fmtBytes(first)} to ${fmtBytes(last)}. This looks like a leak.`,
          action: [m.snapshots.length >= 2 ? 'Compare snapshots' : 'Hunt it with snapshots', goto('memory')],
        });
      }
    }
    // loop lag
    const lag = m.tracks.get('loopLag');
    if (lag && lag.v.length) {
      const blocked = lag.v.filter((v) => v > 100).length;
      if (blocked) {
        out.push({ sev: 'bad', text: `The event loop was blocked for more than 100 ms ${blocked} time${blocked > 1 ? 's' : ''} (max ${fmtMs(maxOf(lag.v))}). Something synchronous runs inside a coroutine.`, action: ['Investigate', goto('async')] });
      }
    }
    const never = m.events.filter((e) => e.kind === 'never-awaited').length;
    if (never) out.push({ sev: 'bad', text: `${never} coroutine${never > 1 ? 's were' : ' was'} never awaited.`, action: ['Show', goto('async')] });
    const slow = m.events.filter((e) => e.kind === 'slow-callback').length;
    if (slow) out.push({ sev: 'warn', text: `${slow} slow asyncio callback${slow > 1 ? 's' : ''} detected.`, action: ['Show', goto('async')] });
    // GC
    const gcPause = m.gc.reduce((a, g) => a + g[1], 0);
    if (m.duration > 2000 && gcPause / m.duration > 0.05) {
      out.push({ sev: 'warn', text: `Garbage collection paused the program for ${fmtMs(gcPause)} (${fmtPct(gcPause, m.duration)} of the run).`, action: ['GC details', goto('memory')] });
    }
    // sampling errors
    if (m.stats.samples > 100 && m.stats.errors / m.stats.samples > 0.2) {
      out.push({ sev: 'warn', text: `${fmtPct(m.stats.errors, m.stats.samples)} of samples were discarded because stacks changed while being read. Enable "pyprof.blockingSampling" for consistent samples.` });
    }
    if (app.caps.live && !app.caps.agent && app.state === 'running') {
      out.push({ sev: 'info', text: 'Running without the in-process agent: CPU, tasks and GC work; memory snapshots and loop lag are unavailable.' });
    }
    return out;
  }
}

function monotonicShare(v: number[]): number {
  let up = 0;
  for (let i = 1; i < v.length; i++) if (v[i] >= v[i - 1]) up++;
  return up / Math.max(1, v.length - 1);
}
