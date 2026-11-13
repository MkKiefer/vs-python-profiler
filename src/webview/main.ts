import css from './style.css';
import { App, vscode, type Tab, type TabId } from './app';
import { button, h } from './dom';
import { OverviewTab } from './tabs/overview';
import { CpuTab } from './tabs/cpu';
import { MemoryTab } from './tabs/memory';
import { AsyncTab } from './tabs/async';
import { TimelineTab } from './tabs/timeline';
import { fmtMs } from '../shared/format';
import type { ToWebview } from '../shared/protocol';

document.head.appendChild(h('style', null, css));

const app = new App();
const root = document.getElementById('app') ?? document.body;
const header = h('div', { class: 'header' });
const tabsBar = h('div', { class: 'tabs', role: 'tablist' });
const host = h('div', { style: 'flex:1;display:flex;flex-direction:column;min-height:0' });
let tabs: Record<TabId, Tab> | undefined;
let initialized = false;

const TAB_LABELS: [TabId, string][] = [
  ['overview', 'Overview'],
  ['cpu', 'CPU'],
  ['memory', 'Memory'],
  ['async', 'Async'],
  ['timeline', 'Timeline'],
];

function renderHeader(): void {
  const { live } = app.caps;
  const pill = h('span', { class: `pill ${app.state}` }, app.state === 'file' ? 'saved profile' : app.state);
  const meta = [
    app.model.meta.pid ? `PID ${app.model.meta.pid}` : '',
    app.model.meta.python ? `Python ${app.model.meta.python}${app.model.meta.freeThreaded ? 't' : ''}` : '',
    app.model.meta.platform ? String(app.model.meta.platform) : '',
  ].filter(Boolean).join(' · ');
  const parts: (Node | null)[] = [
    h('span', { class: 'title', title: app.label }, app.label),
    pill,
    h('span', { class: 'meta' }, meta),
    app.range
      ? h('span', { class: 'range-chip' }, `${fmtMs(app.range[0])} – ${fmtMs(app.range[1])}`, h('button', { title: 'Clear time range', onclick: () => app.clearRange() }, '✕'))
      : null,
    h('span', { class: 'spacer' }),
    live ? button('Marker', () => app.command('mark'), { title: 'Drop a named marker on the timeline', icon: '⚑' }) : null,
    live && app.caps.agent ? button('Snapshot', () => app.command('snapshot'), { title: 'Take a memory snapshot (starts tracemalloc if needed)', icon: '📷' }) : null,
    live ? button('Stop', () => app.command('stop'), { primary: true, icon: '■' }) : null,
    button('Save', () => app.command('save'), { title: 'Save as .pyprof' }),
    button('Export', () => app.command('exportSpeedscope'), { title: 'Export to speedscope' }),
  ];
  header.replaceChildren(...parts.filter((x): x is Node => x !== null));
}

function renderTabs(): void {
  const badges: Partial<Record<TabId, string>> = {};
  const issues = app.model.events.filter((e) => e.kind === 'slow-callback' || e.kind === 'never-awaited').length;
  if (issues) badges.async = String(issues);
  if (app.model.snapshots.length) badges.memory = String(app.model.snapshots.length);
  tabsBar.replaceChildren(
    ...TAB_LABELS.map(([id, label]) =>
      h(
        'button',
        {
          class: `tab ${app.tab === id ? 'active' : ''}`,
          role: 'tab',
          'aria-selected': String(app.tab === id),
          onclick: () => {
            app.tab = id;
            app.changed(true);
          },
        },
        label,
        badges[id] ? h('span', { class: 'badge' }, badges[id]) : null,
      ),
    ),
  );
}

let mountedTab: TabId | undefined;
function render(full: boolean): void {
  if (!tabs) return;
  renderHeader();
  renderTabs();
  const tab = tabs[app.tab];
  if (mountedTab !== app.tab) {
    host.replaceChildren(tab.el);
    mountedTab = app.tab;
    full = true;
  }
  try {
    tab.update(full);
  } catch (e) {
    console.error(e);
  }
}

// live updates: coalesce deltas, redraw at most ~2x per second
let pending = false;
let lastDraw = 0;
function scheduleLive(): void {
  if (pending) return;
  pending = true;
  const wait = Math.max(0, 500 - (performance.now() - lastDraw));
  setTimeout(() => {
    pending = false;
    lastDraw = performance.now();
    render(false);
  }, wait);
}

app.onChange((full) => render(full));

window.addEventListener('message', (ev: MessageEvent<ToWebview>) => {
  const msg = ev.data;
  switch (msg.type) {
    case 'init':
      app.model.applyDelta(msg.data);
      app.label = msg.label;
      app.state = msg.state;
      app.caps = msg.capabilities;
      if (!initialized) {
        initialized = true;
        tabs = {
          overview: new OverviewTab(app),
          cpu: new CpuTab(app),
          memory: new MemoryTab(app),
          async: new AsyncTab(app),
          timeline: new TimelineTab(app),
        };
        root.replaceChildren(header, tabsBar, host);
      }
      app.changed(true);
      break;
    case 'delta':
      app.model.applyDelta(msg.data);
      scheduleLive();
      break;
    case 'state':
      app.state = msg.state;
      app.caps = msg.capabilities;
      render(true);
      break;
    case 'reveal':
      tabs?.cpu.reveal?.(msg.fn);
      break;
    case 'error':
      showToast(msg.message);
      break;
  }
});

function showToast(text: string): void {
  const t = h('div', { class: 'banner warn', style: 'position:fixed;bottom:12px;right:12px;z-index:50;max-width:480px' }, text);
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 6000);
}

window.addEventListener('keydown', (e) => {
  if (e.target instanceof HTMLInputElement) return;
  const n = Number(e.key);
  if (n >= 1 && n <= TAB_LABELS.length && !e.ctrlKey && !e.metaKey && !e.altKey) {
    app.tab = TAB_LABELS[n - 1][0];
    app.changed(true);
  }
});

vscode.postMessage({ type: 'ready' });
