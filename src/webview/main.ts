/** Webview entry point: wires the real host client into the dashboard and mounts it. */
import './style.css';
import { createApp } from 'vue';
import { createPinia } from 'pinia';
import App from './App.vue';
import { createDashboardRouter } from './router';
import { hostClientKey } from './services/hostClientKey';
import { VsCodeHostClient, type VsCodeApi } from './services/vsCodeHostClient';

declare function acquireVsCodeApi(): VsCodeApi;

createApp(App)
  .provide(hostClientKey, new VsCodeHostClient(acquireVsCodeApi(), window))
  .use(createPinia())
  .use(createDashboardRouter())
  .mount('#app');
