/** CPU tab: flame graph, call tree, inverted tree, top functions, callers/callees focus. */
import { h, segmented, checkbox } from '../dom';
import type { App, CpuView, Tab } from '../app';
import { FlameGraph } from '../components/flamegraph';
import { CallTreeView, DataTable } from '../components/table';
import { frameColor } from '../components/colors';
import { Cat, type FnStat } from '../../shared/model';
import { fmtPct, shortPath } from '../../shared/format';

export class CpuTab implements Tab {
  readonly el = h('div', { class: 'content flush' });
  private toolbar = h('div', { class: 'toolbar' });
  private body = h('div', { style: 'flex:1;display:flex;flex-direction:column;min-height:0' });
  private flame: FlameGraph;
  private tree: CallTreeView;
  private top: DataTable<FnStat & { all: number }>;
  private callers: CallTreeView;
  private callees: FlameGraph;
  private lastStructure = '';
  private total = 0;

  constructor(private readonly app: App) {
    const open = (f: string, l: number) => app.open(f, l);
    const focus = (fn: number) => app.focus(fn);
    this.flame = new FlameGraph({ format: app.fmtSamples, onOpen: open, onFocus: focus });
    this.tree = new CallTreeView({ format: app.fmtSamples, onOpen: open, onFocus: focus });
    this.callers = new CallTreeView({ format: app.fmtSamples, onOpen: open, onFocus: focus });
    this.callees = new FlameGraph({ format: app.fmtSamples, onOpen: open, onFocus: focus });
    this.top = new DataTable<FnStat & { all: number }>(
      [
        { label: 'Self', num: true, bar: true, value: (r) => r.self, render: (r) => fmtPct(r.self, r.all) },
        { label: 'Total', num: true, value: (r) => r.total, render: (r) => fmtPct(r.total, r.all) },
        { label: 'Self time', num: true, value: (r) => r.self, render: (r) => app.fmtSamples(r.self) },
        { label: 'Total time', num: true, value: (r) => r.total, render: (r) => app.fmtSamples(r.total) },
        {
          label: 'Function',
          cls: 'fn',
          value: (r) => app.model.fns[r.fn].func,
          render: (r) => {
            const f = app.model.fns[r.fn];
            const dot = h('span', { class: 'cat-dot' });
            dot.style.background = frameColor(f.cat, f.func);
            return h('span', null, dot, f.func);
          },
        },
        { label: 'Location', cls: 'loc', value: (r) => app.model.fns[r.fn].file, render: (r) => `‎${shortPath(app.model.fns[r.fn].file, 3)}:${app.model.fns[r.fn].minLine}` },
      ],
      {
        onClick: (r) => app.focus(r.fn),
        onDblClick: (r) => {
          const f = app.model.fns[r.fn];
          app.open(f.file, f.minLine);
        },
        empty: 'No samples in this selection',
      },
    );
    this.el.append(this.toolbar, this.body);
  }

  private renderToolbar(): void {
    const app = this.app;
    const threads = app.model.threadList();
    const threadMenu = h(
      'div',
      { class: 'menu' },
      threads.map((t) =>
        checkbox(`${t.name} (${t.samples})`, app.threads.has(t.tid), (v) => {
          if (v) app.threads.add(t.tid);
          else app.threads.delete(t.tid);
          app.changed(true);
        }),
      ),
    );
    const threadLabel = app.threads.size ? `${app.threads.size} thread${app.threads.size > 1 ? 's' : ''}` : 'All threads';
    const search = h('input', { type: 'search', placeholder: 'Search functions / files', value: app.search, style: 'width:200px' });
    search.addEventListener('input', () => {
      app.search = search.value;
      this.flame.setSearch(app.search);
      this.callees.setSearch(app.search);
    });
    this.toolbar.replaceChildren(
      segmented<CpuView>(
        [
          { value: 'flame', label: 'Flame graph' },
          { value: 'tree', label: 'Call tree' },
          { value: 'inverted', label: 'Bottom-up', title: 'Inverted tree: where time is spent, then who called it' },
          { value: 'top', label: 'Top functions' },
        ],
        app.cpuView,
        (v) => {
          app.cpuView = v;
          app.focusFn = undefined;
          app.changed(true);
        },
      ),
      h(
        'div',
        { class: 'group' },
        h('span', { class: 'label' }, 'Mode'),
        segmented(
          [
            { value: 'wall', label: 'Wall', title: 'All samples, including waiting/sleeping (latency)' },
            { value: 'cpu', label: 'CPU', title: 'Only samples where the thread was running on a CPU' },
            { value: 'gil', label: 'GIL', title: 'Only samples where the thread held the GIL' },
          ],
          app.mode,
          (v) => {
            app.mode = v;
            app.changed(true);
          },
        ),
      ),
      h(
        'div',
        { class: 'group' },
        h('span', { class: 'label' }, 'Group by'),
        segmented(
          [
            { value: 'threads', label: 'Threads' },
            { value: 'async', label: 'Async tasks', title: 'Async-aware stacks: coroutine chains per asyncio task' },
          ],
          app.source,
          (v) => {
            app.source = v;
            app.changed(true);
          },
        ),
      ),
      h('details', { class: 'dropdown' }, h('summary', { class: 'btn' }, `${threadLabel} ▾`), threadMenu),
      checkbox('Hide libraries', app.hideLibs, (v) => {
        app.hideLibs = v;
        app.changed(true);
      }, 'Collapse stdlib and site-packages frames into the call that entered them'),
      checkbox('By line', app.byLine, (v) => {
        app.byLine = v;
        app.changed(true);
      }, 'Split functions by line number'),
      search,
    );
  }

  update(full: boolean): void {
    const app = this.app;
    const structure = JSON.stringify([app.cpuView, app.mode, app.source, [...app.threads], app.hideLibs, app.byLine, app.focusFn, app.range]);
    const structural = full || structure !== this.lastStructure;
    if (structural) this.renderToolbar();
    const counts = app.model.countStacks(app.filter());
    this.total = app.model.totalWeight(counts);
    const opts = { hideLibs: app.hideLibs, byLine: app.byLine };

    if (app.focusFn !== undefined && app.model.fns[app.focusFn]) {
      if (structural) this.mountFocus();
      this.callers.setData(app.model, app.model.buildTree(counts, { ...opts, focusFn: app.focusFn, focus: 'callers' }), structural);
      this.callees.setData(app.model, app.model.buildTree(counts, { ...opts, focusFn: app.focusFn, focus: 'callees' }));
    } else if (app.cpuView === 'flame') {
      if (structural) {
        this.body.replaceChildren(this.legend(), this.flame.el);
        if (structure !== this.lastStructure) this.flame.resetZoom();
      }
      this.flame.setData(app.model, app.model.buildTree(counts, opts));
      this.flame.setSearch(app.search);
    } else if (app.cpuView === 'tree' || app.cpuView === 'inverted') {
      if (structural) this.body.replaceChildren(this.tree.el);
      this.tree.setData(app.model, app.model.buildTree(counts, { ...opts, inverted: app.cpuView === 'inverted' }), structural);
    } else {
      if (structural) this.body.replaceChildren(this.top.el);
      const all = this.total;
      this.top.setRows(app.model.topFunctions(counts, app.hideLibs).slice(0, 1000).map((r) => ({ ...r, all })));
    }
    this.lastStructure = structure;
  }

  private mountFocus(): void {
    const app = this.app;
    const f = app.model.fns[app.focusFn!];
    const banner = h(
      'div',
      { class: 'crumbs' },
      h('span', { class: 'cat-dot', style: `background:${frameColor(f.cat, f.func)}` }),
      h('b', null, f.func),
      h('span', { class: 'muted' }, `${shortPath(f.file, 3)}:${f.minLine}`),
      h('a', { onclick: () => app.open(f.file, f.minLine) }, 'open source'),
      h('span', { class: 'spacer' }),
      h('a', { onclick: () => { app.focusFn = undefined; app.changed(true); } }, '✕ clear focus'),
    );
    this.body.replaceChildren(
      banner,
      h(
        'div',
        { class: 'split' },
        h('div', null, h('h4', null, 'Callers (who calls it)'), this.callers.el),
        h('div', null, h('h4', null, 'Callees (what it spends time in)'), this.callees.el),
      ),
    );
  }

  private legend(): HTMLElement {
    const item = (cat: Cat, label: string) => {
      const i = h('span', { class: 'cat-dot' });
      i.style.background = frameColor(cat, label);
      return h('span', null, i, label);
    };
    return h(
      'div',
      { class: 'legend', style: 'padding:4px 14px;margin:0;border-bottom:1px solid var(--border)' },
      item(Cat.User, 'your code'),
      item(Cat.Lib, 'libraries'),
      item(Cat.Std, 'stdlib'),
      item(Cat.Synth, 'native / GC / task'),
      h('span', { class: 'spacer' }),
      h('span', null, `${this.total.toLocaleString()} samples ≈ ${this.app.fmtSamples(this.total)} of thread time`),
    );
  }

  reveal(fn: number): void {
    this.app.focus(fn);
  }
}
