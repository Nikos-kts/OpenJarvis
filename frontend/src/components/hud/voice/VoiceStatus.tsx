/**
 * VoiceStatus — compact one-line indicator: WS connection dot + provider badge.
 */

import { VoiceProvider, VoiceState } from '../../../lib/useVoiceSession';

interface VoiceStatusProps {
  connected: boolean;
  provider: VoiceProvider;
  voiceState: VoiceState;
  lastError: string;
}

const PROVIDER_LABELS: Record<string, string> = {
  gemini: 'Gemini Live',
  deepgram: 'Deepgram',
  local: 'Local',
  '': '—',
};

export function VoiceStatus({ connected, provider, voiceState, lastError }: VoiceStatusProps) {
  const dotColor = connected ? '#22d3ee' : '#4b5563';
  const providerLabel = PROVIDER_LABELS[provider] ?? provider;

  return (
    <div className="flex items-center gap-2 text-[10px] font-mono" style={{ color: '#94a3b8' }}>
      {/* WS connection dot */}
      <span
        className="inline-block w-1.5 h-1.5 rounded-full shrink-0"
        style={{ background: dotColor, boxShadow: connected ? `0 0 6px ${dotColor}` : 'none' }}
        title={connected ? 'events connected' : 'events disconnected'}
      />
      <span style={{ color: '#64748b' }}>|</span>
      {/* Provider */}
      <span style={{ color: provider ? '#22d3ee99' : '#4b5563' }}>{providerLabel}</span>

      {/* Error */}
      {voiceState === 'error' && lastError && (
        <>
          <span style={{ color: '#64748b' }}>|</span>
          <span className="truncate max-w-[160px]" style={{ color: '#ef4444bb' }} title={lastError}>
            {lastError}
          </span>
        </>
      )}
    </div>
  );
}
