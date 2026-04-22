/**
 * SettingsPage — the single place users configure OpenJarvis.
 *
 * Architecture:
 *   - "Appearance" is local-only (theme, font size, API URL → persisted
 *     in localStorage via `useAppStore`).
 *   - Every other section is driven by the backend JSON schema fetched
 *     from `/v1/config/schema` and written through `/v1/config` (PATCH).
 *
 * The sidebar is rendered dynamically from the schema so any new
 * dataclass field added on the backend automatically shows up in the UI
 * without frontend changes.
 */
import { useEffect, useMemo, useState } from 'react';
import {
  HelpCircle,
  Info,
  Monitor,
  Moon,
  Palette,
  RefreshCw,
  Sun,
} from 'lucide-react';
import { useAppStore, type ThemeMode } from '../lib/store';
import { useConfigStore } from '../lib/configStore';
import { ConfigForm } from '../components/settings/ConfigForm';
import { RestartBanner } from '../components/settings/RestartBanner';
import type {
  ConfigDict,
  ConfigSchema,
  ConfigValue,
} from '../lib/configApi';

const APPEARANCE_KEY = '__appearance__';

// Preferred sidebar order.  Sections not in this list fall through to
// alphabetical.  All items here map to dataclass names on JarvisConfig.
const SECTION_ORDER = [
  'engine',
  'intelligence',
  'agent',
  'tools',
  'channel',
  'speech',
  'security',
  'telemetry',
  'traces',
  'scheduler',
  'workflow',
  'sessions',
  'skills',
  'digest',
  'sandbox',
  'learning',
  'optimize',
  'a2a',
  'operators',
  'agent_manager',
  'memory_files',
  'system_prompt',
  'compression',
  'server',
  'hardware',
];

export function SettingsPage() {
  const {
    loadState,
    error,
    config,
    schema,
    hydrate,
    patch,
    reloadFromDisk,
    resetSection,
    lastReloadChangedCount,
  } = useConfigStore();
  const [active, setActive] = useState<string>(APPEARANCE_KEY);
  const [filter, setFilter] = useState('');
  const [reloading, setReloading] = useState(false);
  const [reloadMsg, setReloadMsg] = useState<string | null>(null);

  useEffect(() => {
    if (loadState === 'idle') void hydrate();
  }, [loadState, hydrate]);

  const handleReload = async () => {
    if (reloading) return;
    setReloading(true);
    setReloadMsg(null);
    try {
      await reloadFromDisk();
      // `lastReloadChangedCount` is refreshed by the store. Read it fresh.
      const count = useConfigStore.getState().lastReloadChangedCount ?? 0;
      setReloadMsg(
        count === 0
          ? 'Reloaded — no changes detected on disk.'
          : `Reloaded — ${count} key${count === 1 ? '' : 's'} changed on disk.`,
      );
    } catch (exc) {
      setReloadMsg(
        `Reload failed: ${exc instanceof Error ? exc.message : String(exc)}`,
      );
    } finally {
      setReloading(false);
      setTimeout(() => setReloadMsg(null), 4000);
    }
  };

  const sectionKeys = useMemo(() => {
    if (!schema) return [] as string[];
    const known = new Set(Object.keys(schema.sections));
    const ordered = SECTION_ORDER.filter((s) => known.has(s));
    const extra = [...known].filter((s) => !ordered.includes(s)).sort();
    return [...ordered, ...extra];
  }, [schema]);

  const filteredSectionKeys = useMemo(() => {
    if (!filter.trim()) return sectionKeys;
    const q = filter.toLowerCase();
    return sectionKeys.filter((k) => {
      const title = schema?.sections[k]?.title ?? k;
      return k.toLowerCase().includes(q) || title.toLowerCase().includes(q);
    });
  }, [sectionKeys, schema, filter]);

  return (
    <div className="flex h-full">
      <aside
        className="w-64 shrink-0 flex flex-col border-r"
        style={{
          background: 'var(--color-surface)',
          borderColor: 'var(--color-border)',
        }}
      >
        <div
          className="p-3 border-b"
          style={{ borderColor: 'var(--color-border)' }}
        >
          <h1
            className="text-sm font-semibold"
            style={{ color: 'var(--color-text)' }}
          >
            Settings
          </h1>
          <input
            type="text"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filter…"
            className="w-full mt-2 px-2 py-1 rounded text-xs"
            style={{
              background: 'var(--color-bg)',
              border: '1px solid var(--color-border)',
              color: 'var(--color-text)',
            }}
          />
        </div>
        <nav className="flex-1 overflow-y-auto py-2">
          <SidebarItem
            label="Appearance"
            active={active === APPEARANCE_KEY}
            onClick={() => setActive(APPEARANCE_KEY)}
          />
          <div
            className="px-3 pt-3 pb-1 text-[10px] uppercase tracking-wide"
            style={{ color: 'var(--color-text-tertiary)' }}
          >
            Backend
          </div>
          {filteredSectionKeys.map((key) => (
            <SidebarItem
              key={key}
              label={schema?.sections[key]?.title ?? key}
              active={active === key}
              onClick={() => setActive(key)}
            />
          ))}
        </nav>
        <footer
          className="p-3 border-t flex flex-col gap-2"
          style={{ borderColor: 'var(--color-border)' }}
        >
          <button
            type="button"
            onClick={() => void handleReload()}
            disabled={reloading}
            title="Re-read config.toml from disk. Useful if you edited the file by hand or via `jarvis config set` in another shell."
            className="text-xs px-2 py-1 rounded flex items-center justify-center gap-1 disabled:opacity-60"
            style={{
              background: 'var(--color-bg)',
              border: '1px solid var(--color-border)',
              color: 'var(--color-text-secondary)',
            }}
          >
            <RefreshCw
              className={`h-3 w-3 ${reloading ? 'animate-spin' : ''}`}
            />
            {reloading ? 'Reloading…' : 'Reload from disk'}
          </button>
          {reloadMsg && (
            <div
              className="text-[11px] text-center"
              style={{ color: 'var(--color-text-tertiary)' }}
            >
              {reloadMsg}
            </div>
          )}
        </footer>
      </aside>

      <main className="flex-1 overflow-y-auto">
        <div className="max-w-3xl mx-auto p-6 space-y-4">
          <IntroHelp />
          <RestartBanner />
          {active === APPEARANCE_KEY ? (
            <AppearancePane />
          ) : (
            <BackendSectionPane
              sectionKey={active}
              loadState={loadState}
              error={error}
              config={config}
              schema={schema}
              onPatch={patch}
              onResetSection={resetSection}
            />
          )}
        </div>
      </main>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Intro help callout
// ---------------------------------------------------------------------------

function IntroHelp() {
  const [open, setOpen] = useState(false);
  return (
    <div
      className="rounded-lg text-xs"
      style={{
        background: 'var(--color-surface)',
        border: '1px solid var(--color-border)',
        color: 'var(--color-text-secondary)',
      }}
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-3 py-2 text-left"
        style={{ color: 'var(--color-text)' }}
      >
        <HelpCircle className="h-3.5 w-3.5 shrink-0" />
        <span className="flex-1 font-medium">
          How this page works
        </span>
        <span
          className="text-[10px]"
          style={{ color: 'var(--color-text-tertiary)' }}
        >
          {open ? 'Hide' : 'Show'}
        </span>
      </button>
      {open && (
        <div
          className="px-3 pb-3 space-y-2 leading-relaxed"
          style={{ borderTop: '1px solid var(--color-border-subtle)' }}
        >
          <p className="pt-2">
            <strong>Appearance</strong> is UI-only and saved in your browser.
            Every other section is persisted to{' '}
            <code>.openJarvis/config.toml</code> by the backend — the same
            file you'd edit by hand or via <code>jarvis config set</code>.
            OpenJarvis stores all of its data (DBs, audit logs, credentials,
            skills, …) in this project-local <code>.openJarvis/</code>
            folder, never in your home directory.
          </p>
          <p>
            Changes are validated against the backend dataclass schema.
            Most of them are applied immediately; changes to the engine,
            server, or security middleware require a restart and are
            flagged with a banner at the top of this page.
          </p>
          <p>
            Secrets (API keys, tokens, passwords) are never sent to the
            browser: you'll see <code>••••••••</code> once a value is
            stored. Use <em>Change</em> to replace it, <em>Clear</em> to
            remove it.
          </p>
          <p>
            If you edit <code>.openJarvis/config.toml</code> from another
            shell, click <strong>Reload from disk</strong> in the sidebar to
            pick up the change without restarting the browser.
          </p>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sidebar
// ---------------------------------------------------------------------------

function SidebarItem({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="w-full text-left px-3 py-1.5 text-xs"
      style={{
        background: active ? 'var(--color-bg-tertiary)' : 'transparent',
        color: active ? 'var(--color-text)' : 'var(--color-text-secondary)',
        fontWeight: active ? 600 : 400,
      }}
    >
      {label}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Appearance (local-only)
// ---------------------------------------------------------------------------

const THEMES: { value: ThemeMode; label: string; icon: typeof Sun }[] = [
  { value: 'light', label: 'Light', icon: Sun },
  { value: 'dark', label: 'Dark', icon: Moon },
  { value: 'system', label: 'System', icon: Monitor },
];

function AppearancePane() {
  const settings = useAppStore((s) => s.settings);
  const updateSettings = useAppStore((s) => s.updateSettings);
  return (
    <section className="flex flex-col gap-4">
      <header>
        <h2
          className="text-lg font-semibold flex items-center gap-2"
          style={{ color: 'var(--color-text)' }}
        >
          <Palette className="h-4 w-4" />
          Appearance
        </h2>
        <p
          className="text-xs mt-0.5"
          style={{ color: 'var(--color-text-tertiary)' }}
        >
          UI-only preferences. Saved to browser storage, not the backend.
        </p>
      </header>

      <Row label="Theme">
        <div className="flex gap-1">
          {THEMES.map(({ value, label, icon: Icon }) => (
            <button
              key={value}
              type="button"
              onClick={() => updateSettings({ theme: value })}
              className="flex items-center gap-1 px-2 py-1 rounded text-xs"
              style={{
                background:
                  settings.theme === value
                    ? 'var(--color-accent)'
                    : 'var(--color-bg)',
                color:
                  settings.theme === value
                    ? 'var(--color-accent-fg, white)'
                    : 'var(--color-text-secondary)',
                border: '1px solid var(--color-border)',
              }}
            >
              <Icon className="h-3 w-3" />
              {label}
            </button>
          ))}
        </div>
      </Row>

      <Row label="Font size">
        <select
          value={settings.fontSize}
          onChange={(e) =>
            updateSettings({
              fontSize: e.target.value as 'small' | 'default' | 'large',
            })
          }
          className="px-2 py-1 rounded text-xs"
          style={{
            background: 'var(--color-bg)',
            border: '1px solid var(--color-border)',
            color: 'var(--color-text)',
          }}
        >
          <option value="small">Small</option>
          <option value="default">Default</option>
          <option value="large">Large</option>
        </select>
      </Row>

      <Row label="API URL" description="Leave empty to use the default.">
        <input
          type="text"
          value={settings.apiUrl}
          onChange={(e) => updateSettings({ apiUrl: e.target.value })}
          placeholder="http://localhost:8000"
          className="w-64 px-2 py-1 rounded text-xs font-mono"
          style={{
            background: 'var(--color-bg)',
            border: '1px solid var(--color-border)',
            color: 'var(--color-text)',
          }}
        />
      </Row>
    </section>
  );
}

function Row({
  label,
  description,
  children,
}: {
  label: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <div
      className="flex items-center justify-between py-2"
      style={{ borderBottom: '1px solid var(--color-border-subtle)' }}
    >
      <div>
        <div className="text-sm" style={{ color: 'var(--color-text)' }}>
          {label}
        </div>
        {description && (
          <div
            className="text-xs mt-0.5"
            style={{ color: 'var(--color-text-tertiary)' }}
          >
            {description}
          </div>
        )}
      </div>
      <div>{children}</div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Backend section
// ---------------------------------------------------------------------------

// Short helper descriptions keyed by section name.  Rendered above the form.
// Keep these to one or two sentences — the full docs live in mkdocs.
const SECTION_HELP: Record<string, string> = {
  engine:
    'Which local inference runtime to talk to (ollama, vllm, mlx, …). Changing the engine requires a restart.',
  intelligence:
    'The default model and generation parameters (temperature, max tokens, top-p).',
  agent:
    'Agent harness: which agent to run by default, how many turns, system prompt.',
  tools:
    'Memory backend, MCP servers, browser automation, and the default set of tools agents can call.',
  channel:
    'Inbound messaging integrations (Telegram, Slack, Discord, Email, …). Each sub-section holds credentials for one transport.',
  speech:
    'Speech-to-text backend and model used for voice input.',
  security:
    'Guardrails, PII/secret scanners, SSRF protection, rate limits. "block" refuses unsafe calls, "redact" masks them, "warn" only logs.',
  telemetry:
    'Persisted run metrics (latency, tokens, GPU utilisation). Disable for maximum privacy.',
  traces:
    'Full request/response traces used by learning, evaluation, and debugging.',
  scheduler:
    'Cron-style job runner that fires scheduled agents and workflows.',
  workflow:
    'Multi-step graph runner for composing agents and tools.',
  sessions:
    'Cross-channel conversation memory — how long to keep sessions around and when to consolidate.',
  skills:
    'Procedural skills (shell-level recipes) that agents can author and replay.',
  digest:
    'Morning digest: what to summarise, when, and which voice to speak it in.',
  sandbox:
    'Containerised code execution for untrusted tools (Docker / Podman / WASM).',
  learning:
    'Trace-driven policy optimisation. Turn on individual learners (routing, SFT/GRPO, DSPy/GEPA) as needed.',
  optimize:
    'Auto-tune configuration with benchmarks. Runs a small meta-optimiser over the config surface.',
  a2a: 'Agent-to-Agent protocol: expose this OpenJarvis as an A2A server.',
  operators:
    'Long-running operator manifests — background agents with their own memory and tools.',
  agent_manager: 'Persistent, user-authored agents (saved in a local SQLite DB).',
  memory_files:
    'Paths to SOUL / MEMORY / USER markdown files that persist long-term context.',
  system_prompt: 'How the final system prompt is assembled and truncated.',
  compression: 'Context-window compression strategy and threshold.',
  server:
    'HTTP API host, port, workers, and CORS origins. Most fields require a restart to take effect.',
  hardware:
    'Auto-detected hardware info. Read-only; OpenJarvis uses this to recommend engines and models.',
};

interface BackendSectionPaneProps {
  sectionKey: string;
  loadState: 'idle' | 'loading' | 'ready' | 'error';
  error: string | null;
  config: ConfigDict | null;
  schema: ConfigSchema | null;
  onPatch: (patch: Record<string, ConfigValue>) => Promise<void>;
  onResetSection: (section: string) => Promise<void>;
}

function BackendSectionPane({
  sectionKey,
  loadState,
  error,
  config,
  schema,
  onPatch,
  onResetSection,
}: BackendSectionPaneProps) {
  if (loadState === 'loading' || loadState === 'idle') {
    return (
      <div
        className="text-xs"
        style={{ color: 'var(--color-text-tertiary)' }}
      >
        Loading configuration…
      </div>
    );
  }
  if (loadState === 'error') {
    return (
      <div
        className="rounded p-3 text-xs"
        style={{
          background: 'var(--color-error-bg, #fee2e2)',
          color: 'var(--color-error-fg, #991b1b)',
        }}
      >
        Failed to load configuration: {error}
      </div>
    );
  }
  if (!config || !schema) return null;

  const section = schema.sections[sectionKey];
  if (!section) {
    return (
      <div
        className="text-xs"
        style={{ color: 'var(--color-text-tertiary)' }}
      >
        Unknown section: {sectionKey}
      </div>
    );
  }

  const help = SECTION_HELP[sectionKey];

  return (
    <div className="flex flex-col gap-3">
      {help && (
        <div
          className="rounded flex items-start gap-2 px-3 py-2 text-xs"
          style={{
            background: 'var(--color-bg-tertiary)',
            color: 'var(--color-text-secondary)',
          }}
        >
          <Info
            className="h-3.5 w-3.5 shrink-0 mt-0.5"
            style={{ color: 'var(--color-text-tertiary)' }}
          />
          <div>
            <p>{help}</p>
            <p
              className="mt-1 text-[10px]"
              style={{ color: 'var(--color-text-tertiary)' }}
            >
              Persisted to{' '}
              <code>.openJarvis/config.toml</code> under{' '}
              <code>[{sectionKey}]</code>.
            </p>
          </div>
        </div>
      )}
      <ConfigForm
        sectionKey={sectionKey}
        section={section}
        config={config}
        onPatch={onPatch}
        onResetSection={() => onResetSection(sectionKey)}
      />
    </div>
  );
}
