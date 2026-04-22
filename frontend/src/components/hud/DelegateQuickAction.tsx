/**
 * DelegateQuickAction — HUD card + modal to hand a brief directly to
 * a sub-agent, bypassing Jarvis's own reasoning.
 *
 * This is the operator escape-hatch: if you already know exactly which
 * sub-agent should handle something, skip the chat and dispatch it.
 */

import { Send, X, Zap } from 'lucide-react';
import { AnimatePresence, motion } from 'motion/react';
import { useState } from 'react';
import { JarvisSubAgent, delegateManually } from '../../lib/jarvis-api';

type Mode = 'sync' | 'async';

export function DelegateQuickAction({ subAgents }: { subAgents: JarvisSubAgent[] }) {
    const accent = '#22d3ee';
    const [open, setOpen] = useState(false);
    const [agent, setAgent] = useState('');
    const [brief, setBrief] = useState('');
    const [mode, setMode] = useState<Mode>('async');
    const [busy, setBusy] = useState(false);
    const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);

    const hasAgents = subAgents.some((a) => a.name || a.id);

    async function handleSubmit() {
        if (!agent.trim() || !brief.trim()) return;
        setBusy(true);
        setResult(null);
        try {
            const res = await delegateManually({ agent: agent.trim(), brief: brief.trim(), mode });
            setResult({ ok: res.ok, text: res.content || '(no content returned)' });
            if (res.ok && mode === 'async') {
                // Async fires and forgets — close after a short confirmation.
                setTimeout(() => setOpen(false), 1200);
            }
        } catch (err) {
            setResult({ ok: false, text: err instanceof Error ? err.message : String(err) });
        } finally {
            setBusy(false);
        }
    }

    return (
        <>
            <button
                onClick={() => setOpen(true)}
                disabled={!hasAgents}
                className="flex items-center justify-center gap-1.5 w-full px-3 py-2 rounded cursor-pointer transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                style={{
                    border: `1px solid ${accent}66`,
                    background: `${accent}12`,
                    color: accent,
                }}
                title={hasAgents ? 'Dispatch a brief to a sub-agent' : 'No sub-agents available'}
            >
                <Zap size={12} />
                <span className="text-[10px] uppercase tracking-widest">Quick Delegate</span>
            </button>

            <AnimatePresence>
                {open && (
                    <motion.div
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        className="fixed inset-0 z-50 flex items-center justify-center p-4"
                        style={{ background: 'rgba(3, 6, 12, 0.8)', backdropFilter: 'blur(6px)' }}
                        onClick={() => !busy && setOpen(false)}
                    >
                        <motion.div
                            initial={{ opacity: 0, y: 10, scale: 0.98 }}
                            animate={{ opacity: 1, y: 0, scale: 1 }}
                            exit={{ opacity: 0, y: 10, scale: 0.98 }}
                            className="w-full max-w-md rounded-lg overflow-hidden"
                            style={{
                                background: 'linear-gradient(180deg, rgba(12,22,32,0.95), rgba(6,12,20,0.95))',
                                border: `1px solid ${accent}55`,
                                boxShadow: `0 0 40px ${accent}33`,
                            }}
                            onClick={(e) => e.stopPropagation()}
                        >
                            <div className="flex items-center justify-between px-4 py-2" style={{ borderBottom: `1px solid ${accent}33` }}>
                                <div className="flex items-center gap-2">
                                    <Zap size={14} style={{ color: accent }} />
                                    <span className="text-xs uppercase tracking-[0.25em]" style={{ color: accent }}>
                                        Quick Delegate
                                    </span>
                                </div>
                                <button
                                    onClick={() => setOpen(false)}
                                    disabled={busy}
                                    className="p-1 rounded cursor-pointer"
                                    style={{ color: `${accent}99` }}
                                >
                                    <X size={14} />
                                </button>
                            </div>

                            <div className="p-4 flex flex-col gap-3">
                                <Field label="Sub-agent">
                                    <select
                                        value={agent}
                                        onChange={(e) => setAgent(e.target.value)}
                                        className="w-full px-2 py-1.5 rounded text-xs font-mono"
                                        style={inputStyle(accent)}
                                    >
                                        <option value="">— select —</option>
                                        {subAgents
                                            .filter((a) => a.name || a.id)
                                            .map((a) => (
                                                <option key={a.id || a.name!} value={a.name || a.id!}>
                                                    {a.name || a.id} {a.agent_type ? `(${a.agent_type})` : ''}
                                                </option>
                                            ))}
                                    </select>
                                </Field>

                                <Field label="Brief">
                                    <textarea
                                        value={brief}
                                        onChange={(e) => setBrief(e.target.value)}
                                        rows={4}
                                        placeholder="Describe the task for the sub-agent…"
                                        className="w-full px-2 py-1.5 rounded text-xs font-mono resize-none"
                                        style={inputStyle(accent)}
                                    />
                                </Field>

                                <Field label="Mode">
                                    <div className="flex gap-2">
                                        {(['async', 'sync'] as Mode[]).map((m) => (
                                            <button
                                                key={m}
                                                onClick={() => setMode(m)}
                                                className="flex-1 px-2 py-1 rounded text-[10px] uppercase tracking-widest cursor-pointer"
                                                style={{
                                                    border: `1px solid ${mode === m ? accent : `${accent}33`}`,
                                                    background: mode === m ? `${accent}22` : 'transparent',
                                                    color: mode === m ? '#e6fcff' : `${accent}aa`,
                                                }}
                                            >
                                                {m}
                                            </button>
                                        ))}
                                    </div>
                                </Field>

                                {result && (
                                    <div
                                        className="text-[11px] p-2 rounded font-mono max-h-40 overflow-y-auto whitespace-pre-wrap"
                                        style={{
                                            border: `1px solid ${result.ok ? accent : '#ef4444'}55`,
                                            background: `${result.ok ? accent : '#ef4444'}0a`,
                                            color: result.ok ? '#d7f6ff' : '#fecaca',
                                        }}
                                    >
                                        {result.text}
                                    </div>
                                )}

                                <button
                                    onClick={handleSubmit}
                                    disabled={busy || !agent || !brief}
                                    className="flex items-center justify-center gap-2 px-3 py-2 rounded cursor-pointer transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                                    style={{
                                        background: `${accent}33`,
                                        border: `1px solid ${accent}`,
                                        color: '#e6fcff',
                                    }}
                                >
                                    <Send size={12} />
                                    <span className="text-xs uppercase tracking-widest">
                                        {busy ? 'Dispatching…' : 'Dispatch'}
                                    </span>
                                </button>
                            </div>
                        </motion.div>
                    </motion.div>
                )}
            </AnimatePresence>
        </>
    );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
    return (
        <label className="flex flex-col gap-1">
            <span className="text-[9px] uppercase tracking-[0.25em]" style={{ color: '#22d3eeaa' }}>
                {label}
            </span>
            {children}
        </label>
    );
}

function inputStyle(accent: string): React.CSSProperties {
    return {
        background: 'rgba(5, 10, 18, 0.8)',
        border: `1px solid ${accent}33`,
        color: '#e6fcff',
        outline: 'none',
    };
}