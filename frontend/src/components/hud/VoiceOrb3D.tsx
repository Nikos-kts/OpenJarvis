/**
 * VoiceOrb3D — the large animated orb that sits in the HUD's bottom
 * right quadrant.  Upgrade of the old 2D ``FloatingVoiceOrb``.
 *
 * Rendering: a distorted icosahedron with a translucent outer shell
 * and a bright inner core, lit by two coloured point lights that swirl
 * around it.  The orb reacts to:
 *   - ``mood === 'speaking'`` → warmer tint, faster distortion
 *   - recording state        → cyan halo pulses, louder distortion
 *   - idle                   → slow hypnotic swirl
 *
 * Click toggles the same push-to-talk flow that the floating orb
 * exposes: first click starts recording, second click stops and pushes
 * the transcript into the global ``voiceDraft`` store so ``InputArea``
 * picks it up.
 */

import { MeshDistortMaterial, Sphere } from '@react-three/drei';
import { Canvas, useFrame } from '@react-three/fiber';
import { Loader2, Mic, MicOff } from 'lucide-react';
import { useRef, useState } from 'react';
import * as THREE from 'three';
import { useSpeech } from '../../hooks/useSpeech';
import { useAppStore } from '../../lib/store';
import { Mood } from './AgentCoreViz';

interface OrbMeshProps {
    active: boolean;
    speaking: boolean;
    hovered: boolean;
}

function OrbMesh({ active, speaking, hovered }: OrbMeshProps) {
    const groupRef = useRef<THREE.Group>(null);
    const coreRef = useRef<THREE.Mesh>(null);
    const light1 = useRef<THREE.PointLight>(null);
    const light2 = useRef<THREE.PointLight>(null);

    useFrame((state) => {
        const t = state.clock.getElapsedTime();
        if (groupRef.current) {
            groupRef.current.rotation.y = t * (active ? 0.6 : speaking ? 0.4 : 0.18);
            groupRef.current.rotation.x = Math.sin(t * 0.3) * 0.2;
        }
        if (coreRef.current) {
            const pulse = 1 + Math.sin(t * (active ? 4 : 1.8)) * (active ? 0.08 : 0.03);
            coreRef.current.scale.setScalar(pulse);
        }
        if (light1.current) {
            light1.current.position.set(Math.cos(t * 0.9) * 2.2, Math.sin(t * 1.1) * 1.4, 2);
        }
        if (light2.current) {
            light2.current.position.set(
                Math.cos(t * 0.7 + Math.PI) * 2.2,
                Math.sin(t * 0.8 + Math.PI) * 1.4,
                -1.5,
            );
        }
    });

    const coreColor = speaking ? '#f59e0b' : active ? '#22d3ee' : '#38bdf8';
    const shellColor = speaking ? '#fbbf24' : '#22d3ee';
    const distortSpeed = active ? 5 : speaking ? 3 : 1.6;
    const distortAmount = active ? 0.55 : speaking ? 0.45 : hovered ? 0.4 : 0.32;

    return (
        <group ref={groupRef}>
            <ambientLight intensity={0.2} />
            <pointLight ref={light1} color="#22d3ee" intensity={2.6} distance={8} />
            <pointLight ref={light2} color="#0ea5e9" intensity={1.8} distance={8} />

            {/* Outer translucent shell */}
            <Sphere args={[1.35, 64, 64]}>
                <MeshDistortMaterial
                    color={shellColor}
                    attach="material"
                    distort={distortAmount}
                    speed={distortSpeed}
                    roughness={0.15}
                    metalness={0.6}
                    transparent
                    opacity={0.35}
                    emissive={shellColor}
                    emissiveIntensity={0.4}
                />
            </Sphere>

            {/* Inner bright core */}
            <Sphere ref={coreRef} args={[0.78, 48, 48]}>
                <MeshDistortMaterial
                    color={coreColor}
                    attach="material"
                    distort={distortAmount * 0.6}
                    speed={distortSpeed * 1.4}
                    roughness={0}
                    metalness={0.9}
                    emissive={coreColor}
                    emissiveIntensity={1.4}
                />
            </Sphere>
        </group>
    );
}

export function VoiceOrb3D({ mood }: { mood: Mood }) {
    const speechEnabled = useAppStore((s) => s.settings.speechEnabled);
    const setVoiceDraft = useAppStore((s) => s.setVoiceDraft);
    const { state, available, startRecording, stopRecording, error } = useSpeech();
    const [hovered, setHovered] = useState(false);

    const active = state === 'recording';
    const busy = state === 'transcribing';
    const offline = !available || !speechEnabled;
    const speaking = mood === 'speaking';

    async function handleClick() {
        if (offline || busy) return;
        if (active) {
            try {
                const text = await stopRecording();
                if (text) setVoiceDraft(text);
            } catch {
                /* surfaced via useSpeech */
            }
        } else {
            await startRecording();
        }
    }

    const statusText = offline
        ? speechEnabled
            ? 'Voice offline'
            : 'Voice disabled'
        : active
            ? 'Listening…'
            : busy
                ? 'Transcribing…'
                : speaking
                    ? 'Speaking, Sir'
                    : 'Ready';

    const accent = offline ? '#6b7280' : speaking ? '#f59e0b' : '#22d3ee';

    return (
        <div
            role="button"
            tabIndex={0}
            aria-label="Voice orb — click to start or stop recording"
            onClick={handleClick}
            onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    void handleClick();
                }
            }}
            onMouseEnter={() => setHovered(true)}
            onMouseLeave={() => setHovered(false)}
            className="relative w-full h-full rounded-lg overflow-hidden cursor-pointer select-none"
            style={{
                border: `1px solid ${accent}55`,
                background: 'radial-gradient(circle at 50% 60%, #081522 0%, #02060a 70%, #000 100%)',
                boxShadow: `inset 0 0 40px ${accent}22, 0 0 24px ${accent}33`,
            }}
        >
            <Canvas
                camera={{ position: [0, 0, 4.2], fov: 45 }}
                dpr={[1, 2]}
                gl={{ antialias: true, alpha: true }}
            >
                <OrbMesh active={active} speaking={speaking} hovered={hovered} />
            </Canvas>

            {/* Pulse rings while recording */}
            {active && (
                <>
                    {[0, 0.5, 1].map((d) => (
                        <span
                            key={d}
                            className="pointer-events-none absolute inset-0 m-auto rounded-full"
                            style={{
                                width: '72%',
                                height: '72%',
                                border: `1px solid ${accent}`,
                                animation: `jarvis-orb-pulse 1.8s ${d}s ease-out infinite`,
                            }}
                        />
                    ))}
                </>
            )}

            {/* Overlay status */}
            <div className="pointer-events-none absolute inset-x-0 bottom-2 flex flex-col items-center gap-1">
                <div
                    className="flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] uppercase tracking-[0.25em]"
                    style={{
                        background: 'rgba(0,0,0,0.55)',
                        border: `1px solid ${accent}55`,
                        color: accent,
                        backdropFilter: 'blur(4px)',
                    }}
                >
                    {offline ? <MicOff size={10} /> : busy ? <Loader2 size={10} className="animate-spin" /> : <Mic size={10} />}
                    <span>{statusText}</span>
                </div>
            </div>

            {error && (
                <div
                    className="pointer-events-none absolute top-2 left-2 right-2 px-2 py-1 rounded text-[10px] text-center"
                    style={{ background: '#ef444422', border: '1px solid #ef444466', color: '#fecaca' }}
                >
                    {error}
                </div>
            )}

            <style>{`
                @keyframes jarvis-orb-pulse {
                    0%   { transform: scale(0.55); opacity: 0.7; }
                    100% { transform: scale(1.6); opacity: 0; }
                }
            `}</style>
        </div>
    );
}
