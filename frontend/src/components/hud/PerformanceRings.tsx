/**
 * PerformanceRings — three radial-bar gauges (tokens, tools, errors).
 *
 * Uses recharts RadialBar so the HUD stays dependency-light (no
 * canvas).  Values are derived from `JarvisState.metrics`.
 */

import { RadialBar, RadialBarChart, ResponsiveContainer } from 'recharts';
import { JarvisState } from '../../lib/jarvis-api';

export function PerformanceRings({ state }: { state: JarvisState | null }) {
    const tokensOut = state?.metrics.total_tokens_out ?? 0;
    const tokensIn = state?.metrics.total_tokens_in ?? 0;
    const turns = state?.metrics.total_turns ?? 0;
    const errors = state?.metrics.total_errors ?? 0;

    const tokenRatio = tokensIn + tokensOut === 0 ? 0 : tokensOut / (tokensIn + tokensOut);
    const errRate = turns === 0 ? 0 : errors / turns;

    return (
        <div className="grid grid-cols-3 gap-2 h-full">
            <Ring label="OUT / IN" pct={tokenRatio} color="#22d3ee" sub={`${tokensOut}/${tokensIn}`} />
            <Ring label="TURNS" pct={Math.min(1, turns / 100)} color="#a78bfa" sub={String(turns)} />
            <Ring label="ERR" pct={Math.min(1, errRate)} color={errRate > 0.05 ? '#ef4444' : '#22d3ee'} sub={String(errors)} />
        </div>
    );
}

function Ring({ label, pct, color, sub }: { label: string; pct: number; color: string; sub: string }) {
    const data = [{ name: label, value: Math.round(pct * 100), fill: color }];
    return (
        <div className="relative flex flex-col items-center justify-center">
            <ResponsiveContainer width="100%" height="100%">
                <RadialBarChart
                    innerRadius="70%"
                    outerRadius="100%"
                    data={data}
                    startAngle={225}
                    endAngle={-45}
                >
                    <RadialBar dataKey="value" background={{ fill: `${color}14` }} cornerRadius={6} />
                </RadialBarChart>
            </ResponsiveContainer>
            <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
                <div className="text-sm font-mono" style={{ color: '#e6fcff' }}>
                    {sub}
                </div>
                <div className="text-[9px] uppercase tracking-[0.2em]" style={{ color: `${color}cc` }}>
                    {label}
                </div>
            </div>
        </div>
    );
}
