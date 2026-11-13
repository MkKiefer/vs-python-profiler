import type { DOMWrapper, VueWrapper } from '@vue/test-utils';

/** Selector of a `data-testid`. */
export function tid(id: string): string {
  return `[data-testid="${id}"]`;
}

/** The element with this `data-testid`; fails when it is missing. */
export function byTid(wrapper: VueWrapper, id: string): Omit<DOMWrapper<Element>, 'exists'> {
  return wrapper.get(tid(id));
}

/** Buttons (and tabs) whose visible text is exactly `text`. */
export function buttonsByText(wrapper: VueWrapper, text: string): DOMWrapper<HTMLButtonElement>[] {
  return wrapper.findAll('button').filter((button) => button.text() === text);
}

/** The one button with this visible text; fails when there is none or several. */
export function buttonByText(wrapper: VueWrapper, text: string): DOMWrapper<HTMLButtonElement> {
  const buttons = buttonsByText(wrapper, text);
  if (buttons.length !== 1) throw new Error(`expected one button "${text}", found ${buttons.length}`);
  return buttons[0];
}
