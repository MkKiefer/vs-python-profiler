import { inject, type InjectionKey } from 'vue';
import type { HostClient } from './hostClient';

export const hostClientKey: InjectionKey<HostClient> = Symbol('HostClient');

/** The host client the app was created with (stores and components). */
export function useHostClient(): HostClient {
  const client = inject(hostClientKey);
  if (!client) throw new Error('HostClient was not provided to the app');
  return client;
}
