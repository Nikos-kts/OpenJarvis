/**
 * CapabilityDialog — modal surface used to configure Jarvis's active
 * Tools / Skills / Agents from a single pattern.
 *
 * Each row is a togglable capability with an optional ``meta`` string
 * (category, type, etc.).  All toggles round-trip to the backend via
 * the caller-supplied ``onToggle`` handler; optimistic UI is handled
 * by the caller.
 */

import { AlertTriangle, Power, PowerOff, Search, X } from 'lucide-react';
import { ReactNode, useMemo, useState } from 'react';

const ACCENT = '#22d3ee';
const WARN = '#f59e0b';

export interface CapabilityRow {
    key: string;
    label: string;
    description?: string;
    meta?: string;
    active: boolean;
    busy?: boolean;
    disabled?: boolean;
    warning?: string;
}

export function CapabilityDialog({
    open,
    title,
    subtitle,
    icon,
    rows,
    onToggle,
    onClose,
    empty,
}: {
    open: boolean;
    title: string;
    subtitle?: string;
    icon?: ReactNode;
    rows: CapabilityRow[];
    onToggle: (key: string) => void;
    onClose: () => void;
    empty?: string;
}) {
    const [query, setQuery] = useState('');

    const filtered = useMemo(() => {
        const q = query.trim().toLowerCase();
        if (!q) return rows;
        return rows.filter(
            (r) =>
                r.label.toLowerCase().includes(q) ||
                (r.description ?? '').toLowerCase().includes(q) ||
                (r.meta ?? '').toLowerCase().includes(q),
        );
    }, [rows, query]);

    const activeCount = rows.filter((r) => r.active).length;

    if (!open) return null;

    return (
        <div
            className="fixed inset-0 z-50 flex items-center justify-center p-6"
            style={{ background: 'rgba(2,8,14,0.78)', backdropFilter: 'blur(6px)' }}
            onClick={onClose}
        >
            <div
                onClick={(e) => e.stopPropagation()}
                className="relative flex flex-col w-full max-w-2xl max-h-[80vh] rounded-lg overflow-hidden"
                style={{
                    background: 'linear-gradient(180deg, rgba(12,22,32,0.97), rgba(6,12,20,0.97))',
                    border: `1px solid ${ACCENT}55`,
                    boxShadow: `0 0 0 1px ${ACCENT}22 inset, 0 0 42px ${ACCENT}22`,
                }}
            >
                {/* Header */}
                <div
                    className="flex items-center justify-between px-4 py-2.5"
                    style={{ borderBottom: `1px solid ${ACCENT}33` }}
                >
                    <div className="flex items-center gap-2">
                        {icon && <span style={{ color: `${ACCENT}cc` }}>{icon}</span>}
                        <div>
                            <div
                                className="text-[11px] uppercase tracking-[0.25em]"
                                style={{ color: `${ACCENT}cc` }}
                            >
                                {title}
                            </div>
                            {subtitle && (
                                <div className="text-[10px] opacity-70" style={{ color: '#a4d5e0' }}>
                                    {subtitle}
                                </div>
                            )}
                        </div>
                    </div>
                    <div className="flex items-center gap-2">
                        <span
                            className="font-mono text-[10px] px-2 py-0.5 rounded"
                            style={{ background: `${ACCENT}22`, color: '#e6fcff' }}
                        >
                            {activeCount}/{rows.length}
                        </span>
                        <button
                            onClick={onClose}
                            className="p-1 rounded cursor-pointer"
                            title="Close"
                            style={{
                                border: `1px solid ${ACCENT}33`,
                                color: `${ACCENT}cc`,
                                background: 'transparent',
                            }}
                        >
                            <X size={14} />
                        </button>
                    </div>
                </div>

                {/* Search */}
                <div className="px-4 py-2" style={{ borderBottom: `1px solid ${ACCENT}22` }}>
                    <div
                        className="flex items-center gap-1.5 px-2 py-1 rounded"
                        style={{ border: `1px solid ${ACCENT}33`, background: `${ACCENT}0a` }}
                    >
                        <Search size={12} style={{ color: `${ACCENT}aa` }} />
                        <input
                            autoFocus
                            value={query}
                            onChange={(e) => setQuery(e.target.value)}
                            placeholder="filter…"
                            className="flex-1 bg-transparent outline-none text-[12px]"
                            style={{ color: '#e6fcff' }}
                        />
                    </div>
                </div>

                {/* Rows */}
                <div className="flex-1 min-h-0 overflow-y-auto p-3">
                    {filtered.length === 0 ? (
                        <div
                            className="text-[11px] opacity-60 p-8 text-center"
                            style={{ color: ACCENT }}
                        >
                            {rows.length === 0 ? (empty ?? 'nothing available') : 'no matches'}
                        </div>
                    ) : (
                        <ul className="flex flex-col gap-1.5">
                            {filtered.map((r) => (
                                <CapabilityDialogRow
                                    key={r.key}
                                    row={r}
                                    onToggle={() => onToggle(r.key)}
                                />
                            ))}
                        </ul>
                    )}
                </div>
            </div>
        </div>
    );
}

function CapabilityDialogRow({
    row,
    onToggle,
}: {
    row: CapabilityRow;
    onToggle: () => void;
}) {
    const color = row.active ? ACCENT : '#64748b';
    return (
        <li
            className="flex items-center justify-between gap-3 px-3 py-2 rounded"
            style={{ border: `1px solid ${color}33`, background: `${color}08` }}
        >
            <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                    {row.warning && (
                        <span
                            title={row.warning}
                            className="shrink-0 flex items-center"
                            style={{ color: WARN }}
                        >
                            <AlertTriangle size={13} />
                        </span>
                    )}
                    <span
                        className="text-[13px] font-mono truncate"
                        style={{ color: row.active ? '#e6fcff' : '#a4d5e0aa' }}
                    >
                        {row.label}
                    </span>
                    {row.meta && (
                        <span
                            className="text-[9px] uppercase tracking-widest px-1.5 py-[1px] rounded shrink-0"
                            style={{ border: `1px solid ${color}55`, color: `${color}dd` }}
                        >
                            {row.meta}
                        </span>
                    )}
                </div>
                {row.description && (
                    <div
                        className="text-[11px] mt-0.5 opacity-80 leading-snug"
                        style={{ color: `${color}cc` }}
                    >
                        {row.description}
                    </div>
                )}
            </div>
            <button
                onClick={onToggle}
                disabled={row.busy || row.disabled}
                className="shrink-0 flex items-center gap-1 px-2 py-1 rounded cursor-pointer transition-colors disabled:opacity-40"
                style={{ border: `1px solid ${color}77`, color, background: 'transparent' }}
                title={row.active ? 'Disable' : 'Enable'}
            >
                {row.active ? <Power size={12} /> : <PowerOff size={12} />}
                <span className="text-[10px] uppercase tracking-widest">
                    {row.active ? 'on' : 'off'}
                </span>
            </button>
        </li>
    );
}
