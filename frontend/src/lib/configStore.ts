/**
 * Zustand store for backend configuration (the SettingsPage's live state).
 *
 * Separation of concerns:
 *   - `lib/store.ts`      → UI-only preferences (theme, fontSize, apiUrl).
 *   - `lib/configStore.ts` → Everything persisted server-side in
 *                            `~/.openjarvis/config.toml`.
 *
 * Flow:
 *   1. `hydrate()` fetches `{config, defaults, schema}` from the backend.
 *   2. `patch({ 'intelligence.temperature': 0.2 })` POSTs to the backend,
 *      reconciles the returned config, and records restart-required reasons
 *      so a banner can be shown.
 *   3. `reloadFromDisk()` asks the server to re-read the TOML file (useful
 *      when a power user edited it by hand).
 */
import { create } from 'zustand';
import {
  getConfig,
  getDefaults,
  getHardware,
  getSchema,
  patchConfig,
  reloadConfig,
  type ConfigDict,
  type ConfigSchema,
  type ConfigValue,
} from './configApi';

type LoadState = 'idle' | 'loading' | 'ready' | 'error';

interface ConfigStoreState {
  loadState: LoadState;
  error: string | null;

  config: ConfigDict | null;
  defaults: ConfigDict | null;
  schema: ConfigSchema | null;
  hardware: Record<string, ConfigValue> | null;

  /** Reasons surfaced by the backend's SubsystemReloader. Cleared on dismiss. */
  restartReasons: string[];
  /** Timestamp of the most recent successful patch. */
  lastUpdated: number | null;
  /** Count of keys picked up by the last reload-from-disk. null = never reloaded. */
  lastReloadChangedCount: number | null;

  // -- actions --
  hydrate: () => Promise<void>;
  patch: (patch: Record<string, ConfigValue>) => Promise<void>;
  reloadFromDisk: () => Promise<void>;
  dismissRestartBanner: () => void;
  resetSection: (section: string) => Promise<void>;
}

export const useConfigStore = create<ConfigStoreState>((set, get) => ({
  loadState: 'idle',
  error: null,
  config: null,
  defaults: null,
  schema: null,
  hardware: null,
  restartReasons: [],
  lastUpdated: null,
  lastReloadChangedCount: null,

  async hydrate() {
    if (get().loadState === 'loading') return;
    set({ loadState: 'loading', error: null });
    try {
      const [config, defaults, schema, hardware] = await Promise.all([
        getConfig(),
        getDefaults(),
        getSchema(),
        getHardware(),
      ]);
      set({
        config,
        defaults,
        schema,
        hardware,
        loadState: 'ready',
        error: null,
      });
    } catch (exc) {
      set({
        loadState: 'error',
        error: exc instanceof Error ? exc.message : String(exc),
      });
    }
  },

  async patch(patch) {
    try {
      const resp = await patchConfig(patch);
      set((s) => ({
        config: resp.config,
        restartReasons: resp.restart_required
          ? Array.from(new Set([...s.restartReasons, ...resp.restart_reasons]))
          : s.restartReasons,
        lastUpdated: Date.now(),
        error: null,
      }));
    } catch (exc) {
      set({ error: exc instanceof Error ? exc.message : String(exc) });
      throw exc;
    }
  },

  async reloadFromDisk() {
    try {
      const resp = await reloadConfig();
      set((s) => ({
        config: resp.config,
        restartReasons: resp.restart_required
          ? Array.from(new Set([...s.restartReasons, ...resp.restart_reasons]))
          : s.restartReasons,
        lastUpdated: Date.now(),
        lastReloadChangedCount: resp.changed_keys.length,
        error: null,
      }));
    } catch (exc) {
      set({ error: exc instanceof Error ? exc.message : String(exc) });
      throw exc;
    }
  },

  dismissRestartBanner() {
    set({ restartReasons: [] });
  },

  async resetSection(section) {
    const { defaults, schema } = get();
    if (!defaults || !schema) return;
    const sectionSchema = schema.sections[section];
    if (!sectionSchema) return;
    const patch: Record<string, ConfigValue> = {};
    const walk = (
      props: Record<string, import('./configApi').ConfigFieldSchema>,
      prefix: string,
    ) => {
      for (const [name, field] of Object.entries(props)) {
        const dotted = prefix ? `${prefix}.${name}` : name;
        if (field.properties) {
          walk(field.properties, dotted);
        } else if (field.default !== undefined) {
          patch[dotted] = field.default as ConfigValue;
        }
      }
    };
    walk(sectionSchema.properties, section);
    if (Object.keys(patch).length > 0) {
      await get().patch(patch);
    }
  },
}));
