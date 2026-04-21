import { useId } from 'react';

export type RobotState = 'idle' | 'listening' | 'thinking' | 'speaking' | 'offline';

interface Props {
  state: RobotState;
  size?: number;
}

const STATE_META: Record<
  RobotState,
  { core: string; ring: string; label: string; pulseMs: number }
> = {
  idle: { core: 'var(--color-accent)', ring: 'var(--color-accent)', label: 'Standing by', pulseMs: 3200 },
  listening: { core: '#38bdf8', ring: '#38bdf8', label: 'Listening', pulseMs: 1200 },
  thinking: { core: '#a78bfa', ring: '#a78bfa', label: 'Thinking', pulseMs: 900 },
  speaking: { core: '#f97316', ring: '#f97316', label: 'Speaking', pulseMs: 600 },
  offline: { core: 'var(--color-text-tertiary)', ring: 'var(--color-text-tertiary)', label: 'Offline', pulseMs: 0 },
};

/**
 * A stylised humanoid robot HUD figure. Body is rendered as an SVG so it can
 * react to theme variables. The glow ring + eye intensity are driven by the
 * current `state` prop.
 */
export function HumanoidRobot({ state, size = 260 }: Props) {
  const uid = useId();
  const meta = STATE_META[state];
  const pulseId = `robot-pulse-${uid}`;
  const gradId = `robot-grad-${uid}`;

  return (
    <div
      className="relative flex items-center justify-center"
      style={{ width: size, height: size }}
      aria-label={`Jarvis · ${meta.label}`}
    >
      {/* Outer aura */}
      <div
        className="absolute inset-0 rounded-full"
        style={{
          background: `radial-gradient(circle, color-mix(in srgb, ${meta.ring} 18%, transparent) 0%, transparent 65%)`,
          filter: 'blur(4px)',
          animation: meta.pulseMs
            ? `robot-aura ${meta.pulseMs}ms ease-in-out infinite`
            : 'none',
        }}
      />
      {/* Orbiting ring */}
      <div
        className="absolute rounded-full"
        style={{
          width: size * 0.92,
          height: size * 0.92,
          border: `1px dashed color-mix(in srgb, ${meta.ring} 40%, transparent)`,
          animation:
            state === 'offline' ? 'none' : 'robot-spin 18s linear infinite',
        }}
      />
      <div
        className="absolute rounded-full"
        style={{
          width: size * 0.74,
          height: size * 0.74,
          border: `1px solid color-mix(in srgb, ${meta.ring} 25%, transparent)`,
          animation:
            state === 'offline' ? 'none' : 'robot-spin-rev 26s linear infinite',
        }}
      />

      {/* Robot SVG */}
      <svg
        viewBox="0 0 200 200"
        width={size * 0.62}
        height={size * 0.62}
        style={{
          filter: `drop-shadow(0 0 12px color-mix(in srgb, ${meta.ring} 45%, transparent))`,
        }}
      >
        <defs>
          <radialGradient id={gradId} cx="50%" cy="40%" r="60%">
            <stop offset="0%" stopColor={meta.core} stopOpacity="0.9" />
            <stop offset="60%" stopColor={meta.core} stopOpacity="0.35" />
            <stop offset="100%" stopColor={meta.core} stopOpacity="0" />
          </radialGradient>
          <filter id={pulseId}>
            <feGaussianBlur stdDeviation="1.2" />
          </filter>
        </defs>

        {/* Head */}
        <rect
          x="62"
          y="24"
          width="76"
          height="66"
          rx="22"
          fill="var(--color-bg-secondary)"
          stroke={meta.ring}
          strokeWidth="1.6"
        />
        {/* Antenna */}
        <line
          x1="100"
          y1="24"
          x2="100"
          y2="10"
          stroke={meta.ring}
          strokeWidth="1.6"
        />
        <circle
          cx="100"
          cy="8"
          r="3.5"
          fill={meta.core}
          style={{
            animation: meta.pulseMs
              ? `robot-blink ${meta.pulseMs}ms ease-in-out infinite`
              : 'none',
          }}
        />
        {/* Face plate */}
        <rect
          x="72"
          y="38"
          width="56"
          height="30"
          rx="10"
          fill={`url(#${gradId})`}
          opacity="0.55"
        />
        {/* Eyes */}
        <circle cx="86" cy="53" r="4.5" fill={meta.core} filter={`url(#${pulseId})`}>
          {state !== 'offline' && (
            <animate
              attributeName="opacity"
              values="1;0.55;1"
              dur={`${meta.pulseMs || 2000}ms`}
              repeatCount="indefinite"
            />
          )}
        </circle>
        <circle cx="114" cy="53" r="4.5" fill={meta.core} filter={`url(#${pulseId})`}>
          {state !== 'offline' && (
            <animate
              attributeName="opacity"
              values="1;0.55;1"
              dur={`${meta.pulseMs || 2000}ms`}
              repeatCount="indefinite"
            />
          )}
        </circle>
        {/* Mouth/speaker grille */}
        <g stroke={meta.ring} strokeWidth="1" strokeLinecap="round">
          <line x1="90" y1="78" x2="110" y2="78" opacity="0.8" />
          <line x1="93" y1="82" x2="107" y2="82" opacity="0.55" />
        </g>

        {/* Neck */}
        <rect
          x="94"
          y="90"
          width="12"
          height="8"
          fill="var(--color-bg-tertiary)"
          stroke={meta.ring}
          strokeWidth="1"
        />

        {/* Torso */}
        <rect
          x="50"
          y="98"
          width="100"
          height="64"
          rx="14"
          fill="var(--color-bg-secondary)"
          stroke={meta.ring}
          strokeWidth="1.6"
        />
        {/* Chest core */}
        <circle
          cx="100"
          cy="130"
          r="12"
          fill={`url(#${gradId})`}
        />
        <circle
          cx="100"
          cy="130"
          r="5"
          fill={meta.core}
        >
          {state !== 'offline' && (
            <animate
              attributeName="r"
              values="4;6.5;4"
              dur={`${meta.pulseMs || 2400}ms`}
              repeatCount="indefinite"
            />
          )}
        </circle>
        {/* Shoulder joints */}
        <circle cx="50" cy="108" r="5" fill="var(--color-bg-tertiary)" stroke={meta.ring} strokeWidth="1" />
        <circle cx="150" cy="108" r="5" fill="var(--color-bg-tertiary)" stroke={meta.ring} strokeWidth="1" />
        {/* Arms */}
        <rect x="34" y="110" width="12" height="46" rx="5" fill="var(--color-bg-secondary)" stroke={meta.ring} strokeWidth="1.2" />
        <rect x="154" y="110" width="12" height="46" rx="5" fill="var(--color-bg-secondary)" stroke={meta.ring} strokeWidth="1.2" />
        {/* Legs */}
        <rect x="76" y="162" width="16" height="28" rx="5" fill="var(--color-bg-secondary)" stroke={meta.ring} strokeWidth="1.2" />
        <rect x="108" y="162" width="16" height="28" rx="5" fill="var(--color-bg-secondary)" stroke={meta.ring} strokeWidth="1.2" />
      </svg>

      <style>{`
        @keyframes robot-spin {
          from { transform: rotate(0deg); }
          to   { transform: rotate(360deg); }
        }
        @keyframes robot-spin-rev {
          from { transform: rotate(0deg); }
          to   { transform: rotate(-360deg); }
        }
        @keyframes robot-aura {
          0%, 100% { transform: scale(0.96); opacity: 0.7; }
          50%      { transform: scale(1.04); opacity: 1; }
        }
        @keyframes robot-blink {
          0%, 100% { opacity: 1; }
          50%      { opacity: 0.4; }
        }
      `}</style>
    </div>
  );
}
