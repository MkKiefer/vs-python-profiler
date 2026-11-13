/** The one place that reads and writes `pyprof.*` settings (keys and defaults mirror package.json). */
import * as vscode from 'vscode';
import type { CollectorOptions } from '../shared/protocol';

export type FollowChildren = 'ask' | 'always' | 'never';
export type HeatMetric = 'self' | 'total';

const SECTION = 'pyprof';

function config(resource?: vscode.Uri): vscode.WorkspaceConfiguration {
  return vscode.workspace.getConfiguration(SECTION, resource);
}

export const settings = {
  /** Collector options from the user's settings; explicitly given `overrides` win. */
  collectorOptions(resource?: vscode.Uri, overrides: CollectorOptions = {}): CollectorOptions {
    const c = config(resource);
    return {
      rateHz: c.get('samplingRate', 1000),
      native: c.get('nativeFrames', false),
      blocking: c.get('blockingSampling', false),
      tracemalloc: c.get('memory.tracemallocOnStart', false),
      tracemallocFrames: c.get('memory.tracebackFrames', 16),
      asyncioDebug: c.get('asyncio.debugOnStart', false),
      slowCallbackMs: c.get('asyncio.slowCallbackMs', 100),
      asyncAware: true,
      gc: true,
      ...(Object.fromEntries(Object.entries(overrides).filter(([, v]) => v !== undefined)) as CollectorOptions),
    };
  },

  slowCallbackMs(): number {
    return config().get('asyncio.slowCallbackMs', 100);
  },

  followChildren(): FollowChildren {
    return config().get<FollowChildren>('followChildren', 'ask');
  },

  async alwaysFollowChildren(): Promise<void> {
    await config().update('followChildren', 'always', vscode.ConfigurationTarget.Global);
  },

  openDashboardOnStart(): boolean {
    return config().get('openDashboardOnStart', true);
  },

  autoSave(): boolean {
    return config().get('autoSave', true);
  },

  terminalIntegration(): boolean {
    return config().get('terminalIntegration', true);
  },

  /** Fallback interpreter when the Python extension is unavailable. */
  pythonPath(resource?: vscode.Uri): string | undefined {
    return config(resource).get<string>('pythonPath') || undefined;
  },

  heatMapEnabled(): boolean {
    return config().get('heatMap.enabled', true);
  },

  async setHeatMapEnabled(enabled: boolean): Promise<void> {
    await config().update('heatMap.enabled', enabled, vscode.ConfigurationTarget.Global);
  },

  heatMapMetric(): HeatMetric {
    return config().get<HeatMetric>('heatMap.metric', 'total');
  },

  codeLensEnabled(): boolean {
    return config().get('codeLens.enabled', true);
  },

  changedBy(event: vscode.ConfigurationChangeEvent): boolean {
    return event.affectsConfiguration(SECTION);
  },
};
