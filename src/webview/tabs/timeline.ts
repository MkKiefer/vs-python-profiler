/** Timeline: every track on one time axis for deep troubleshooting. */
import { h } from '../dom';
import type { App, Tab } from '../app';
import { ThreadLanes } from '../components/timeline';
import { TimeSeriesChart } from '../components/timeseries';
import { chartColor } from '../components/colors';
import { fmtBytes, fmtMs } from '../../shared/format';

export class TimelineTab implements Tab {
  readonly el = h('div', { class: 'content' });
  private lanes: ThreadLanes;
  private cpu: TimeSeriesChart;
  private mem: TimeSeriesChart;
  private lag: TimeSeriesChart;
  private samples: TimeSeriesChart;

  constructor(private readonly app: App) {
    const brush = { onBrush: (a: number, b: number) => app.setRange(a, b), onClearBrush: () => app.clearRange() };
    this.lanes = new ThreadLanes(brush.onBrush, brush.onClearBrush);
    this.cpu = new TimeSeriesChart({ height: 90, yFormat: (v) => `${v.toFixed(0)}%`, ...brush });
    this.mem = new TimeSeriesChart({ height: 90, yFormat: (v) => fmtBytes(v), ...brush });
    this.lag = new TimeSeriesChart({ height: 90, yFormat: (v) => fmtMs(v), ...brush });
    this.samples = new TimeSeriesChart({ height: 90, bars: true, yFormat: (v) => v.toFixed(0), ...brush });
    this.el.append(
      h('div', { class: 'banner' }, h('span', { class: 'muted' }, 'Drag on any track to zoom every tab (and the editor heat map) to that time range. Double-click to reset. Orange = on CPU, red underline = waiting for the GIL, purple = GC.')),
      h('div', { class: 'card' }, h('h3', null, 'Threads'), this.lanes.el),
      h('div', { class: 'card', style: 'margin-top:12px' }, h('h3', null, 'Samples per bucket', h('span', { class: 'sub' }, 'activity in the current mode')), this.samples.el),
      h('div', { class: 'card', style: 'margin-top:12px' }, h('h3', null, 'CPU'), this.cpu.el),
      h('div', { class: 'card', style: 'margin-top:12px' }, h('h3', null, 'Memory'), this.mem.el),
      h('div', { class: 'card', style: 'margin-top:12px' }, h('h3', null, 'Event loop lag'), this.lag.el),
    );
  }

  update(): void {
    const app = this.app;
    const m = app.model;
    const domain: [number, number] = app.range ?? app.domain();
    this.lanes.setData(m, domain);
    const buckets = 120;
    const hist = m.histogram(buckets, domain[0], domain[1], { mode: app.mode, source: app.source });
    const step = (domain[1] - domain[0]) / buckets;
    this.samples.setData({
      domain,
      series: [{ name: `${app.mode} samples`, color: chartColor('orange'), t: Array.from(hist, (_, i) => domain[0] + (i + 0.5) * step), v: Array.from(hist) }],
      markers: m.markers,
    });
    const cpu = m.trackRange('cpu', domain[0], domain[1]);
    this.cpu.setData({ domain, series: [{ name: 'CPU %', color: chartColor('orange'), ...cpu, area: true }], markers: m.markers });
    const rss = m.trackRange('rss', domain[0], domain[1]);
    const traced = m.trackRange('traced', domain[0], domain[1]);
    this.mem.setData({
      domain,
      series: [{ name: 'RSS', color: chartColor('blue'), ...rss, area: true }, ...(traced.t.length ? [{ name: 'traced', color: chartColor('orange'), ...traced }] : [])],
      markers: m.markers,
      ticks: m.gc.map((g) => ({ t: g[0], color: chartColor('purple'), label: 'gc' })),
    });
    const lag = m.trackRange('loopLag', domain[0], domain[1]);
    this.lag.setData({ domain, series: [{ name: 'loop lag', color: chartColor('red'), ...lag, area: true }], markers: m.markers });
  }
}
