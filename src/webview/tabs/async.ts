/** Async tab: event-loop lag, task timeline, task stats, asyncio debug events. */
import { button, h, tile } from '../dom';
import type { App, Tab } from '../app';
import { TimeSeriesChart } from '../components/timeseries';
import { chartColor } from '../components/colors';
import { TaskGantt } from '../components/timeline';
import { DataTable } from '../components/table';
import { fmtCount, fmtMs, maxOf, percentile } from '../../shared/format';
import type { EventRec, TaskRec } from '../../shared/model';

const EVENT_KINDS = new Set(['slow-callback', 'never-awaited', 'task-destroyed-pending', 'exception-never-retrieved', 'asyncio']);

export class AsyncTab implements Tab {
  readonly el = h('div', { class: 'content' });
  private banner = h('div', { class: 'banner' });
  private tiles = h('div', { class: 'grid tiles' });
  private lag: TimeSeriesChart;
  private gantt: TaskGantt;
  private events: DataTable<EventRec>;
  private tasks: DataTable<TaskRec & { life: number }>;

  constructor(private readonly app: App) {
    this.lag = new TimeSeriesChart({
      height: 130,
      yFormat: (v) => fmtMs(v),
      onBrush: (a, b) => app.setRange(a, b),
      onClearBrush: () => app.clearRange(),
    });
    this.gantt = new TaskGantt((a, b) => app.setRange(a, b), () => app.clearRange());
    const openFromMessage = (e: EventRec) => {
      if (typeof e.file === 'string') return app.open(e.file, Number(e.line ?? 1));
      const m = detail(e).match(/at (.+?):(\d+)/);
      if (m) app.open(m[1], Number(m[2]));
    };
    this.events = new DataTable<EventRec>(
      [
        { label: 'Time', num: true, value: (e) => e.t, render: (e) => fmtMs(e.t) },
        { label: 'Kind', value: (e) => e.kind, render: (e) => h('span', { class: `kind ${e.kind}` }, e.kind) },
        { label: 'Blocked', num: true, value: (e) => Number(e.seconds ?? 0), render: (e) => (e.seconds ? fmtMs(Number(e.seconds) * 1000) : '') },
        { label: 'Details', cls: 'msg', value: (e) => e.message, render: (e) => h('span', { class: 'mono' }, detail(e).slice(0, 400)) },
      ],
      { onDblClick: openFromMessage, onClick: openFromMessage, empty: 'No asyncio debug events. Enable asyncio debug mode to detect slow callbacks and never-awaited coroutines.' },
    );
    this.tasks = new DataTable<TaskRec & { life: number }>(
      [
        { label: 'Lifetime', num: true, bar: true, value: (t) => t.life, render: (t) => fmtMs(t.life) },
        { label: 'Task', value: (t) => t.name },
        { label: 'State', value: (t) => t.state },
        {
          label: 'Awaiting in',
          cls: 'fn',
          value: (t) => (t.stack >= 0 ? app.model.userLeaf(t.stack)?.func ?? '' : ''),
          render: (t) => {
            const f = t.stack >= 0 ? app.model.userLeaf(t.stack) : undefined;
            return f ? h('a', { class: 'link', onclick: () => app.open(f.file, f.line) }, `${f.func}:${f.line}`) : '';
          },
        },
      ],
      { empty: 'No asyncio tasks seen yet', limit: 300 },
    );
    this.el.append(
      this.banner,
      this.tiles,
      h('div', { class: 'card' }, h('h3', null, 'Event loop lag', h('span', { class: 'sub' }, 'how long a callback had to wait to run — spikes mean something blocked the loop')), this.lag.el),
      h('div', { class: 'card', style: 'margin-top:12px' }, h('h3', null, 'Task timeline', h('span', { class: 'sub' }, h('span', { style: `color:${chartColor('green')}` }, '■ running '), h('span', { style: `color:${chartColor('yellow')}` }, '■ awaiting'))), h('div', { style: 'max-height:420px;overflow:auto' }, this.gantt.el)),
      h(
        'div',
        { class: 'grid two', style: 'margin-top:12px' },
        h('div', { class: 'card', style: 'max-height:380px;display:flex;flex-direction:column' }, h('h3', null, 'asyncio debug events'), this.events.el),
        h('div', { class: 'card', style: 'max-height:380px;display:flex;flex-direction:column' }, h('h3', null, 'Tasks', h('span', { class: 'actions' }, button('Async-aware flame graph', () => { app.source = 'async'; app.tab = 'cpu'; app.changed(true); }))), this.tasks.el),
      ),
    );
  }

  update(): void {
    const app = this.app;
    const m = app.model;
    // banner
    if (app.caps.live && app.caps.agent) {
      this.banner.style.display = 'flex';
      this.banner.replaceChildren(
        app.caps.asyncioDebug
          ? button('Disable asyncio debug', () => app.command('asyncioDebug', { enabled: false }))
          : button('Enable asyncio debug', () => app.command('asyncioDebug', { enabled: true }), { primary: true }),
        h('span', { class: 'muted' }, app.caps.asyncioDebug
          ? 'Debug mode is on: slow callbacks, never-awaited coroutines and destroyed pending tasks are reported below.'
          : 'Turn on asyncio debug mode to catch slow callbacks and coroutines that were never awaited (small overhead).'),
      );
    } else if (app.caps.live) {
      this.banner.style.display = 'flex';
      this.banner.replaceChildren(h('span', { class: 'muted' }, 'Task graphs are read from outside the process. Loop lag and asyncio debug need the in-process agent.'));
    } else {
      this.banner.style.display = 'none';
    }
    const domain = app.domain();
    const lag = m.tracks.get('loopLag');
    const tasksAll = [...m.tasks.values()];
    const live = tasksAll.filter((t) => t.end === null);
    const events = m.events.filter((e) => EVENT_KINDS.has(e.kind));
    const slow = events.filter((e) => e.kind === 'slow-callback');
    const maxLag = lag ? maxOf(lag.v) : undefined;
    const p99 = lag ? percentile(lag.v, 0.99) : undefined;
    this.tiles.replaceChildren(
      tile('Tasks alive', fmtCount(live.length), `${fmtCount(tasksAll.length)} seen`),
      tile('Loop lag p99', fmtMs(p99), maxLag !== undefined ? `max ${fmtMs(maxLag)}` : 'needs agent', p99 !== undefined && p99 > 100 ? 'bad' : p99 !== undefined && p99 > 20 ? 'warn' : ''),
      tile('Slow callbacks', String(slow.length), app.caps.asyncioDebug ? '' : 'debug mode off', slow.length ? 'warn' : ''),
      tile('Never awaited', String(events.filter((e) => e.kind === 'never-awaited').length), '', events.some((e) => e.kind === 'never-awaited') ? 'bad' : ''),
    );
    const series = [];
    if (lag) series.push({ name: 'loop lag', color: chartColor('red'), t: lag.t, v: lag.v, area: true });
    this.lag.setData({ domain, series, selection: app.range, markers: m.markers });
    this.gantt.setData(m, app.range ?? domain);
    this.events.setRows(events);
    this.tasks.setRows(tasksAll.map((t) => ({ ...t, life: (t.end ?? m.now) - t.start })));
  }
}

/** The most specific text of a debug event: the offending handle if asyncio reported one. */
function detail(event: EventRec): string {
  return typeof event.handle === 'string' ? event.handle : event.message;
}
