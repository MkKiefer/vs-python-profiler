/**
 * Chart colours. Theme colours come from CSS custom properties (VS Code's
 * `--vscode-charts-*` and the dashboard's own `--pp-*` tokens in style.css),
 * so light, dark and high-contrast themes all work.
 */
import { Cat } from '../../shared/model';
import { hashString } from './canvas';

export type ChartColor = 'red' | 'blue' | 'yellow' | 'orange' | 'green' | 'purple' | 'foreground' | 'lines';

/** Dashboard tokens a canvas needs (defined in style.css). */
export type ChartToken = 'hover-outline' | 'brush' | 'outside-selection' | 'flame-text' | 'flame-root';

function cssVar(name: string): string {
  return getComputedStyle(document.body).getPropertyValue(name).trim();
}

export function chartColor(name: ChartColor): string {
  return cssVar(`--pp-chart-${name}`) || 'currentColor';
}

export function chartToken(name: ChartToken): string {
  return cssVar(`--pp-${name}`) || 'currentColor';
}

function isDarkTheme(): boolean {
  const classes = document.body.classList;
  return classes.contains('vscode-dark') || classes.contains('vscode-high-contrast');
}

/**
 * Flame graph fill per frame category; the lightness varies by function name
 * so neighbours are distinguishable. Category hues are data colours, tuned
 * for light and dark themes.
 */
export function frameColor(cat: Cat, name: string, dimmed = false): string {
  const jitter = (hashString(name) % 1000) / 1000;
  const dark = isDarkTheme();
  let hue: number;
  let sat: number;
  let light: number;
  switch (cat) {
    case Cat.User:
      hue = 14 + jitter * 30; // red → orange
      sat = 78;
      light = dark ? 50 + jitter * 10 : 62 + jitter * 10;
      break;
    case Cat.Lib:
      hue = 195 + jitter * 25; // teal → blue
      sat = 55;
      light = dark ? 45 + jitter * 10 : 66 + jitter * 10;
      break;
    case Cat.Std:
      hue = 95 + jitter * 50; // muted green
      sat = 22;
      light = dark ? 40 + jitter * 10 : 70 + jitter * 8;
      break;
    default:
      hue = 275 + jitter * 20; // purple: <native>, <GC>, <task>
      sat = 40;
      light = dark ? 45 : 72;
  }
  if (dimmed) return `hsla(${hue},${sat * 0.3}%,${light}%,0.35)`;
  return `hsl(${hue},${sat}%,${light}%)`;
}

export const CATEGORY_LABELS: Record<Cat, string> = {
  [Cat.User]: 'your code',
  [Cat.Lib]: 'libraries',
  [Cat.Std]: 'stdlib',
  [Cat.Synth]: 'native / GC / task',
};
