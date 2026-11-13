/**
 * Canvas icicle/flame graph. Root at the top, children below, width = weight.
 * Click: zoom · double-click: open source · right-click / Alt-click: focus
 * (callers & callees) · search dims non-matching frames.
 */
import { fitCanvas, h, tooltip } from '../dom';
import { frameColor, CAT_LABEL } from './colors';
import type { ProfileModel, TreeNode } from '../../shared/model';
import { fmtPct, shortPath } from '../../shared/format';

const ROW = 18;

export interface FlameOptions {
  format: (w: number) => string;
  onOpen?: (file: string, line: number) => void;
  onFocus?: (fn: number) => void;
  weightLabel?: string;
}

interface Rect {
  x: number;
  y: number;
  w: number;
  node: TreeNode;
  depth: number;
}

export class FlameGraph {
  readonly el: HTMLElement;
  private crumbs = h('div', { class: 'crumbs' });
  private wrap = h('div', { class: 'flame-wrap' });
  private canvas = h('canvas', { tabindex: 0, 'aria-label': 'Flame graph' });
  private root: TreeNode | undefined;
  private model: ProfileModel | undefined;
  private zoomPath: number[] = []; // keys from root to zoom node
  private rects: Rect[] = [];
  private hover: TreeNode | undefined;
  private search = '';
  private tip = tooltip();
  private ro: ResizeObserver;
  private raf = 0;

  constructor(private readonly opts: FlameOptions) {
    this.el = h('div', { style: 'display:flex;flex-direction:column;flex:1;min-height:0' }, this.crumbs, this.wrap);
    this.wrap.appendChild(this.canvas);
    this.ro = new ResizeObserver(() => this.schedule());
    this.ro.observe(this.wrap);
    this.canvas.addEventListener('mousemove', (e) => this.onMove(e));
    this.canvas.addEventListener('mouseleave', () => {
      this.hover = undefined;
      this.tip.hide();
      this.schedule();
    });
    this.canvas.addEventListener('click', (e) => {
      const r = this.hit(e);
      if (!r) return;
      if (e.altKey) {
        this.opts.onFocus?.(r.node.fn);
        return;
      }
      this.zoomTo(r.node);
    });
    this.canvas.addEventListener('dblclick', (e) => {
      const r = this.hit(e);
      if (r && this.model) {
        const f = this.model.frames[r.node.frame];
        this.opts.onOpen?.(f.file, f.line);
      }
    });
    this.canvas.addEventListener('contextmenu', (e) => {
      const r = this.hit(e);
      if (r) {
        e.preventDefault();
        this.opts.onFocus?.(r.node.fn);
      }
    });
    this.canvas.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' || e.key === 'Backspace') {
        this.zoomPath.pop();
        this.draw();
      }
    });
  }

  setData(model: ProfileModel, root: TreeNode): void {
    this.model = model;
    this.root = root;
    this.schedule();
  }

  setSearch(s: string): void {
    this.search = s.toLowerCase();
    this.schedule();
  }

  resetZoom(): void {
    this.zoomPath = [];
    this.schedule();
  }

  private schedule(): void {
    cancelAnimationFrame(this.raf);
    this.raf = requestAnimationFrame(() => this.draw());
  }

  private zoomTo(node: TreeNode): void {
    const path = this.pathTo(node);
    if (path) this.zoomPath = path;
    this.draw();
  }

  private pathTo(target: TreeNode): number[] | undefined {
    const walk = (n: TreeNode, acc: number[]): number[] | undefined => {
      if (n === target) return acc;
      for (const c of n.children) {
        const r = walk(c, [...acc, c.key]);
        if (r) return r;
      }
      return undefined;
    };
    return this.root ? walk(this.root, []) : undefined;
  }

  private zoomNode(root: TreeNode): { node: TreeNode; chain: TreeNode[] } {
    let node = root;
    const chain: TreeNode[] = [node];
    for (const key of this.zoomPath) {
      const next = node.children.find((c) => c.key === key);
      if (!next) break;
      node = next;
      chain.push(node);
    }
    return { node, chain };
  }

  private name(n: TreeNode): string {
    return this.model?.frames[n.frame]?.func ?? 'all';
  }

  draw(): void {
    if (!this.root || !this.model) return;
    const model = this.model;
    const { node: zoom, chain } = this.zoomNode(this.root);
    this.renderCrumbs(chain);
    const W = this.wrap.clientWidth || 600;
    // depth of visible subtree
    let maxDepth = 0;
    const minW = 0.5;
    const measure = (n: TreeNode, d: number, w: number) => {
      maxDepth = Math.max(maxDepth, d);
      for (const c of n.children) {
        const cw = (c.total / n.total) * w;
        if (cw >= minW) measure(c, d + 1, cw);
      }
    };
    measure(zoom, 0, W);
    const H = Math.max(this.wrap.clientHeight, (maxDepth + chain.length + 1) * ROW + 4);
    const ctx = fitCanvas(this.canvas, W, H);
    ctx.clearRect(0, 0, W, H);
    ctx.font = '11px var(--vscode-editor-font-family), monospace';
    ctx.textBaseline = 'middle';
    this.rects = [];
    const total = zoom.total || 1;
    const searching = this.search.length > 0;

    const drawRect = (n: TreeNode, x: number, y: number, w: number, depth: number, ancestor = false) => {
      const isRoot = n.frame < 0;
      const f = isRoot ? undefined : model.frames[n.frame];
      const label = f ? f.func : `all (${this.opts.format(n.total)})`;
      const match = !searching || (f && (f.func.toLowerCase().includes(this.search) || f.file.toLowerCase().includes(this.search)));
      ctx.fillStyle = f ? frameColor(f.cat, f.func, !match || ancestor) : 'rgba(128,128,128,0.35)';
      ctx.fillRect(x, y, Math.max(0.5, w - 1), ROW - 1);
      if (this.hover === n) {
        ctx.strokeStyle = 'rgba(255,255,255,0.9)';
        ctx.lineWidth = 1.5;
        ctx.strokeRect(x + 0.5, y + 0.5, Math.max(0.5, w - 2), ROW - 2);
      }
      if (w > 28) {
        ctx.fillStyle = isRoot || ancestor ? getComputedStyle(document.body).color : '#111';
        const text = fitText(ctx, label, w - 6);
        if (text) ctx.fillText(text, x + 3, y + ROW / 2);
      }
      this.rects.push({ x, y, w, node: n, depth });
    };

    // ancestors of the zoom node, full width
    let y = 0;
    for (let i = 0; i < chain.length - 1; i++) {
      drawRect(chain[i], 0, y, W, i, true);
      y += ROW;
    }
    const layout = (n: TreeNode, x: number, yy: number, w: number, depth: number) => {
      drawRect(n, x, yy, w, depth);
      let cx = x;
      for (const c of n.children) {
        const cw = (c.total / n.total) * w;
        if (cw < minW) break; // children are sorted desc
        layout(c, cx, yy + ROW, cw, depth + 1);
        cx += cw;
      }
    };
    layout(zoom, 0, y, W * (zoom.total / total), chain.length - 1);
  }

  private renderCrumbs(chain: TreeNode[]): void {
    this.crumbs.replaceChildren();
    if (chain.length <= 1) {
      this.crumbs.appendChild(
        h('span', { class: 'muted' }, 'Click a frame to zoom · double-click to open source · right-click for callers/callees · Esc to zoom out'),
      );
      return;
    }
    chain.forEach((n, i) => {
      if (i) this.crumbs.appendChild(h('span', { class: 'sep' }, '›'));
      const last = i === chain.length - 1;
      this.crumbs.appendChild(
        last
          ? h('span', null, this.name(n))
          : h('a', { onclick: () => { this.zoomPath = this.zoomPath.slice(0, i); this.draw(); } }, this.name(n)),
      );
    });
  }

  private hit(e: MouseEvent): Rect | undefined {
    const r = this.canvas.getBoundingClientRect();
    const x = e.clientX - r.left;
    const y = e.clientY - r.top;
    for (let i = this.rects.length - 1; i >= 0; i--) {
      const rc = this.rects[i];
      if (x >= rc.x && x < rc.x + rc.w && y >= rc.y && y < rc.y + ROW) return rc;
    }
    return undefined;
  }

  private onMove(e: MouseEvent): void {
    const r = this.hit(e);
    const node = r?.node;
    if (node !== this.hover) {
      this.hover = node;
      this.draw();
    }
    if (!node || !this.model || !this.root) {
      this.tip.hide();
      return;
    }
    if (node.frame < 0) {
      this.tip.show(e.clientX, e.clientY, h('div', null, h('div', { class: 'tt-title' }, 'all'), this.opts.format(node.total)));
      return;
    }
    const f = this.model.frames[node.frame];
    const all = this.root.total;
    this.tip.show(
      e.clientX,
      e.clientY,
      h(
        'div',
        null,
        h('div', { class: 'tt-title' }, f.func),
        h('div', { class: 'tt-sub' }, `${shortPath(f.file, 3)}:${f.line} · ${CAT_LABEL[f.cat]}`),
        h(
          'table',
          null,
          h('tr', null, h('td', null, 'total'), h('td', null, this.opts.format(node.total)), h('td', null, fmtPct(node.total, all))),
          h('tr', null, h('td', null, 'self'), h('td', null, this.opts.format(node.self)), h('td', null, fmtPct(node.self, all))),
        ),
      ),
    );
  }

  dispose(): void {
    this.ro.disconnect();
  }
}

function fitText(ctx: CanvasRenderingContext2D, text: string, w: number): string {
  if (ctx.measureText(text).width <= w) return text;
  let lo = 0;
  let hi = text.length;
  while (lo < hi) {
    const mid = (lo + hi + 1) >>> 1;
    if (ctx.measureText(text.slice(0, mid) + '…').width <= w) lo = mid;
    else hi = mid - 1;
  }
  return lo > 1 ? text.slice(0, lo) + '…' : '';
}
