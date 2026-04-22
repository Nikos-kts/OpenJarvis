/**
 * DelegationTimeline — recent sub-agent delegations with status pills.
 *
 * Running delegations get an Abort button that POSTs to
 * `/v1/jarvis/delegations/{id}/abort`.  The backend performs a
 * best-effort cancel (marks the record aborted); the UI refreshes via
 * the usual `jarvis_delegation_*` SSE event.
 */

import { Ban, CheckCircle2, Clock, Loader2, XCircle } from 'lucide-react';
import { motion } from 'motion/react';
import { useState } from 'react';
import { DelegationRecord, abortJarvisDelegation } from '../../lib/jarvis-api';

const STATUS: Record<
    DelegationRecord['status'],
    { color: string; icon: React.ReactNode; label: string }
> = {
    running: { color: '#f59e0b', icon: <Loader2 size={11} className="animate-spin" />, label: 'running' },
    completed: { color: '#22d3ee', icon: <CheckCircle2 size={11} />, label: 'done' },
    failed: { color: '#ef4444', icon: <XCircle size={11} />, label: 'failed' },
    aborted: { color: '#6b7280', icon: <XCircle size={11} />, label: 'aborted' },
};

export function DelegationTimeline({ records }: { records: DelegationRecord[] }) {
    const [aborting, setAborting] = useState<Set<string>>(new Set());

    async function handleAbort(id: string) {
        setAborting((prev) => {
            const next = new Set(prev);
            next.add(id);
            return next;
        });
        try {
            await abortJarvisDelegation(id);
        } catch {
            /* surface via stream or silent */
        } finally {
            setAborting((prev) => {
                const next = new Set(prev);
                next.delete(id);
                return next;
            });
        }
    }

    if (records.length === 0) {
        return (
            <div className="text-[11px] opacity-50 p-3 text-center" style={{ color: '#22d3ee' }}>
                no delegations yet
            </div>
        );
    }

    return (
        <ul className="flex flex-col gap-1.5 h-full min-h-0 overflow-y-auto pr-1">
            {records.map((r) => {
                const s = STATUS[r.status];
                return (
                    <motion.li
                        key={r.id}
                        initial={{ opacity: 0, x: -8 }}
                        animate={{ opacity: 1, x: 0 }}
                        className="flex flex-col gap-0.5 px-2.5 py-1.5 rounded"
                        style={{ border: `1px solid ${s.color}33`, background: `${s.color}0a` }}
                    >
                        <div className="flex items-center justify-between">
                            <div className="flex items-center gap-1.5 text-xs">
                                <span style={{ color: s.color }}>{s.icon}</span>
                                <span className="font-mono" style={{ color: '#e6fcff' }}>
                                    {r.sub_agent}
                                </span>
                                <span
                                    className="text-[9px] uppercase tracking-widest px-1 rounded"
                                    style={{ background: `${s.color}22`, color: s.color }}
                                >
                                    {r.mode}
                                </span>
                            </div>
                            <span className="flex items-center gap-1 text-[9px]" style={{ color: '#a4d5e0aa' }}>
                                <Clock size={9} />
                                {r.latency_ms > 0 ? `${r.latency_ms}ms` : s.label}
                                {r.status === 'running' && (
                                    <button
                                        onClick={() => handleAbort(r.id)}
                                        disabled={aborting.has(r.id)}
                                        className="ml-1 flex items-center gap-0.5 px-1.5 py-0.5 rounded cursor-pointer transition-colors disabled:opacity-40"
                                        style={{
                                            border: '1px solid #ef444455',
                                            color: '#ef4444',
                                            background: '#ef44440a',
                                        }}
                                        title="Abort delegation"
                                    >
                                        <Ban size={9} />
                                        abort
                                    </button>
                                )}
                            </span>
                        </div>
                        <div className="text-[10px] truncate" style={{ color: '#a4d5e0aa' }} title={r.brief}>
                            {r.brief}
                        </div>
                    </motion.li>
                );
            })}
        </ul>
    );
}
