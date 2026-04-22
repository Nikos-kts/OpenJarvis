/**
 * IdentityCard — HUD identity panel with the wireframe Jarvis face as
 * its centrepiece and a compact row of persona-file health ticks.
 *
 * Replaces the text-heavy ``PersonaCard`` for the main Identity panel.
 * Still exposes the "reload persona" affordance because that's a
 * common day-to-day action while iterating on SOUL/MEMORY/USER.
 */

import { AlertCircle, CheckCircle2, RefreshCw } from 'lucide-react';
import { useState } from 'react';
import { JarvisState, reloadJarvisPersona } from '../../lib/jarvis-api';
import { Mood } from './AgentCoreViz';
import { JarvisFace } from './JarvisFace';

const ACCENT = '#22d3ee';

export function IdentityCard({
    state,
    mood,
    onReloaded,
}: {
    state: JarvisState | null;
    mood: Mood;
    onReloaded?: () => void;
}) {
    const [reloading, setReloading] = useState(false);
    const files = state?.persona.files ?? {};

    async function handleReload() {
        setReloading(true);
        try {
            await reloadJarvisPersona();
            onReloaded?.();
        } finally {
            setReloading(false);
        }
    }

    return (
        <div className="flex flex-col h-full min-h-0 gap-2">
            <div className="flex-1 min-h-0 relative">
                <JarvisFace mood={mood} />
                <button
                    onClick={handleReload}
                    disabled={reloading || !state}
                    className="absolute top-1 right-1 p-1 rounded transition-colors cursor-pointer disabled:opacity-40"
                    title="Reload persona files"
                    style={{ border: `1px solid ${ACCENT}33`, color: ACCENT, background: `${ACCENT}08` }}
                >
                    <RefreshCw size={11} className={reloading ? 'animate-spin' : ''} />
                </button>
            </div>

            <div className="flex items-center justify-between text-[10px]" style={{ color: `${ACCENT}99` }}>
                <span className="uppercase tracking-[0.25em]">
                    {state?.persona.honorific || 'sir'} · {state?.persona.voice_id || '—'}
                </span>
                <div className="flex items-center gap-1.5">
                    {(['soul', 'memory', 'user'] as const).map((k) => {
                        const ok = files[k]?.exists;
                        return (
                            <span
                                key={k}
                                title={`${k}: ${files[k]?.path ?? '(unset)'}`}
                                className="flex items-center gap-0.5 px-1 py-0.5 rounded uppercase tracking-widest text-[8px]"
                                style={{
                                    border: `1px solid ${ok ? ACCENT : '#ef4444'}44`,
                                    background: `${ok ? ACCENT : '#ef4444'}0a`,
                                    color: ok ? `${ACCENT}cc` : '#fecaca',
                                }}
                            >
                                {ok ? <CheckCircle2 size={8} /> : <AlertCircle size={8} />}
                                {k[0]}
                            </span>
                        );
                    })}
                </div>
            </div>
        </div>
    );
}
