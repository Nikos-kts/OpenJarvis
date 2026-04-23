/**
 * VoiceOrb — visual indicator of voice pipeline state.
 *
 * Deliberately simple: a CSS-animated circle that changes colour and
 * pulse speed based on the current VoiceState.  3D / WebAudio
 * enhancements will be added in a future pass.
 */

import { VoiceState } from '../../../lib/useVoiceSession';

interface VoiceOrbProps {
  voiceState: VoiceState;
  size?: number;
}

const STATE_CONFIG: Record<
  VoiceState,
  { color: string; label: string; animationDuration: string; opacity: string }
> = {
  idle: {
    color: '#334155',
    label: 'idle',
    animationDuration: '3s',
    opacity: '0.6',
  },
  connecting: {
    color: '#f59e0b',
    label: 'connecting…',
    animationDuration: '1.2s',
    opacity: '0.85',
  },
  listening: {
    color: '#22d3ee',
    label: 'listening',
    animationDuration: '1.6s',
    opacity: '1',
  },
  speaking: {
    color: '#a78bfa',
    label: 'speaking',
    animationDuration: '0.8s',
    opacity: '1',
  },
  error: {
    color: '#ef4444',
    label: 'error',
    animationDuration: '2s',
    opacity: '0.9',
  },
};

export function VoiceOrb({ voiceState, size = 64 }: VoiceOrbProps) {
  const cfg = STATE_CONFIG[voiceState];
  const half = size / 2;

  return (
    <div
      className="flex flex-col items-center justify-center gap-2 w-full h-full"
      aria-label={`voice orb — ${cfg.label}`}
    >
      {/* Outer ring */}
      <div
        className="rounded-full"
        style={{
          width: size,
          height: size,
          position: 'relative',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        {/* Pulse ring */}
        <div
          style={{
            position: 'absolute',
            inset: 0,
            borderRadius: '50%',
            border: `2px solid ${cfg.color}`,
            opacity: 0.5,
            animation: `voice-orb-pulse ${cfg.animationDuration} ease-in-out infinite`,
          }}
        />
        {/* Core circle */}
        <div
          style={{
            width: half,
            height: half,
            borderRadius: '50%',
            background: `radial-gradient(circle at 35% 35%, ${cfg.color}cc, ${cfg.color}44)`,
            boxShadow: `0 0 ${half * 0.6}px ${cfg.color}66`,
            opacity: cfg.opacity,
            transition: 'background 0.4s ease, box-shadow 0.4s ease',
          }}
        />
      </div>

      {/* State label */}
      <span
        className="text-[10px] font-mono uppercase tracking-widest"
        style={{ color: cfg.color, opacity: 0.8 }}
      >
        {cfg.label}
      </span>

      <style>{`
        @keyframes voice-orb-pulse {
          0%, 100% { transform: scale(1); opacity: 0.5; }
          50% { transform: scale(1.18); opacity: 0.15; }
        }
      `}</style>
    </div>
  );
}
