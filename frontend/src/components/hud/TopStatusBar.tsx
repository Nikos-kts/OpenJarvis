/**
 * TopStatusBar — name, model, uptime, connection status.
 *
 * Sits at the top of the HUD and scrolls nothing — it is the user's
 * "am I connected to Jarvis?" check.
 */

import { Activity, Cpu, Hexagon } from 'lucide-react';
import { JarvisState } from '../../lib/jarvis-api';

export function TopStatusBar({
    state,
    connected,
    error,
}: {
    state: JarvisState | null;
    connected: boolean;
    error: Error | null;
}) {
    const status = error ? 'offline' : !state ? 'booting' : 'online';
    const color = status === 'online' ? '#22d3ee' : status === 'booting' ? '#eab308' : '#ef4444';
    const uptime = state ? formatUptime(state.uptime_seconds) : '--';

    return (
        <div
            className="flex items-center justify-between px-4 py-2 rounded-lg"
            style={{
                border: `1px solid ${color}33`,
                background: 'rgba(10, 18, 28, 0.8)',
                boxShadow: `0 0 24px ${color}22 inset`,
            }}
        >
            <div className="flex items-center gap-3">
                <Hexagon size={20} style={{ color }} />
                <div>
                    <div className="text-sm font-semibold tracking-wider" style={{ color: '#e6fcff' }}>
                        {state?.persona.name ?? 'JARVIS'}
                    </div>
                    <div className="text-[10px] uppercase tracking-widest" style={{ color: `${color}bb` }}>
                        {status} · v0.1
                    </div>
                </div>
            </div>

            <div className="flex items-center gap-6 text-xs" style={{ color: '#a4d5e0' }}>
                <Stat icon={<Cpu size={12} />} label="MODEL" value={state?.model || '—'} />
                <Stat icon={<Activity size={12} />} label="UPTIME" value={uptime} />
                <Stat label="TURNS" value={String(state?.metrics.total_turns ?? 0)} />
                <Stat label="DELEGATED" value={String(state?.metrics.total_delegations ?? 0)} />
                <div className="flex items-center gap-1.5">
                    <span
                        className="inline-block w-2 h-2 rounded-full"
                        style={{
                            background: color,
                            boxShadow: `0 0 8px ${color}`,
                            animation: connected ? 'pulse 1.6s ease-in-out infinite' : undefined,
                        }}
                    />
                    <span className="uppercase tracking-widest text-[10px]" style={{ color: `${color}dd` }}>
                        {connected ? 'stream' : 'idle'}
                    </span>
                </div>
            </div>
        </div>
    );
}

function Stat({ icon, label, value }: { icon?: React.ReactNode; label: string; value: string }) {
    return (
        <div className="flex items-center gap-1.5">
            {icon && <span style={{ color: '#22d3ee99' }}>{icon}</span>}
            <span className="uppercase tracking-widest text-[9px]" style={{ color: '#22d3ee99' }}>
                {label}
            </span>
            <span className="font-mono text-[11px]" style={{ color: '#e6fcff' }}>
                {value}
            </span>
        </div>
    );
}

function formatUptime(seconds: number): string {
    const s = Math.max(0, Math.floor(seconds));
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const r = s % 60;
    if (h > 0) return `${h}h ${m}m`;
    if (m > 0) return `${m}m ${r}s`;
    return `${r}s`;
}
