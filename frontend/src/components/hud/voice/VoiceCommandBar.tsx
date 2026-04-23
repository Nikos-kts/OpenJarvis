/**
 * VoiceCommandBar — start / stop / interrupt controls for the voice session.
 */

import { Mic, MicOff, Square, Zap } from 'lucide-react';
import { VoiceState } from '../../../lib/useVoiceSession';

interface VoiceCommandBarProps {
  voiceState: VoiceState;
  onStart: () => void;
  onStop: () => void;
  onInterrupt: () => void;
}

const ACCENT = '#22d3ee';

export function VoiceCommandBar({
  voiceState,
  onStart,
  onStop,
  onInterrupt,
}: VoiceCommandBarProps) {
  const isIdle = voiceState === 'idle' || voiceState === 'error';
  const isActive = !isIdle;
  const isConnecting = voiceState === 'connecting';
  const isSpeaking = voiceState === 'speaking';

  return (
    <div className="flex items-center justify-center gap-2">
      {/* Start / Stop */}
      {isIdle ? (
        <Btn
          onClick={onStart}
          title="start voice session"
          color={ACCENT}
          disabled={isConnecting}
        >
          <Mic size={14} />
        </Btn>
      ) : (
        <Btn onClick={onStop} title="stop voice session" color="#ef4444">
          <MicOff size={14} />
        </Btn>
      )}

      {/* Barge-in / interrupt — only while speaking */}
      <Btn
        onClick={onInterrupt}
        title="interrupt (barge-in)"
        color="#f59e0b"
        disabled={!isSpeaking}
      >
        <Zap size={14} />
      </Btn>

      {/* Stop (square) — shown while active as an alternative to MicOff */}
      {isActive && (
        <Btn onClick={onStop} title="end session" color="#6b7280">
          <Square size={12} />
        </Btn>
      )}
    </div>
  );
}

function Btn({
  children,
  onClick,
  title,
  color,
  disabled = false,
}: {
  children: React.ReactNode;
  onClick: () => void;
  title: string;
  color: string;
  disabled?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      title={title}
      disabled={disabled}
      className="flex items-center justify-center rounded"
      style={{
        width: 28,
        height: 28,
        background: disabled ? '#1e293b44' : `${color}18`,
        border: `1px solid ${disabled ? '#334155' : color + '44'}`,
        color: disabled ? '#475569' : color,
        cursor: disabled ? 'not-allowed' : 'pointer',
        transition: 'background 0.15s ease, border-color 0.15s ease',
      }}
      onMouseEnter={(e) => {
        if (!disabled) {
          (e.currentTarget as HTMLButtonElement).style.background = `${color}30`;
        }
      }}
      onMouseLeave={(e) => {
        if (!disabled) {
          (e.currentTarget as HTMLButtonElement).style.background = `${color}18`;
        }
      }}
    >
      {children}
    </button>
  );
}
