/**
 * Schema-driven configuration form.
 *
 * Renders every field described by a section of the `/v1/config/schema`
 * response.  Primitive types (string/number/boolean) render as inputs;
 * nested objects recurse under a collapsible header; secret fields use a
 * password input with "set new value" semantics (an untouched field is
 * sent back as the `MASKED_PLACEHOLDER` sentinel which the backend
 * ignores).  Advanced fields are collapsed by default.
 */
import { HelpCircle } from 'lucide-react';
import { useMemo, useState } from 'react';
import type {
    ConfigDict,
    ConfigFieldSchema,
    ConfigSectionSchema,
    ConfigValue,
} from '../../lib/configApi';
import { MASKED_PLACEHOLDER, getByPath } from '../../lib/configApi';
import { getFieldHint } from '../../lib/configFieldHints';

interface ConfigFormProps {
    sectionKey: string;
    section: ConfigSectionSchema;
    config: ConfigDict;
    onPatch: (patch: Record<string, ConfigValue>) => Promise<void>;
    onResetSection?: () => Promise<void>;
}

export function ConfigForm({
    sectionKey,
    section,
    config,
    onPatch,
    onResetSection,
}: ConfigFormProps) {
    const [showAdvanced, setShowAdvanced] = useState(false);
    const [dirty, setDirty] = useState<Record<string, ConfigValue>>({});
    const [saving, setSaving] = useState(false);
    const [savedAt, setSavedAt] = useState<number | null>(null);

    const currentValue = (dotted: string): ConfigValue | undefined => {
        if (dotted in dirty) return dirty[dotted];
        return getByPath(config, dotted);
    };

    const markDirty = (dotted: string, value: ConfigValue) => {
        setDirty((d) => ({ ...d, [dotted]: value }));
    };

    const save = async () => {
        if (Object.keys(dirty).length === 0) return;
        setSaving(true);
        try {
            await onPatch(dirty);
            setDirty({});
            setSavedAt(Date.now());
            setTimeout(() => setSavedAt(null), 2000);
        } finally {
            setSaving(false);
        }
    };

    const discard = () => setDirty({});

    const hasAdvanced = useMemo(
        () => findAdvanced(section.properties),
        [section.properties],
    );

    return (
        <div className="flex flex-col gap-4">
            <header className="flex items-center justify-between">
                <div>
                    <h2
                        className="text-lg font-semibold"
                        style={{ color: 'var(--color-text)' }}
                    >
                        {section.title}
                    </h2>
                    {section.readonly && (
                        <p
                            className="text-xs mt-0.5"
                            style={{ color: 'var(--color-text-tertiary)' }}
                        >
                            Read-only (auto-detected).
                        </p>
                    )}
                </div>
                <div className="flex items-center gap-2">
                    {onResetSection && !section.readonly && (
                        <button
                            type="button"
                            onClick={onResetSection}
                            className="text-xs px-2 py-1 rounded"
                            style={{
                                background: 'var(--color-bg)',
                                border: '1px solid var(--color-border)',
                                color: 'var(--color-text-secondary)',
                            }}
                        >
                            Reset section
                        </button>
                    )}
                    {hasAdvanced && (
                        <button
                            type="button"
                            onClick={() => setShowAdvanced((v) => !v)}
                            className="text-xs px-2 py-1 rounded"
                            style={{
                                background: 'var(--color-bg)',
                                border: '1px solid var(--color-border)',
                                color: 'var(--color-text-secondary)',
                            }}
                        >
                            {showAdvanced ? 'Hide advanced' : 'Show advanced'}
                        </button>
                    )}
                </div>
            </header>

            <div className="flex flex-col gap-2">
                {Object.entries(section.properties).map(([name, field]) => (
                    <FieldView
                        key={name}
                        name={name}
                        field={field}
                        parentPath={sectionKey}
                        readonly={Boolean(section.readonly)}
                        showAdvanced={showAdvanced}
                        currentValue={currentValue}
                        markDirty={markDirty}
                    />
                ))}
            </div>

            {Object.keys(dirty).length > 0 && (
                <footer
                    className="sticky bottom-0 flex items-center justify-between p-3 rounded-lg"
                    style={{
                        background: 'var(--color-surface)',
                        border: '1px solid var(--color-border)',
                    }}
                >
                    <span
                        className="text-xs"
                        style={{ color: 'var(--color-text-secondary)' }}
                    >
                        {Object.keys(dirty).length} unsaved change(s)
                    </span>
                    <div className="flex gap-2">
                        <button
                            type="button"
                            onClick={discard}
                            disabled={saving}
                            className="text-xs px-3 py-1.5 rounded"
                            style={{
                                background: 'var(--color-bg)',
                                border: '1px solid var(--color-border)',
                                color: 'var(--color-text-secondary)',
                            }}
                        >
                            Discard
                        </button>
                        <button
                            type="button"
                            onClick={save}
                            disabled={saving}
                            className="text-xs px-3 py-1.5 rounded font-medium"
                            style={{
                                background: 'var(--color-accent)',
                                color: 'var(--color-accent-fg, white)',
                            }}
                        >
                            {saving ? 'Saving…' : 'Save'}
                        </button>
                    </div>
                </footer>
            )}
            {savedAt && (
                <div
                    className="text-xs"
                    style={{ color: 'var(--color-success, #16a34a)' }}
                >
                    Saved.
                </div>
            )}
        </div>
    );
}

// ---------------------------------------------------------------------------
// Field renderer (recursive)
// ---------------------------------------------------------------------------

interface FieldViewProps {
    name: string;
    field: ConfigFieldSchema;
    parentPath: string;
    readonly: boolean;
    showAdvanced: boolean;
    currentValue: (dotted: string) => ConfigValue | undefined;
    markDirty: (dotted: string, value: ConfigValue) => void;
}

function FieldView({
    name,
    field,
    parentPath,
    readonly,
    showAdvanced,
    currentValue,
    markDirty,
}: FieldViewProps) {
    const dotted = `${parentPath}.${name}`;

    if (field.advanced && !showAdvanced) return null;

    // Nested dataclass → collapsible group.
    if (field.properties) {
        return (
            <NestedGroup
                title={humanise(name)}
                dotted={dotted}
                properties={field.properties}
                readonly={readonly}
                showAdvanced={showAdvanced}
                currentValue={currentValue}
                markDirty={markDirty}
            />
        );
    }

    const value = currentValue(dotted);
    const label = humanise(name);
    const hint = getFieldHint(dotted);

    return (
        <div
            className="flex items-start justify-between gap-4 py-2"
            style={{ borderBottom: '1px solid var(--color-border-subtle)' }}
        >
            <div className="min-w-0 flex-1">
                <div
                    className="text-sm font-mono flex items-center gap-1.5"
                    style={{ color: 'var(--color-text)' }}
                    title={dotted}
                >
                    <span className="truncate">{label}</span>
                    {hint && <HintIcon text={hint.text} scope={hint.scope} />}
                </div>
                <div
                    className="text-[11px] mt-0.5 flex flex-wrap items-center gap-2"
                    style={{ color: 'var(--color-text-tertiary)' }}
                >
                    <code>{dotted}</code>
                    {field.secret && <Tag label="secret" />}
                    {field.restart_required && <Tag label="restart required" tone="warn" />}
                    {field.advanced && <Tag label="advanced" />}
                </div>
            </div>
            <div className="shrink-0">
                <FieldInput
                    field={field}
                    value={value}
                    readonly={readonly}
                    onChange={(v) => markDirty(dotted, v)}
                />
            </div>
        </div>
    );
}

interface NestedGroupProps {
    title: string;
    dotted: string;
    properties: Record<string, ConfigFieldSchema>;
    readonly: boolean;
    showAdvanced: boolean;
    currentValue: (dotted: string) => ConfigValue | undefined;
    markDirty: (dotted: string, value: ConfigValue) => void;
}

function NestedGroup({
    title,
    dotted,
    properties,
    readonly,
    showAdvanced,
    currentValue,
    markDirty,
}: NestedGroupProps) {
    const [open, setOpen] = useState(false);
    // Hide groups whose every visible child is advanced when showAdvanced is off.
    const visible = Object.values(properties).some((f) => !f.advanced || showAdvanced);
    if (!visible) return null;

    return (
        <div
            className="rounded-lg"
            style={{ border: '1px solid var(--color-border)' }}
        >
            <button
                type="button"
                onClick={() => setOpen((v) => !v)}
                className="w-full flex items-center justify-between px-3 py-2 text-sm"
                style={{ color: 'var(--color-text)' }}
            >
                <span className="font-medium">{title}</span>
                <span
                    className="text-xs"
                    style={{ color: 'var(--color-text-tertiary)' }}
                >
                    {open ? '−' : '+'}
                </span>
            </button>
            {open && (
                <div className="px-3 pb-3 flex flex-col gap-2">
                    {Object.entries(properties).map(([n, f]) => (
                        <FieldView
                            key={n}
                            name={n}
                            field={f}
                            parentPath={dotted}
                            readonly={readonly}
                            showAdvanced={showAdvanced}
                            currentValue={currentValue}
                            markDirty={markDirty}
                        />
                    ))}
                </div>
            )}
        </div>
    );
}

// ---------------------------------------------------------------------------
// Primitive inputs
// ---------------------------------------------------------------------------

interface FieldInputProps {
    field: ConfigFieldSchema;
    value: ConfigValue | undefined;
    readonly: boolean;
    onChange: (v: ConfigValue) => void;
}

function FieldInput({ field, value, readonly, onChange }: FieldInputProps) {
    const style = {
        background: 'var(--color-bg)',
        border: '1px solid var(--color-border)',
        color: 'var(--color-text)',
    } as const;

    if (field.secret) {
        return (
            <SecretField
                value={(value as string) ?? ''}
                readonly={readonly}
                onChange={onChange}
            />
        );
    }

    if (field.type === 'boolean') {
        return (
            <input
                type="checkbox"
                checked={Boolean(value)}
                disabled={readonly}
                onChange={(e) => onChange(e.target.checked)}
            />
        );
    }

    if (field.type === 'integer' || field.type === 'number') {
        return (
            <input
                type="number"
                className="w-40 px-2 py-1 rounded text-xs font-mono"
                style={style}
                value={value === null || value === undefined ? '' : String(value)}
                disabled={readonly}
                step={field.type === 'integer' ? 1 : 'any'}
                onChange={(e) => {
                    const raw = e.target.value;
                    if (raw === '') return onChange(0);
                    const parsed = field.type === 'integer'
                        ? parseInt(raw, 10)
                        : parseFloat(raw);
                    if (!Number.isNaN(parsed)) onChange(parsed);
                }}
            />
        );
    }

    if (field.type === 'array') {
        const arr = Array.isArray(value) ? value : [];
        return (
            <input
                type="text"
                className="w-64 px-2 py-1 rounded text-xs font-mono"
                style={style}
                placeholder="comma,separated,values"
                value={arr.map((v) => String(v)).join(',')}
                disabled={readonly}
                onChange={(e) =>
                    onChange(
                        e.target.value
                            .split(',')
                            .map((v) => v.trim())
                            .filter(Boolean),
                    )
                }
            />
        );
    }

    // string / fallback
    return (
        <input
            type="text"
            className="w-64 px-2 py-1 rounded text-xs font-mono"
            style={style}
            value={(value as string) ?? ''}
            disabled={readonly}
            onChange={(e) => onChange(e.target.value)}
        />
    );
}

function SecretField({
    value,
    readonly,
    onChange,
}: {
    value: string;
    readonly: boolean;
    onChange: (v: ConfigValue) => void;
}) {
    const isMaskedSentinel = value === MASKED_PLACEHOLDER;
    const [editing, setEditing] = useState(false);
    const [draft, setDraft] = useState('');

    if (!editing && isMaskedSentinel) {
        return (
            <div className="flex items-center gap-2">
                <span
                    className="text-xs font-mono"
                    style={{ color: 'var(--color-text-tertiary)' }}
                >
                    ••••••••
                </span>
                <button
                    type="button"
                    disabled={readonly}
                    onClick={() => {
                        setEditing(true);
                        setDraft('');
                    }}
                    className="text-[11px] px-2 py-0.5 rounded"
                    style={{
                        background: 'var(--color-bg)',
                        border: '1px solid var(--color-border)',
                        color: 'var(--color-text-secondary)',
                    }}
                >
                    Change
                </button>
                <button
                    type="button"
                    disabled={readonly}
                    onClick={() => onChange('')}
                    className="text-[11px] px-2 py-0.5 rounded"
                    style={{
                        background: 'var(--color-bg)',
                        border: '1px solid var(--color-border)',
                        color: 'var(--color-text-secondary)',
                    }}
                >
                    Clear
                </button>
            </div>
        );
    }

    return (
        <div className="flex items-center gap-2">
            <input
                type="password"
                className="w-64 px-2 py-1 rounded text-xs font-mono"
                style={{
                    background: 'var(--color-bg)',
                    border: '1px solid var(--color-border)',
                    color: 'var(--color-text)',
                }}
                value={editing ? draft : value}
                disabled={readonly}
                placeholder="(unset)"
                onChange={(e) => {
                    const v = e.target.value;
                    if (editing) setDraft(v);
                    onChange(v);
                }}
            />
            {editing && (
                <button
                    type="button"
                    onClick={() => {
                        setEditing(false);
                        setDraft('');
                        onChange(MASKED_PLACEHOLDER);
                    }}
                    className="text-[11px] px-2 py-0.5 rounded"
                    style={{
                        background: 'var(--color-bg)',
                        border: '1px solid var(--color-border)',
                        color: 'var(--color-text-secondary)',
                    }}
                >
                    Cancel
                </button>
            )}
        </div>
    );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function HintIcon({ text, scope }: { text: string; scope?: string }) {
    // Hover-card pattern: native `title` gives keyboard-free baseline, and
    // a Tailwind `group-hover` popover provides rich styling with the scope
    // badge.  Pointer-events are disabled so the popover doesn't block
    // clicks on adjacent inputs.
    return (
        <span className="relative inline-flex group" tabIndex={0}>
            <HelpCircle
                className="h-3.5 w-3.5 cursor-help shrink-0"
                style={{ color: 'var(--color-text-tertiary)' }}
                aria-label={text}
            />
            <span
                className="pointer-events-none absolute left-5 top-1/2 -translate-y-1/2 z-20 w-72 rounded-md p-2 text-[11px] leading-snug opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 transition-opacity shadow-lg"
                style={{
                    background: 'var(--color-surface)',
                    border: '1px solid var(--color-border)',
                    color: 'var(--color-text-secondary)',
                }}
                role="tooltip"
            >
                <span className="block">{text}</span>
                {scope && (
                    <span
                        className="mt-1 inline-block text-[10px] px-1.5 py-0.5 rounded uppercase tracking-wide"
                        style={{
                            background: 'var(--color-bg-tertiary)',
                            color: 'var(--color-text-tertiary)',
                        }}
                    >
                        {scope}
                    </span>
                )}
            </span>
        </span>
    );
}

function Tag({ label, tone }: { label: string; tone?: 'warn' }) {
    const bg = tone === 'warn' ? 'var(--color-warn-bg, #fef3c7)' : 'var(--color-bg-tertiary)';
    const fg = tone === 'warn' ? 'var(--color-warn-fg, #92400e)' : 'var(--color-text-tertiary)';
    return (
        <span
            className="text-[10px] px-1.5 py-0.5 rounded uppercase tracking-wide"
            style={{ background: bg, color: fg }}
        >
            {label}
        </span>
    );
}

function humanise(name: string): string {
    return name
        .replace(/_/g, ' ')
        .replace(/\b\w/g, (c) => c.toUpperCase());
}

function findAdvanced(props: Record<string, ConfigFieldSchema>): boolean {
    for (const f of Object.values(props)) {
        if (f.advanced) return true;
        if (f.properties && findAdvanced(f.properties)) return true;
    }
    return false;
}
