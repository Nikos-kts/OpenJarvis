/**
 * AgentCoreViz — central animated "brain / arc reactor" SVG.
 *
 * Pulses faster while Jarvis is thinking (INFERENCE_START without END),
 * flares a cyan ring while a tool call is in flight, and goes dim when
 * idle.  All animation is pure SVG + motion — no canvas, no GL.
 */

import { motion } from 'motion/react';
import { useMemo } from 'react';

type Mood = 'idle' | 'thinking' | 'tool' | 'speaking' | 'delegating';

export function AgentCoreViz({ mood, tokens }: { mood: Mood; tokens: number }) {
    const accent = '#22d3ee';
    // Derive animation speeds from mood
    const speed =
        mood === 'thinking'
            ? 0.9
            : mood === 'tool'
                ? 1.6
                : mood === 'delegating'
                    ? 1.2
                    : mood === 'speaking'
                        ? 0.7
                        : 2.6;
    const density = Math.min(32, 8 + Math.floor(Math.log2(Math.max(1, tokens / 100)) * 4));
    const neurons = useMemo(() => seedNeurons(density), [density]);

    return (
        <div className="relative w-full aspect-square flex items-center justify-center">
            <svg viewBox="-100 -100 200 200" className="w-full h-full">
                {/* Outer ring with orbiting dashes */}
                <motion.circle
                    cx={0}
                    cy={0}
                    r={88}
                    fill="none"
                    stroke={accent}
                    strokeOpacity={0.35}
                    strokeWidth={0.6}
                    strokeDasharray="4 6"
                    animate={{ rotate: 360 }}
                    transition={{ duration: 40, repeat: Infinity, ease: 'linear' }}
                    style={{ originX: '100px', originY: '100px' }}
                />
                <motion.circle
                    cx={0}
                    cy={0}
                    r={72}
                    fill="none"
                    stroke={accent}
                    strokeOpacity={0.25}
                    strokeWidth={0.4}
                    strokeDasharray="2 8"
                    animate={{ rotate: -360 }}
                    transition={{ duration: 55, repeat: Infinity, ease: 'linear' }}
                    style={{ originX: '100px', originY: '100px' }}
                />

                {/* Core */}
                <motion.circle
                    cx={0}
                    cy={0}
                    r={28}
                    fill={accent}
                    fillOpacity={0.08}
                    stroke={accent}
                    strokeWidth={0.8}
                    animate={{
                        scale: [1, 1.06, 1],
                        opacity: [0.7, 1, 0.7],
                    }}
                    transition={{ duration: speed, repeat: Infinity, ease: 'easeInOut' }}
                />
                <motion.circle
                    cx={0}
                    cy={0}
                    r={14}
                    fill={accent}
                    fillOpacity={0.35}
                    animate={{
                        scale: mood === 'speaking' ? [1, 1.3, 1] : [1, 1.15, 1],
                        opacity: [0.5, 1, 0.5],
                    }}
                    transition={{ duration: speed * 0.6, repeat: Infinity, ease: 'easeInOut' }}
                />

                {/* Neuron field */}
                {neurons.map((n, i) => (
                    <motion.circle
                        key={i}
                        cx={n.x}
                        cy={n.y}
                        r={0.9}
                        fill={accent}
                        animate={{ opacity: [0.1, 0.9, 0.1] }}
                        transition={{
                            duration: 1.4 + (i % 7) * 0.12,
                            repeat: Infinity,
                            delay: (i % 11) * 0.07,
                            ease: 'easeInOut',
                        }}
                    />
                ))}
                {neurons.slice(0, density / 2).map((n, i) => {
                    const m = neurons[(i * 3 + 1) % neurons.length];
                    return (
                        <motion.line
                            key={`l${i}`}
                            x1={n.x}
                            y1={n.y}
                            x2={m.x}
                            y2={m.y}
                            stroke={accent}
                            strokeWidth={0.2}
                            animate={{ opacity: [0.05, 0.35, 0.05] }}
                            transition={{
                                duration: 1.6 + (i % 5) * 0.2,
                                repeat: Infinity,
                                delay: (i % 7) * 0.1,
                            }}
                        />
                    );
                })}

                {/* Tick marks */}
                {Array.from({ length: 24 }).map((_, i) => {
                    const a = (i / 24) * Math.PI * 2;
                    const r1 = 90;
                    const r2 = i % 4 === 0 ? 96 : 93;
                    return (
                        <line
                            key={i}
                            x1={Math.cos(a) * r1}
                            y1={Math.sin(a) * r1}
                            x2={Math.cos(a) * r2}
                            y2={Math.sin(a) * r2}
                            stroke={accent}
                            strokeOpacity={i % 4 === 0 ? 0.6 : 0.25}
                            strokeWidth={0.5}
                        />
                    );
                })}
            </svg>

            <div className="absolute bottom-2 left-0 right-0 flex flex-col items-center pointer-events-none">
                <div
                    className="text-[10px] uppercase tracking-[0.3em]"
                    style={{ color: accent, opacity: 0.8 }}
                >
                    {moodLabel(mood)}
                </div>
            </div>
        </div>
    );
}

function moodLabel(m: Mood): string {
    switch (m) {
        case 'thinking':
            return 'Processing';
        case 'tool':
            return 'Tool Call';
        case 'speaking':
            return 'Responding';
        case 'delegating':
            return 'Delegating';
        default:
            return 'Standby';
    }
}

function seedNeurons(n: number): { x: number; y: number }[] {
    // Deterministic fibonacci-spiral inside the core band (r ∈ [32, 68])
    const out: { x: number; y: number }[] = [];
    const golden = Math.PI * (3 - Math.sqrt(5));
    for (let i = 0; i < n; i++) {
        const t = i / Math.max(1, n - 1);
        const r = 32 + t * 36;
        const a = i * golden;
        out.push({ x: Math.cos(a) * r, y: Math.sin(a) * r });
    }
    return out;
}

export type { Mood };
