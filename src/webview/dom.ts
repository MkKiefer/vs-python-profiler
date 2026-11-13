/** Tiny DOM helpers – no framework, the dashboard is canvas-heavy anyway. */

type Attrs = Record<string, unknown> & { class?: string; style?: string };
type Child = Node | string | number | null | undefined | false | Child[];

export function h<K extends keyof HTMLElementTagNameMap>(tag: K, attrs: Attrs | null = null, ...children: Child[]): HTMLElementTagNameMap[K] {
  const el = document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v === undefined || v === null || v === false) continue;
      if (k.startsWith('on') && typeof v === 'function') {
        el.addEventListener(k.slice(2).toLowerCase(), v as EventListener);
      } else if (k === 'class') {
        el.className = attrText(v);
      } else if (k === 'style') {
        el.setAttribute('style', attrText(v));
      } else if (k in el && typeof v !== 'string') {
        (el as unknown as Record<string, unknown>)[k] = v;
      } else {
        el.setAttribute(k, v === true ? '' : attrText(v));
      }
    }
  }
  append(el, children);
  return el;
}

function attrText(value: unknown): string {
  return typeof value === 'string' ? value : typeof value === 'number' ? String(value) : '';
}

function append(el: HTMLElement, children: Child[]): void {
  for (const c of children) {
    if (c === null || c === undefined || c === false) continue;
    if (Array.isArray(c)) append(el, c);
    else el.appendChild(typeof c === 'string' || typeof c === 'number' ? document.createTextNode(String(c)) : c);
  }
}

export function cssVar(name: string, fallback = '#888'): string {
  const v = getComputedStyle(document.body).getPropertyValue(name).trim();
  return v || fallback;
}

export function isDark(): boolean {
  return document.body.classList.contains('vscode-dark') || document.body.classList.contains('vscode-high-contrast');
}

export interface SegOption<T extends string> {
  value: T;
  label: string;
  title?: string;
}

export function segmented<T extends string>(options: SegOption<T>[], value: T, onChange: (v: T) => void): HTMLElement {
  const wrap = h('div', { class: 'seg', role: 'radiogroup' });
  for (const o of options) {
    const b = h('button', {
      class: o.value === value ? 'active' : '',
      title: o.title ?? '',
      role: 'radio',
      'aria-checked': String(o.value === value),
      onclick: () => {
        wrap.querySelectorAll('button').forEach((x) => {
          x.classList.remove('active');
          x.setAttribute('aria-checked', 'false');
        });
        b.classList.add('active');
        b.setAttribute('aria-checked', 'true');
        onChange(o.value);
      },
    }, o.label);
    wrap.appendChild(b);
  }
  return wrap;
}

export function button(label: string, onClick: () => void, opts: { title?: string; primary?: boolean; disabled?: boolean; icon?: string } = {}): HTMLButtonElement {
  return h(
    'button',
    { class: `btn${opts.primary ? ' primary' : ''}`, title: opts.title ?? '', disabled: opts.disabled ?? false, onclick: onClick },
    opts.icon ? h('span', { class: 'icon' }, opts.icon) : null,
    label,
  );
}

export function checkbox(label: string, checked: boolean, onChange: (v: boolean) => void, title = ''): HTMLElement {
  const input = h('input', { type: 'checkbox', checked, onchange: (e: Event) => onChange((e.target as HTMLInputElement).checked) });
  return h('label', { class: 'check', title }, input, label);
}

export function tile(label: string, value: string, sub = '', tone: '' | 'warn' | 'bad' | 'good' = ''): HTMLElement {
  return h('div', { class: `tile ${tone}` }, h('div', { class: 'tile-label' }, label), h('div', { class: 'tile-value' }, value), sub ? h('div', { class: 'tile-sub' }, sub) : null);
}

export function hashString(s: string): number {
  let x = 2166136261;
  for (let i = 0; i < s.length; i++) {
    x ^= s.charCodeAt(i);
    x = Math.imul(x, 16777619);
  }
  return x >>> 0;
}

/** Fit a canvas to its CSS box with devicePixelRatio scaling; returns 2d context in CSS px. */
export function fitCanvas(canvas: HTMLCanvasElement, width: number, height: number): CanvasRenderingContext2D {
  const dpr = window.devicePixelRatio || 1;
  const w = Math.max(1, Math.floor(width));
  const hh = Math.max(1, Math.floor(height));
  if (canvas.width !== w * dpr || canvas.height !== hh * dpr) {
    canvas.width = w * dpr;
    canvas.height = hh * dpr;
    canvas.style.width = `${w}px`;
    canvas.style.height = `${hh}px`;
  }
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('2D canvas rendering is not available');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return ctx;
}

export function tooltip(): { show: (x: number, y: number, html: HTMLElement | string) => void; hide: () => void } {
  let el = document.getElementById('tooltip');
  if (!el) {
    el = h('div', { id: 'tooltip', role: 'tooltip' });
    document.body.appendChild(el);
  }
  const tip = el;
  return {
    show(x, y, content) {
      tip.replaceChildren(content);
      tip.style.display = 'block';
      const r = tip.getBoundingClientRect();
      const left = Math.min(window.innerWidth - r.width - 8, x + 14);
      const top = y + r.height + 20 > window.innerHeight ? y - r.height - 10 : y + 16;
      tip.style.left = `${Math.max(4, left)}px`;
      tip.style.top = `${Math.max(4, top)}px`;
    },
    hide() {
      tip.style.display = 'none';
    },
  };
}
