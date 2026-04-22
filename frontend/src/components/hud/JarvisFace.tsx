/**
 * JarvisFace — wireframe humanoid head used in the Identity card.
 *
 * Stylised after the reference mockup: a procedurally drawn SVG bust
 * with polygonal contour lines and a soft cyan glow.  When Jarvis is
 * speaking (or producing tokens) the wireframe pulses and concentric
 * rings emanate outward to hint at TTS output without requiring any
 * actual audio wiring.
 */

import { motion } from 'motion/react';
import { Mood } from './AgentCoreViz';

export function JarvisFace({ mood }: { mood: Mood }) {
    const accent = '#22d3ee';
    const speaking = mood === 'speaking';
    const thinking = mood === 'thinking' || mood === 'tool';

    return (
        <div className="relative w-full h-full flex items-center justify-center select-none">
            {/* Backdrop glow */}
            <motion.div
                className="absolute inset-0 rounded-lg"
                animate={{
                    opacity: speaking ? [0.5, 0.9, 0.5] : thinking ? [0.35, 0.55, 0.35] : 0.35,
                }}
                transition={{ duration: speaking ? 1.2 : 2.4, repeat: Infinity, ease: 'easeInOut' }}
                style={{
                    background: `radial-gradient(circle at 50% 45%, ${accent}33 0%, ${accent}11 35%, transparent 70%)`,
                }}
            />

            {/* Concentric pulse rings — visible while speaking */}
            {speaking &&
                [0, 0.4, 0.8].map((d) => (
                    <motion.span
                        key={d}
                        className="absolute rounded-full"
                        style={{
                            width: '62%',
                            height: '62%',
                            border: `1px solid ${accent}`,
                        }}
                        initial={{ scale: 0.6, opacity: 0.6 }}
                        animate={{ scale: 1.6, opacity: 0 }}
                        transition={{ duration: 1.6, delay: d, repeat: Infinity, ease: 'easeOut' }}
                    />
                ))}

            <svg
                viewBox="0 0 200 220"
                className="relative w-full h-full"
                style={{ filter: `drop-shadow(0 0 6px ${accent}88)` }}
            >
                <defs>
                    <linearGradient id="jf-stroke" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor={accent} stopOpacity="0.95" />
                        <stop offset="100%" stopColor={accent} stopOpacity="0.55" />
                    </linearGradient>
                    <linearGradient id="jf-fill" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor={accent} stopOpacity="0.22" />
                        <stop offset="100%" stopColor={accent} stopOpacity="0.04" />
                    </linearGradient>
                </defs>

                {/* Head silhouette (stylised) */}
                <motion.g
                    animate={{ opacity: speaking ? [0.9, 1, 0.9] : 1 }}
                    transition={{ duration: 1.2, repeat: Infinity }}
                    stroke="url(#jf-stroke)"
                    strokeWidth="1.2"
                    fill="url(#jf-fill)"
                    strokeLinejoin="round"
                    strokeLinecap="round"
                >
                    {/* Skull outline */}
                    <path d="M100 22 L140 34 L162 62 L164 110 L150 146 L128 168 L100 176 L72 168 L50 146 L36 110 L38 62 L60 34 Z" />
                    {/* Jawline highlight */}
                    <path d="M72 168 L100 180 L128 168" fill="none" />
                    {/* Cranial ridge */}
                    <path d="M60 34 L100 22 L140 34" fill="none" />
                    {/* Forehead plates */}
                    <path d="M60 34 L80 70 L100 62 L120 70 L140 34" fill="none" />
                    {/* Brow bar */}
                    <path d="M62 80 L100 72 L138 80" fill="none" />
                    {/* Cheek polys */}
                    <path d="M50 110 L80 104 L80 140 L56 140 Z" fill="none" />
                    <path d="M150 110 L120 104 L120 140 L144 140 Z" fill="none" />
                    {/* Nose ridge */}
                    <path d="M100 78 L96 118 L100 128 L104 118 Z" fill="none" />
                    {/* Mouth line */}
                    <path d="M82 148 L100 152 L118 148" fill="none" />
                    {/* Neck */}
                    <path d="M84 176 L84 200 L116 200 L116 176" fill="none" />
                </motion.g>

                {/* Eyes — independent pulse to sell the "alive" feel */}
                <motion.g
                    animate={{ opacity: [0.6, 1, 0.6] }}
                    transition={{ duration: speaking ? 0.9 : 2.2, repeat: Infinity }}
                >
                    <circle cx="80" cy="96" r="3.2" fill={accent} />
                    <circle cx="120" cy="96" r="3.2" fill={accent} />
                </motion.g>

                {/* HUD micro-ticks around the head */}
                <g stroke={accent} strokeOpacity="0.5" strokeWidth="1">
                    <line x1="14" y1="110" x2="28" y2="110" />
                    <line x1="172" y1="110" x2="186" y2="110" />
                    <line x1="100" y1="6" x2="100" y2="14" />
                    <line x1="100" y1="206" x2="100" y2="214" />
                </g>
            </svg>

            {/* Wordmark */}
            <div
                className="absolute bottom-1 left-0 right-0 text-center text-[9px] tracking-[0.5em] font-semibold"
                style={{ color: `${accent}cc`, textShadow: `0 0 6px ${accent}66` }}
            >
                J.A.R.V.I.S.
            </div>
        </div>
    );
}
