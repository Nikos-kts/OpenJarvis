/**
 * Config API client — wraps the `/v1/config` endpoints.
 *
 * All settings that used to live in `~/.openjarvis/config.toml` are
 * accessed through this module.  The backend is the single source of
 * truth; the SettingsPage hydrates from `getConfig()` + `getSchema()`
 * and writes changes back via `patchConfig()`.
 */
import { getBase } from './api';

/** Sentinel the backend returns for secret fields that have a value set.
 *  If the UI echoes this back in a PATCH, the backend treats it as
 *  "no change" and preserves the stored value. */
export const MASKED_PLACEHOLDER = '__SECRET_SET__';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type ConfigValue =
  | string
  | number
  | boolean
  | null
  | ConfigValue[]
  | { [key: string]: ConfigValue };

export type ConfigDict = Record<string, ConfigValue>;

export interface ConfigFieldSchema {
  dotted: string;
  type: 'string' | 'integer' | 'number' | 'boolean' | 'array' | 'object';
  default?: ConfigValue;
  secret?: boolean;
  advanced?: boolean;
  restart_required?: boolean;
  properties?: Record<string, ConfigFieldSchema>;
}

export interface ConfigSectionSchema {
  title: string;
  readonly?: boolean;
  properties: Record<string, ConfigFieldSchema>;
}

export interface ConfigSchema {
  sections: Record<string, ConfigSectionSchema>;
}

export interface PatchResponse {
  changed_keys: string[];
  restart_required: boolean;
  restart_reasons: string[];
  config: ConfigDict;
}

// ---------------------------------------------------------------------------
// Low-level fetch helpers
// ---------------------------------------------------------------------------

async function jsonFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const base = getBase();
  const res = await fetch(`${base}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers || {}),
    },
  });
  if (!res.ok) {
    let detail: unknown = undefined;
    try {
      detail = await res.json();
    } catch {}
    throw new ConfigApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export class ConfigApiError extends Error {
  constructor(public readonly status: number, public readonly detail: unknown) {
    super(`Config API error: HTTP ${status}`);
  }
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export async function getConfig(): Promise<ConfigDict> {
  return jsonFetch<ConfigDict>('/v1/config');
}

export async function getDefaults(): Promise<ConfigDict> {
  return jsonFetch<ConfigDict>('/v1/config/defaults');
}

export async function getSchema(): Promise<ConfigSchema> {
  return jsonFetch<ConfigSchema>('/v1/config/schema');
}

export async function getHardware(): Promise<Record<string, ConfigValue>> {
  return jsonFetch<Record<string, ConfigValue>>('/v1/config/hardware');
}

export async function patchConfig(patch: Record<string, ConfigValue>): Promise<PatchResponse> {
  return jsonFetch<PatchResponse>('/v1/config', {
    method: 'PATCH',
    body: JSON.stringify({ patch }),
  });
}

export async function reloadConfig(): Promise<PatchResponse> {
  return jsonFetch<PatchResponse>('/v1/config/reload', { method: 'POST' });
}

// ---------------------------------------------------------------------------
// Dotted-path helpers (used by the SettingsPage form)
// ---------------------------------------------------------------------------

export function getByPath(obj: ConfigDict, dotted: string): ConfigValue | undefined {
  const parts = dotted.split('.');
  let current: ConfigValue | undefined = obj;
  for (const p of parts) {
    if (current && typeof current === 'object' && !Array.isArray(current)) {
      current = (current as ConfigDict)[p];
    } else {
      return undefined;
    }
  }
  return current;
}
