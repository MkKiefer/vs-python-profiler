/** Sortable data table and expandable call tree. */
import { h } from '../dom';
import { frameColor } from './colors';
import type { ProfileModel, TreeNode } from '../../shared/model';
import { fmtPct, shortPath } from '../../shared/format';

export interface Column<R> {
  label: string;
  num?: boolean;
  cls?: string;
  title?: string;
  value: (r: R) => number | string;
  render?: (r: R) => Node | string;
  /** draw a proportional bar behind the cell (value / max) */
  bar?: boolean;
}

export class DataTable<R> {
  readonly el: HTMLElement;
  private table = h('table', { class: 'data' });
  private rows: R[] = [];
  private sortCol: number;
  private asc = false;
  private selected: R | undefined;

  constructor(
    private readonly cols: Column<R>[],
    private readonly opts: { onClick?: (r: R) => void; onDblClick?: (r: R) => void; sortCol?: number; limit?: number; empty?: string } = {},
  ) {
    this.sortCol = opts.sortCol ?? 0;
    this.el = h('div', { class: 'table-wrap' }, this.table);
  }

  setRows(rows: R[]): void {
    this.rows = rows;
    this.render();
  }

  private render(): void {
    const { cols } = this;
    const sorted = [...this.rows];
    const c = cols[this.sortCol];
    sorted.sort((a, b) => {
      const va = c.value(a);
      const vb = c.value(b);
      const d = typeof va === 'number' && typeof vb === 'number' ? va - vb : String(va).localeCompare(String(vb));
      return this.asc ? d : -d;
    });
    const limit = this.opts.limit ?? 500;
    const shown = sorted.slice(0, limit);
    const max = cols.map((col) => (col.bar ? Math.max(1e-9, ...shown.map((r) => Math.abs(Number(col.value(r))) || 0)) : 0));
    const head = h(
      'tr',
      null,
      cols.map((col, i) =>
        h(
          'th',
          {
            class: `${col.num ? 'num' : ''} ${i === this.sortCol ? 'sorted' : ''} ${i === this.sortCol && this.asc ? 'asc' : ''}`,
            title: col.title ?? '',
            onclick: () => {
              if (this.sortCol === i) this.asc = !this.asc;
              else {
                this.sortCol = i;
                this.asc = !col.num;
              }
              this.render();
            },
          },
          col.label,
        ),
      ),
    );
    const body = shown.map((r) => {
      const tr = h(
        'tr',
        {
          class: r === this.selected ? 'selected' : '',
          onclick: () => {
            this.selected = r;
            this.table.querySelectorAll('tr.selected').forEach((x) => x.classList.remove('selected'));
            tr.classList.add('selected');
            this.opts.onClick?.(r);
          },
          ondblclick: () => this.opts.onDblClick?.(r),
        },
        cols.map((col, i) => {
          const content = col.render ? col.render(r) : String(col.value(r));
          if (col.bar) {
            const v = Number(col.value(r));
            const bar = h('div', { class: `bar${v < 0 ? ' neg' : ''}` });
            bar.style.width = `${Math.min(100, (Math.abs(v) / max[i]) * 100)}%`;
            return h('td', { class: `bar-cell ${col.num ? 'num' : ''} ${col.cls ?? ''}` }, bar, h('span', null, content));
          }
          return h('td', { class: `${col.num ? 'num' : ''} ${col.cls ?? ''}` }, content);
        }),
      );
      return tr;
    });
    this.table.replaceChildren(h('thead', null, head), h('tbody', null, body));
    if (!shown.length) {
      this.table.appendChild(h('tbody', null, h('tr', null, h('td', { colSpan: cols.length, class: 'empty' }, this.opts.empty ?? 'No data'))));
    } else if (sorted.length > limit) {
      this.table.appendChild(h('tbody', null, h('tr', null, h('td', { colSpan: cols.length, class: 'muted' }, `… ${sorted.length - limit} more rows`))));
    }
  }
}

/** Expandable call tree (top-down, inverted or focused) with percentage bars. */
export class CallTreeView {
  readonly el: HTMLElement;
  private table = h('table', { class: 'data' });
  private expanded = new Set<string>();
  private root: TreeNode | undefined;
  private model: ProfileModel | undefined;
  private autoExpanded = false;

  constructor(
    private readonly opts: { format: (w: number) => string; onOpen: (file: string, line: number) => void; onFocus?: (fn: number) => void; weightLabel?: string },
  ) {
    this.el = h('div', { class: 'table-wrap' }, this.table);
  }

  setData(model: ProfileModel, root: TreeNode, resetExpansion = false): void {
    this.model = model;
    this.root = root;
    if (resetExpansion) {
      this.expanded.clear();
      this.autoExpanded = false;
    }
    if (!this.autoExpanded && root.children.length) {
      // open the hot path: follow the heaviest child while it carries ≥ 40% of the parent
      let n = root;
      let key = '';
      for (let d = 0; d < 30 && n.children.length; d++) {
        const c = n.children[0];
        key += '/' + c.key;
        this.expanded.add(key);
        if (c.total < n.total * 0.4) break;
        n = c;
      }
      this.autoExpanded = true;
    }
    this.render();
  }

  private render(): void {
    if (!this.root || !this.model) return;
    const model = this.model;
    const all = this.root.total || 1;
    const rows: HTMLElement[] = [];
    const walk = (n: TreeNode, depth: number, key: string) => {
      const limit = 200;
      n.children.slice(0, limit).forEach((c) => {
        const k = `${key}/${c.key}`;
        const f = model.frames[c.frame];
        const open = this.expanded.has(k);
        const twisty = h('span', { class: 'twisty' }, c.children.length ? (open ? '▾' : '▸') : '');
        const dot = h('span', { class: 'cat-dot' });
        dot.style.background = frameColor(f.cat, f.func);
        const totalBar = h('div', { class: 'bar' });
        totalBar.style.width = `${(c.total / all) * 100}%`;
        const tr = h(
          'tr',
          {
            ondblclick: () => this.opts.onOpen(f.file, f.line),
            oncontextmenu: (e: Event) => {
              e.preventDefault();
              this.opts.onFocus?.(c.fn);
            },
          },
          h('td', { class: 'bar-cell num' }, totalBar, h('span', null, fmtPct(c.total, all))),
          h('td', { class: 'num' }, fmtPct(c.self, all)),
          h('td', { class: 'num' }, this.opts.format(c.total)),
          h('td', { class: 'fn', title: f.func }, h('span', { style: `padding-left:${depth * 14}px` }), twisty, dot, f.func),
          h('td', { class: 'loc', title: `${f.file}:${f.line}` }, `‎${shortPath(f.file, 3)}:${f.line}`),
        );
        twisty.addEventListener('click', (e) => {
          e.stopPropagation();
          if (open) this.expanded.delete(k);
          else this.expanded.add(k);
          this.render();
        });
        tr.addEventListener('click', () => {
          if (!c.children.length) return;
          if (this.expanded.has(k)) this.expanded.delete(k);
          else this.expanded.add(k);
          this.render();
        });
        rows.push(tr);
        if (open) walk(c, depth + 1, k);
      });
      if (n.children.length > limit) {
        rows.push(h('tr', null, h('td', { colSpan: 5, class: 'muted' }, h('span', { style: `padding-left:${depth * 14 + 14}px` }, `… ${n.children.length - limit} more`))));
      }
    };
    walk(this.root, 0, '');
    const scrollTop = this.el.scrollTop;
    this.table.replaceChildren(
      h(
        'thead',
        null,
        h(
          'tr',
          null,
          h('th', { class: 'num', title: 'Share of all samples in this frame and below' }, 'Total'),
          h('th', { class: 'num', title: 'Share of samples where this frame was executing' }, 'Self'),
          h('th', { class: 'num' }, this.opts.weightLabel ?? 'Time'),
          h('th', null, 'Function'),
          h('th', null, 'Location'),
        ),
      ),
      h('tbody', null, rows.length ? rows : h('tr', null, h('td', { colSpan: 5, class: 'empty' }, 'No samples in this selection'))),
    );
    this.el.scrollTop = scrollTop;
  }
}
