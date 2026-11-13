import { Cat } from '../../shared/model';
import { cssVar, hashString, isDark } from '../dom';

/** Theme chart colors (VS Code exposes --vscode-charts-*). */
export function chartColor(name: 'red' | 'blue' | 'yellow' | 'orange' | 'green' | 'purple' | 'foreground' | 'lines'): string {
  const fallback: Record<string, string> = {
    red: '#f14c4c', blue: '#3794ff', yellow: '#cca700', orange: '#d18616',
    green: '#89d185', purple: '#b180d7', foreground: '#ccc', lines: 'rgba(128,128,128,.35)',
  };
  return cssVar(`--vscode-charts-${name}`, fallback[name]);
}

/** Flame graph fill per frame category; lightness varies by function name. */
export function frameColor(cat: Cat, name: string, dimmed = false): string {
  const h = hashString(name);
  const jitter = (h % 1000) / 1000;
  const dark = isDark();
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
      hue = 95 + jitter * 50; // green-ish, muted
      sat = 22;
      light = dark ? 40 + jitter * 10 : 70 + jitter * 8;
      break;
    default:
      hue = 275 + jitter * 20; // purple for <native>, <GC>, <task>
      sat = 40;
      light = dark ? 45 : 72;
  }
  if (dimmed) return `hsla(${hue},${sat * 0.3}%,${light}%,0.35)`;
  return `hsl(${hue},${sat}%,${light}%)`;
}

export const CAT_LABEL: Record<number, string> = {
  [Cat.User]: 'your code',
  [Cat.Lib]: 'libraries',
  [Cat.Std]: 'stdlib',
  [Cat.Synth]: 'native / GC / task',
};
