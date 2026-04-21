import { Loader2, RotateCcw, X } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import {
    patchJarvisPrimaryConfig,
    resetJarvisPrimaryConfig,
    updateWakeMode,
    type JarvisPrimaryConfig,
    type JarvisPrimaryRecord,
} from '../../lib/api';
import { syncJarvisConfigToSettings } from '../../lib/jarvisSync';

export type TabKey = 'persona' | 'intent' | 'voice' | 'wake' | 'tools' | 'delegation' | 'advanced';

const TABS: { key: TabKey; label: string }[] = [
    { key: 'persona', label: 'Persona' },
    { key: 'intent', label: 'Intent' },
    { key: 'voice', label: 'Voice' },
    { key: 'wake', label: 'Wake' },
    { key: 'tools', label: 'Tools' },
    { key: 'delegation', label: 'Delegation' },
    { key: 'advanced', label: 'Advanced' },
];

interface Props {
    agent: JarvisPrimaryRecord;
    onClose: () => void;
    onUpdated: (next: JarvisPrimaryConfig) => void;
    initialTab?: TabKey;
}

export function JarvisSettingsDrawer({ agent, onClose, onUpdated, initialTab }: Props) {
    const [draft, setDraft] = useState<JarvisPrimaryConfig>(agent.config || {});
    const [active, setActive] = useState<TabKey>(initialTab ?? 'persona');
    const [saving, setSaving] = useState(false);
    const [resetting, setResetting] = useState(false);

    useEffect(() => {
        setDraft(agent.config || {});
    }, [agent.id]);

    const dirty = useMemo(() => {
        return JSON.stringify(draft) !== JSON.stringify(agent.config || {});
    }, [draft, agent.config]);

    const patch = <K extends keyof JarvisPrimaryConfig>(
        key: K,
        value: JarvisPrimaryConfig[K],
    ) => setDraft((d) => ({ ...d, [key]: value }));

    const patchNested = (
        key: 'persona' | 'intent' | 'voice' | 'wake' | 'delegation',
        patchObj: Record<string, unknown>,
    ) =>
        setDraft((d) => ({
            ...d,
            [key]: { ...(d[key] as object | undefined), ...patchObj },
        }));

    const save = async () => {
        setSaving(true);
        try {
            const res = await patchJarvisPrimaryConfig(draft);
            onUpdated(res.config);
            setDraft(res.config);
            // Mirror voice/wake into the legacy settings store (used by VoicePanel)
            // and push wake changes to the clap-boot runtime daemon.
            syncJarvisConfigToSettings(res.config, agent.config);
            const prevWake = (agent.config?.wake ?? {}) as Record<string, unknown>;
            const nextWake = (res.config?.wake ?? {}) as Record<string, unknown>;
            if (
                prevWake.enabled !== nextWake.enabled ||
                prevWake.mode !== nextWake.mode
            ) {
                const runtimeMode = nextWake.enabled === false ? 'off' : (nextWake.mode as string) || 'off';
                const mapped = runtimeMode === 'wakeword' ? 'auto' : runtimeMode;
                updateWakeMode(mapped).catch(() => { /* runtime sync is best-effort */ });
            }
            toast.success('Jarvis updated');
        } catch (e) {
            toast.error('Failed to save', { description: String(e) });
        } finally {
            setSaving(false);
        }
    };

    const reset = async () => {
        if (!confirm('Reset Jarvis configuration to defaults?')) return;
        setResetting(true);
        try {
            const res = await resetJarvisPrimaryConfig();
            onUpdated(res.config);
            setDraft(res.config);
            syncJarvisConfigToSettings(res.config, agent.config);
            toast.success('Jarvis reset to defaults');
        } catch (e) {
            toast.error('Failed to reset', { description: String(e) });
        } finally {
            setResetting(false);
        }
    };

    return (
        <div
            className="fixed inset-0 z-50 flex justify-end"
            style={{ background: 'rgba(0,0,0,0.55)' }}
            onClick={onClose}
        >
            <div
                className="h-full w-full max-w-xl flex flex-col shadow-2xl"
                style={{
                    background: 'var(--color-bg)',
                    borderLeft: '1px solid var(--color-border)',
                }}
                onClick={(e) => e.stopPropagation()}
            >
                {/* Header */}
                <div
                    className="flex items-center justify-between px-4 py-3 shrink-0"
                    style={{ borderBottom: '1px solid var(--color-border)' }}
                >
                    <div>
                        <div className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>
                            Jarvis settings
                        </div>
                        <div className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                            {agent.name} · {agent.id.slice(0, 8)}
                        </div>
                    </div>
                    <button
                        onClick={onClose}
                        className="p-1.5 rounded cursor-pointer"
                        style={{ color: 'var(--color-text-secondary)' }}
                        title="Close"
                    >
                        <X size={16} />
                    </button>
                </div>

                {/* Tabs */}
                <div
                    className="flex items-center gap-1 px-3 py-2 shrink-0 overflow-x-auto"
                    style={{ borderBottom: '1px solid var(--color-border)' }}
                >
                    {TABS.map((t) => (
                        <button
                            key={t.key}
                            onClick={() => setActive(t.key)}
                            className="px-3 py-1.5 rounded-md text-xs transition-colors cursor-pointer whitespace-nowrap"
                            style={{
                                background:
                                    active === t.key
                                        ? 'var(--color-accent-subtle)'
                                        : 'transparent',
                                color:
                                    active === t.key
                                        ? 'var(--color-accent)'
                                        : 'var(--color-text-secondary)',
                            }}
                        >
                            {t.label}
                        </button>
                    ))}
                </div>

                {/* Body */}
                <div className="flex-1 overflow-y-auto px-4 py-4">
                    {active === 'persona' && (
                        <PersonaTab draft={draft} patch={patch} patchNested={patchNested} />
                    )}
                    {active === 'intent' && <IntentTab draft={draft} patchNested={patchNested} />}
                    {active === 'voice' && <VoiceTab draft={draft} patchNested={patchNested} />}
                    {active === 'wake' && <WakeTab draft={draft} patchNested={patchNested} />}
                    {active === 'tools' && <ToolsTab draft={draft} patch={patch} />}
                    {active === 'delegation' && (
                        <DelegationTab draft={draft} patch={patch} patchNested={patchNested} />
                    )}
                    {active === 'advanced' && <AdvancedTab draft={draft} patch={patch} />}
                </div>

                {/* Footer */}
                <div
                    className="flex items-center justify-between px-4 py-3 shrink-0 gap-2"
                    style={{ borderTop: '1px solid var(--color-border)' }}
                >
                    <button
                        onClick={reset}
                        disabled={resetting}
                        className="px-3 py-1.5 rounded-md text-xs flex items-center gap-1.5 cursor-pointer disabled:opacity-40"
                        style={{
                            color: 'var(--color-text-secondary)',
                            background: 'transparent',
                            border: '1px solid var(--color-border)',
                        }}
                    >
                        {resetting ? <Loader2 size={12} className="animate-spin" /> : <RotateCcw size={12} />}
                        Reset to defaults
                    </button>
                    <div className="flex items-center gap-2">
                        <button
                            onClick={onClose}
                            className="px-3 py-1.5 rounded-md text-xs cursor-pointer"
                            style={{
                                color: 'var(--color-text-secondary)',
                                border: '1px solid var(--color-border)',
                            }}
                        >
                            Cancel
                        </button>
                        <button
                            onClick={save}
                            disabled={!dirty || saving}
                            className="px-3 py-1.5 rounded-md text-xs cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-1.5"
                            style={{
                                background: 'var(--color-accent)',
                                color: 'var(--color-bg)',
                            }}
                        >
                            {saving && <Loader2 size={12} className="animate-spin" />}
                            Save changes
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
}

// ---------------------------------------------------------------------------
// Shared primitives
// ---------------------------------------------------------------------------

function Field({
    label,
    hint,
    children,
}: {
    label: string;
    hint?: string;
    children: React.ReactNode;
}) {
    return (
        <label className="flex flex-col gap-1.5 mb-4">
            <span className="text-xs font-medium" style={{ color: 'var(--color-text)' }}>
                {label}
            </span>
            {children}
            {hint && (
                <span className="text-[11px]" style={{ color: 'var(--color-text-tertiary)' }}>
                    {hint}
                </span>
            )}
        </label>
    );
}

function TextInput({
    value,
    onChange,
    placeholder,
    type = 'text',
}: {
    value: string | number | undefined;
    onChange: (v: string) => void;
    placeholder?: string;
    type?: string;
}) {
    return (
        <input
            type={type}
            value={value ?? ''}
            onChange={(e) => onChange(e.target.value)}
            placeholder={placeholder}
            className="px-2.5 py-1.5 rounded-md text-xs outline-none"
            style={{
                background: 'var(--color-bg-secondary)',
                color: 'var(--color-text)',
                border: '1px solid var(--color-border)',
            }}
        />
    );
}

function TextArea({
    value,
    onChange,
    placeholder,
    rows = 4,
}: {
    value: string | undefined;
    onChange: (v: string) => void;
    placeholder?: string;
    rows?: number;
}) {
    return (
        <textarea
            value={value ?? ''}
            onChange={(e) => onChange(e.target.value)}
            placeholder={placeholder}
            rows={rows}
            className="px-2.5 py-1.5 rounded-md text-xs outline-none font-mono resize-y"
            style={{
                background: 'var(--color-bg-secondary)',
                color: 'var(--color-text)',
                border: '1px solid var(--color-border)',
            }}
        />
    );
}

function SelectInput<T extends string>({
    value,
    onChange,
    options,
}: {
    value: T | undefined;
    onChange: (v: T) => void;
    options: { value: T; label: string }[];
}) {
    return (
        <select
            value={value ?? ''}
            onChange={(e) => onChange(e.target.value as T)}
            className="px-2.5 py-1.5 rounded-md text-xs outline-none cursor-pointer"
            style={{
                background: 'var(--color-bg-secondary)',
                color: 'var(--color-text)',
                border: '1px solid var(--color-border)',
            }}
        >
            {options.map((o) => (
                <option key={o.value} value={o.value}>
                    {o.label}
                </option>
            ))}
        </select>
    );
}

function Toggle({
    checked,
    onChange,
    label,
    hint,
}: {
    checked: boolean;
    onChange: (v: boolean) => void;
    label: string;
    hint?: string;
}) {
    return (
        <div
            className="flex items-center justify-between gap-3 py-2.5 px-3 rounded-md mb-3"
            style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
        >
            <div className="flex flex-col min-w-0">
                <span className="text-xs font-medium" style={{ color: 'var(--color-text)' }}>
                    {label}
                </span>
                {hint && (
                    <span className="text-[11px]" style={{ color: 'var(--color-text-tertiary)' }}>
                        {hint}
                    </span>
                )}
            </div>
            <button
                onClick={() => onChange(!checked)}
                className="w-9 h-5 rounded-full relative transition-colors cursor-pointer shrink-0"
                style={{
                    background: checked ? 'var(--color-accent)' : 'var(--color-bg-tertiary)',
                    border: '1px solid var(--color-border)',
                }}
            >
                <span
                    className="absolute top-0.5 w-3.5 h-3.5 rounded-full transition-all"
                    style={{
                        background: checked ? 'var(--color-bg)' : 'var(--color-text-tertiary)',
                        left: checked ? '18px' : '2px',
                    }}
                />
            </button>
        </div>
    );
}

// ---------------------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------------------

interface TabArgs {
    draft: JarvisPrimaryConfig;
    patch: <K extends keyof JarvisPrimaryConfig>(
        key: K,
        value: JarvisPrimaryConfig[K],
    ) => void;
    patchNested: (
        key: 'persona' | 'intent' | 'voice' | 'wake' | 'delegation',
        patchObj: Record<string, unknown>,
    ) => void;
}

function PersonaTab({ draft, patch, patchNested }: TabArgs) {
    const p = draft.persona ?? {};
    return (
        <div>
            <Field label="System prompt" hint="Overrides the built-in butler prompt when set.">
                <TextArea
                    value={draft.system_prompt}
                    onChange={(v) => patch('system_prompt', v)}
                    placeholder="Leave empty to use the built-in Jarvis butler persona."
                    rows={6}
                />
            </Field>
            <Field label="Tone">
                <TextInput
                    value={p.tone as string | undefined}
                    onChange={(v) => patchNested('persona', { tone: v })}
                    placeholder="e.g. witty_butler"
                />
            </Field>
            <Field label="Verbosity">
                <SelectInput
                    value={(p.verbosity as string | undefined) ?? 'balanced'}
                    onChange={(v) => patchNested('persona', { verbosity: v })}
                    options={[
                        { value: 'concise', label: 'Concise' },
                        { value: 'balanced', label: 'Balanced' },
                        { value: 'detailed', label: 'Detailed' },
                    ]}
                />
            </Field>
            <Field label="Proactive level">
                <SelectInput
                    value={(p.proactive_level as string | undefined) ?? 'medium'}
                    onChange={(v) => patchNested('persona', { proactive_level: v })}
                    options={[
                        { value: 'low', label: 'Low' },
                        { value: 'medium', label: 'Medium' },
                        { value: 'high', label: 'High' },
                    ]}
                />
            </Field>
            <Field label="Wake phrase (persona)" hint="Also mirrored to the Wake tab.">
                <TextInput
                    value={p.wake_phrase as string | undefined}
                    onChange={(v) => patchNested('persona', { wake_phrase: v })}
                    placeholder="Hey Jarvis"
                />
            </Field>
        </div>
    );
}

function IntentTab({
    draft,
    patchNested,
}: {
    draft: JarvisPrimaryConfig;
    patchNested: TabArgs['patchNested'];
}) {
    const i = draft.intent ?? {};
    return (
        <div>
            <Field label="Policy" hint="Controls how Jarvis routes between heuristics and LLM.">
                <SelectInput
                    value={(i.policy as string | undefined) ?? 'hybrid'}
                    onChange={(v) => patchNested('intent', { policy: v })}
                    options={[
                        { value: 'heuristic', label: 'Heuristic' },
                        { value: 'hybrid', label: 'Hybrid' },
                        { value: 'llm', label: 'LLM only' },
                    ]}
                />
            </Field>
            <Field label="Confidence threshold" hint="0 – 1">
                <TextInput
                    type="number"
                    value={i.confidence_threshold as number | undefined}
                    onChange={(v) =>
                        patchNested('intent', { confidence_threshold: parseFloat(v) || 0 })
                    }
                />
            </Field>
            <Field label="Max clarification rounds">
                <TextInput
                    type="number"
                    value={i.clarify_max_rounds as number | undefined}
                    onChange={(v) =>
                        patchNested('intent', { clarify_max_rounds: parseInt(v, 10) || 0 })
                    }
                />
            </Field>
        </div>
    );
}

function VoiceTab({
    draft,
    patchNested,
}: {
    draft: JarvisPrimaryConfig;
    patchNested: TabArgs['patchNested'];
}) {
    const v = draft.voice ?? {};
    return (
        <div>
            <Toggle
                label="Voice output"
                hint="Enable Jarvis to speak responses."
                checked={!!v.enabled}
                onChange={(val) => patchNested('voice', { enabled: val })}
            />
            <Toggle
                label="Realtime (live) mode"
                hint="Bidirectional streaming voice."
                checked={!!v.realtime}
                onChange={(val) => patchNested('voice', { realtime: val })}
            />
            <Field label="TTS voice">
                <TextInput
                    value={v.tts_voice as string | undefined}
                    onChange={(val) => patchNested('voice', { tts_voice: val })}
                    placeholder="e.g. Kore"
                />
            </Field>
            <Field label="Live model">
                <TextInput
                    value={v.live_model as string | undefined}
                    onChange={(val) => patchNested('voice', { live_model: val })}
                    placeholder="e.g. gemini-live-2.5-flash-preview"
                />
            </Field>
            <Field label="Silence timeout (seconds)">
                <TextInput
                    type="number"
                    value={v.silence_seconds as number | undefined}
                    onChange={(val) =>
                        patchNested('voice', { silence_seconds: parseFloat(val) || 0 })
                    }
                />
            </Field>
        </div>
    );
}

function WakeTab({
    draft,
    patchNested,
}: {
    draft: JarvisPrimaryConfig;
    patchNested: TabArgs['patchNested'];
}) {
    const w = draft.wake ?? {};
    return (
        <div>
            <Toggle
                label="Wake detection"
                hint="Listen for a wake trigger in the background."
                checked={!!w.enabled}
                onChange={(val) => patchNested('wake', { enabled: val })}
            />
            <Field label="Wake mode">
                <SelectInput
                    value={(w.mode as string | undefined) ?? 'clap'}
                    onChange={(val) => patchNested('wake', { mode: val })}
                    options={[
                        { value: 'off', label: 'Off' },
                        { value: 'clap', label: 'Clap detector' },
                        { value: 'wakeword', label: 'Wake word' },
                    ]}
                />
            </Field>
            <Field label="Wake phrase" hint="Used when mode is 'wakeword'.">
                <TextInput
                    value={w.phrase as string | undefined}
                    onChange={(val) => patchNested('wake', { phrase: val })}
                    placeholder="Hey Jarvis"
                />
            </Field>
        </div>
    );
}

function ToolsTab({
    draft,
    patch,
}: {
    draft: JarvisPrimaryConfig;
    patch: TabArgs['patch'];
}) {
    const list = draft.tools ?? [];
    const text = list.join('\n');
    return (
        <div>
            <Field
                label="Allowed tools"
                hint="One tool name per line. These are registered in the backend ToolRegistry."
            >
                <TextArea
                    value={text}
                    onChange={(v) =>
                        patch(
                            'tools',
                            v
                                .split('\n')
                                .map((x) => x.trim())
                                .filter(Boolean),
                        )
                    }
                    rows={10}
                    placeholder={'web_search\nfile_read\ncalculator\nthink\nlist_available_agents\ndelegate_to_agent'}
                />
            </Field>
        </div>
    );
}

function DelegationTab({
    draft,
    patch,
    patchNested,
}: TabArgs) {
    const d = draft.delegation ?? {};
    const visible =
        (d.visible_to_brain as boolean | undefined) ??
        (draft.visible_to_brain as boolean | undefined) ??
        false;
    const tags =
        (d.tags as string[] | undefined) ??
        (draft.delegation_tags as string[] | undefined) ??
        [];
    return (
        <div>
            <Toggle
                label="Visible to other Jarvis agents"
                hint="Primary Jarvis agents usually don't delegate to themselves, but other Brains can discover this one."
                checked={visible}
                onChange={(v) => {
                    patchNested('delegation', { visible_to_brain: v });
                    patch('visible_to_brain', v);
                }}
            />
            <Field
                label="Delegation tags"
                hint="Comma-separated tags. Surfaced to the delegating agent as metadata."
            >
                <TextInput
                    value={tags.join(', ')}
                    onChange={(v) => {
                        const arr = v
                            .split(',')
                            .map((x) => x.trim())
                            .filter(Boolean);
                        patchNested('delegation', { tags: arr });
                        patch('delegation_tags', arr);
                    }}
                    placeholder="primary, butler"
                />
            </Field>
        </div>
    );
}

function AdvancedTab({
    draft,
    patch,
}: {
    draft: JarvisPrimaryConfig;
    patch: TabArgs['patch'];
}) {
    return (
        <div>
            <Field label="Model">
                <TextInput
                    value={draft.model}
                    onChange={(v) => patch('model', v)}
                    placeholder="e.g. gpt-4o-mini"
                />
            </Field>
            <Field label="Preferred engine">
                <TextInput
                    value={draft.preferred_engine}
                    onChange={(v) => patch('preferred_engine', v)}
                    placeholder="e.g. openai"
                />
            </Field>
            <Field label="Description">
                <TextInput
                    value={draft.description}
                    onChange={(v) => patch('description', v)}
                    placeholder="Short description shown in the Jarvis header."
                />
            </Field>
            <Field label="Max turns">
                <TextInput
                    type="number"
                    value={draft.max_turns}
                    onChange={(v) => patch('max_turns', parseInt(v, 10) || 0)}
                />
            </Field>
            <Field label="Temperature">
                <TextInput
                    type="number"
                    value={draft.temperature}
                    onChange={(v) => patch('temperature', parseFloat(v) || 0)}
                />
            </Field>
            <Field label="Generation max tokens">
                <TextInput
                    type="number"
                    value={draft.generation_max_tokens}
                    onChange={(v) =>
                        patch('generation_max_tokens', parseInt(v, 10) || 0)
                    }
                />
            </Field>
        </div>
    );
}
