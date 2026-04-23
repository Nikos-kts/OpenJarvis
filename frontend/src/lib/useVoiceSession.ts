/**
 * useVoiceSession — manages the voice pipeline lifecycle from the React side.
 *
 * Responsibilities:
 * - POST /v1/voice/start  on start()
 * - POST /v1/voice/stop   on stop()
 * - POST /v1/voice/interrupt on interrupt()
 * - WebSocket /v1/voice/events  auto-reconnect with back-off
 * - Accumulates session events into state (transcript turns, VAD state,
 *   TTS state, provider, errors)
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { getBase } from './api';

// ---- Types ------------------------------------------------------------------

export type VoiceState = 'idle' | 'connecting' | 'listening' | 'speaking' | 'error';
export type VoiceProvider = 'gemini' | 'deepgram' | 'local' | '';

export interface TranscriptTurn {
  role: 'user' | 'assistant';
  text: string;
  partial: boolean;
  provider: string;
  ts: number;
}

export interface VoiceSessionState {
  voiceState: VoiceState;
  sessionId: string;
  provider: VoiceProvider;
  connected: boolean;
  turns: TranscriptTurn[];
  lastError: string;
}

const INITIAL: VoiceSessionState = {
  voiceState: 'idle',
  sessionId: '',
  provider: '',
  connected: false,
  turns: [],
  lastError: '',
};

// ---- Helpers ----------------------------------------------------------------

function buildWsUrl(path: string): string {
  const base = getBase();
  let origin: string;
  if (base) {
    origin = base.replace(/^http/, 'ws');
  } else {
    const loc = window.location;
    origin = `${loc.protocol === 'https:' ? 'wss:' : 'ws:'}//${loc.host}`;
  }
  return `${origin}${path}`;
}

async function postVoice(path: string, body?: unknown): Promise<unknown> {
  const base = getBase();
  const res = await fetch(`${base}${path}`, {
    method: 'POST',
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`${path} failed: ${res.status}`);
  return res.json();
}

// ---- Hook -------------------------------------------------------------------

export interface UseVoiceSession {
  state: VoiceSessionState;
  start: (daemonUrl?: string) => Promise<void>;
  stop: () => Promise<void>;
  interrupt: () => Promise<void>;
}

export function useVoiceSession(): UseVoiceSession {
  const [state, setState] = useState<VoiceSessionState>(INITIAL);
  const wsRef = useRef<WebSocket | null>(null);
  const closedRef = useRef(false);
  const retryRef = useRef(0);
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ---- WebSocket event pump ------------------------------------------------

  const connectEvents = useCallback((sessionId: string) => {
    if (closedRef.current) return;
    const url = buildWsUrl('/v1/voice/events');
    let ws: WebSocket;
    try {
      ws = new WebSocket(url);
    } catch {
      scheduleReconnect(sessionId);
      return;
    }
    wsRef.current = ws;

    ws.onopen = () => {
      retryRef.current = 0;
      setState((s) => ({ ...s, connected: true }));
    };

    ws.onmessage = (msg) => {
      let evt: Record<string, unknown>;
      try {
        evt = JSON.parse(msg.data as string) as Record<string, unknown>;
      } catch {
        return;
      }
      handleEvent(evt);
    };

    ws.onclose = () => {
      setState((s) => ({ ...s, connected: false }));
      if (!closedRef.current) scheduleReconnect(sessionId);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  function scheduleReconnect(sessionId: string) {
    if (closedRef.current) return;
    const delay = Math.min(30_000, 1_000 * 2 ** Math.min(retryRef.current, 5));
    retryRef.current += 1;
    retryTimerRef.current = setTimeout(() => connectEvents(sessionId), delay);
  }

  function handleEvent(evt: Record<string, unknown>) {
    const type = evt.type as string;
    const provider = (evt.provider as string) ?? '';

    switch (type) {
      case 'session_start':
        setState((s) => ({
          ...s,
          voiceState: 'listening',
          provider: (evt.provider as VoiceProvider) ?? s.provider,
          lastError: '',
        }));
        break;

      case 'session_end':
        setState((s) => ({ ...s, voiceState: 'idle', connected: false }));
        break;

      case 'provider_switch':
        setState((s) => ({
          ...s,
          provider: (evt.to as VoiceProvider) ?? s.provider,
        }));
        break;

      case 'vad': {
        const vadState = evt.state as string;
        if (vadState === 'speech_start') {
          setState((s) => ({ ...s, voiceState: 'listening' }));
        } else if (vadState === 'speech_end') {
          setState((s) => ({
            ...s,
            voiceState: s.voiceState === 'speaking' ? 'speaking' : 'listening',
          }));
        }
        break;
      }

      case 'transcript_partial': {
        const text = (evt.text as string) ?? '';
        setState((s) => {
          const turns = [...s.turns];
          // Update the last partial user turn, or append a new one.
          const last = turns[turns.length - 1];
          if (last && last.role === 'user' && last.partial) {
            turns[turns.length - 1] = { ...last, text, provider };
          } else {
            turns.push({ role: 'user', text, partial: true, provider, ts: Date.now() });
          }
          return { ...s, turns };
        });
        break;
      }

      case 'transcript_final': {
        const text = (evt.text as string) ?? '';
        setState((s) => {
          const turns = [...s.turns];
          // Finalise an existing partial, or append new.
          const last = turns[turns.length - 1];
          if (last && last.role === 'user' && last.partial) {
            turns[turns.length - 1] = { ...last, text, partial: false, provider };
          } else if (text) {
            turns.push({ role: 'user', text, partial: false, provider, ts: Date.now() });
          }
          return { ...s, turns };
        });
        break;
      }

      case 'tts_start':
        setState((s) => ({ ...s, voiceState: 'speaking' }));
        break;

      case 'tts_end':
        setState((s) => ({ ...s, voiceState: 'listening' }));
        break;

      case 'user_interrupt':
        setState((s) => ({ ...s, voiceState: 'listening' }));
        break;

      case 'error':
        setState((s) => ({
          ...s,
          voiceState: 'error',
          lastError: (evt.message as string) ?? 'unknown error',
        }));
        break;
    }
  }

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      closedRef.current = true;
      if (retryTimerRef.current) clearTimeout(retryTimerRef.current);
      wsRef.current?.close();
    };
  }, []);

  // ---- Control actions -----------------------------------------------------

  const start = useCallback(
    async (daemonUrl = 'ws://127.0.0.1:8765') => {
      setState((s) => ({ ...s, voiceState: 'connecting', lastError: '' }));
      closedRef.current = false;
      retryRef.current = 0;
      try {
        const res = (await postVoice('/v1/voice/start', { daemon_url: daemonUrl })) as {
          session_id: string;
          provider: VoiceProvider;
        };
        setState((s) => ({
          ...s,
          sessionId: res.session_id,
          provider: res.provider,
        }));
        connectEvents(res.session_id);
      } catch (err) {
        setState((s) => ({
          ...s,
          voiceState: 'error',
          lastError: err instanceof Error ? err.message : String(err),
        }));
      }
    },
    [connectEvents],
  );

  const stop = useCallback(async () => {
    closedRef.current = true;
    if (retryTimerRef.current) clearTimeout(retryTimerRef.current);
    wsRef.current?.close();
    setState(INITIAL);
    try {
      await postVoice('/v1/voice/stop');
    } catch {
      // best-effort
    }
  }, []);

  const interrupt = useCallback(async () => {
    try {
      await postVoice('/v1/voice/interrupt');
    } catch {
      // best-effort
    }
  }, []);

  return { state, start, stop, interrupt };
}
