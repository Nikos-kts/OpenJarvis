import { useCallback, useEffect, useRef, useState } from 'react';
import { getBase } from '../lib/api';

/**
 * Global voice channel via Gemini Live API.
 *
 * connect() — acquires mic, opens WebSocket, and immediately starts
 *             streaming audio once the Gemini session is ready.
 * disconnect() — tears down the session.
 *
 * The channel stays open until disconnect() is called. No auto-mute,
 * no silence timeout.
 *
 * States: idle → connecting → active
 */

export type VoiceLiveState = 'idle' | 'connecting' | 'active';

interface UseVoiceLiveOptions {
    /** Gemini voice persona */
    voice?: string;
    /** Called with each chunk of user transcript */
    onUserTranscript?: (text: string) => void;
    /** Called with each chunk of assistant transcript */
    onAssistantTranscript?: (text: string) => void;
    /** Called when Gemini finishes its turn */
    onTurnComplete?: () => void;
    /** Called when the session disconnects */
    onSessionEnd?: () => void;
}

function getWsBase(): string {
    const base = getBase();
    if (!base) {
        const loc = window.location;
        const proto = loc.protocol === 'https:' ? 'wss:' : 'ws:';
        return `${proto}//${loc.host}`;
    }
    return base.replace(/^http/, 'ws');
}

function downsampleToInt16(
    buffer: Float32Array,
    fromRate: number,
    toRate: number,
): Int16Array {
    const ratio = fromRate / toRate;
    const newLength = Math.round(buffer.length / ratio);
    const out = new Int16Array(newLength);
    for (let i = 0; i < newLength; i++) {
        const srcIdx = Math.min(Math.round(i * ratio), buffer.length - 1);
        const sample = buffer[srcIdx];
        out[i] = Math.max(-32768, Math.min(32767, Math.round(sample * 32767)));
    }
    return out;
}

const PLAYBACK_RATE = 24000;

export function useVoiceLive(opts: UseVoiceLiveOptions = {}) {
    const [state, setState] = useState<VoiceLiveState>('idle');
    const [muted, setMuted] = useState(false);
    const [userText, setUserText] = useState('');
    const [assistantText, setAssistantText] = useState('');
    const [micLevel, setMicLevel] = useState(0);
    const [jarvisSpeaking, setJarvisSpeaking] = useState(false);

    const optsRef = useRef(opts);
    optsRef.current = opts;

    // Refs for resources
    const wsRef = useRef<WebSocket | null>(null);
    const streamRef = useRef<MediaStream | null>(null);
    const audioCtxCaptureRef = useRef<AudioContext | null>(null);
    const processorRef = useRef<ScriptProcessorNode | null>(null);
    const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
    const audioCtxPlayRef = useRef<AudioContext | null>(null);
    const nextPlayTimeRef = useRef(0);
    const speakingCheckRef = useRef<ReturnType<typeof setInterval> | null>(null);
    const mutedRef = useRef(false);

    const cleanup = useCallback(() => {
        if (speakingCheckRef.current) {
            clearInterval(speakingCheckRef.current);
            speakingCheckRef.current = null;
        }
        if (processorRef.current) {
            processorRef.current.disconnect();
            processorRef.current = null;
        }
        if (sourceRef.current) {
            sourceRef.current.disconnect();
            sourceRef.current = null;
        }
        if (audioCtxCaptureRef.current) {
            audioCtxCaptureRef.current.close().catch(() => { });
            audioCtxCaptureRef.current = null;
        }
        if (streamRef.current) {
            streamRef.current.getTracks().forEach((t: MediaStreamTrack) => t.stop());
            streamRef.current = null;
        }
        if (audioCtxPlayRef.current) {
            audioCtxPlayRef.current.close().catch(() => { });
            audioCtxPlayRef.current = null;
        }
        if (wsRef.current) {
            wsRef.current.onclose = null;
            wsRef.current.onerror = null;
            wsRef.current.onmessage = null;
            if (wsRef.current.readyState <= WebSocket.OPEN) {
                wsRef.current.close();
            }
            wsRef.current = null;
        }
        nextPlayTimeRef.current = 0;
        setJarvisSpeaking(false);
    }, []);

    /**
     * Open a Gemini Live session. Mic starts streaming as soon as the
     * server sends "ready". The channel stays open until disconnect().
     */
    const connect = useCallback(
        async (voice?: string) => {
            if (wsRef.current) return;

            setState('connecting');
            setUserText('');
            setAssistantText('');

            try {
                // 1. Mic permission
                console.log('[VoiceLive] Acquiring microphone...');
                const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                streamRef.current = stream;

                // 2. WebSocket
                const wsUrl = `${getWsBase()}/v1/voice/live`;
                console.log('[VoiceLive] Connecting:', wsUrl);
                const ws = new WebSocket(wsUrl);
                ws.binaryType = 'arraybuffer';
                wsRef.current = ws;

                await new Promise<void>((resolve, reject) => {
                    ws.onopen = () => resolve();
                    ws.onerror = () => reject(new Error('WebSocket failed'));
                    setTimeout(() => reject(new Error('WebSocket timeout')), 10000);
                });

                // 3. Config
                ws.send(
                    JSON.stringify({
                        type: 'config',
                        voice: voice || optsRef.current.voice || 'Kore',
                        system: 'You are Jarvis, a helpful and concise AI assistant.',
                    }),
                );

                // 4. Playback context
                let playCtx = new AudioContext({ sampleRate: PLAYBACK_RATE });
                audioCtxPlayRef.current = playCtx;
                if (playCtx.state === 'suspended') await playCtx.resume();

                /** Kill all scheduled audio and create a fresh playback context */
                const resetPlayback = async () => {
                    try { playCtx.close().catch(() => { }); } catch { }
                    playCtx = new AudioContext({ sampleRate: PLAYBACK_RATE });
                    audioCtxPlayRef.current = playCtx;
                    if (playCtx.state === 'suspended') await playCtx.resume();
                    nextPlayTimeRef.current = 0;
                };

                // Jarvis speaking tracker
                speakingCheckRef.current = setInterval(() => {
                    if (audioCtxPlayRef.current && nextPlayTimeRef.current > audioCtxPlayRef.current.currentTime) {
                        setJarvisSpeaking(true);
                    } else {
                        setJarvisSpeaking(false);
                    }
                }, 100);

                // Track whether session is ready (set true when server says "ready")
                let sessionReady = false;
                mutedRef.current = false;
                setMuted(false);

                // 5. Server messages
                ws.onmessage = (event) => {
                    if (event.data instanceof ArrayBuffer) {
                        const pcm16 = new Int16Array(event.data);
                        const float32 = new Float32Array(pcm16.length);
                        for (let i = 0; i < pcm16.length; i++) {
                            float32[i] = pcm16[i] / 32768;
                        }
                        const buffer = playCtx.createBuffer(1, float32.length, PLAYBACK_RATE);
                        buffer.getChannelData(0).set(float32);
                        const src = playCtx.createBufferSource();
                        src.buffer = buffer;
                        src.connect(playCtx.destination);
                        const now = playCtx.currentTime;
                        const startAt = Math.max(now, nextPlayTimeRef.current);
                        src.start(startAt);
                        nextPlayTimeRef.current = startAt + buffer.duration;
                    } else {
                        try {
                            const msg = JSON.parse(event.data);
                            console.log('[VoiceLive] Server:', msg.type, msg.text?.slice(0, 60) || '');

                            if (msg.type === 'ready') {
                                // Session is active — mic streams unless muted
                                sessionReady = true;
                                setState('active');
                                console.log('[VoiceLive] Session active — mic live');
                            } else if (msg.type === 'user_transcript') {
                                setUserText((prev: string) => prev + msg.text);
                                optsRef.current.onUserTranscript?.(msg.text);
                            } else if (msg.type === 'assistant_transcript') {
                                setAssistantText((prev: string) => prev + msg.text);
                                optsRef.current.onAssistantTranscript?.(msg.text);
                            } else if (msg.type === 'turn_complete') {
                                optsRef.current.onTurnComplete?.();
                                setUserText('');
                                setAssistantText('');
                            } else if (msg.type === 'interrupted') {
                                console.log('[VoiceLive] Interrupted — silencing playback');
                                optsRef.current.onTurnComplete?.();
                                setUserText('');
                                setAssistantText('');
                                resetPlayback();
                            } else if (msg.type === 'error') {
                                console.error('[VoiceLive] Error:', msg.detail);
                                cleanup();
                                setState('idle');
                                optsRef.current.onSessionEnd?.();
                            }
                        } catch {
                            // ignore
                        }
                    }
                };

                ws.onclose = () => {
                    console.log('[VoiceLive] WebSocket closed');
                    cleanup();
                    setState('idle');
                    optsRef.current.onSessionEnd?.();
                };

                ws.onerror = (ev) => {
                    console.warn('[VoiceLive] WebSocket error:', ev);
                };

                // 6. Mic capture pipeline — sends audio once micLive is true
                const captureCtx = new AudioContext();
                audioCtxCaptureRef.current = captureCtx;
                if (captureCtx.state === 'suspended') await captureCtx.resume();

                const micSource = captureCtx.createMediaStreamSource(stream);
                sourceRef.current = micSource;

                const processor = captureCtx.createScriptProcessor(4096, 1, 1);
                processorRef.current = processor;

                processor.onaudioprocess = (e) => {
                    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
                    const inputData = e.inputBuffer.getChannelData(0);

                    // RMS for mic level
                    let sum = 0;
                    for (let i = 0; i < inputData.length; i++) sum += inputData[i] * inputData[i];
                    setMicLevel(Math.sqrt(sum / inputData.length));

                    // Only send audio when session is ready and not muted
                    if (!sessionReady || mutedRef.current) return;

                    const pcm16 = downsampleToInt16(inputData, captureCtx.sampleRate, 16000);
                    try {
                        wsRef.current.send(pcm16.buffer);
                    } catch {
                        // WS closed
                    }
                };

                micSource.connect(processor);
                processor.connect(captureCtx.destination);
                console.log('[VoiceLive] Capture pipeline ready — waiting for server ready');
            } catch (err) {
                console.error('[VoiceLive] Failed to connect:', err);
                cleanup();
                setState('idle');
            }
        },
        [cleanup],
    );

    /** Mute mic — connection stays open */
    const mute = useCallback(() => {
        mutedRef.current = true;
        setMuted(true);
        console.log('[VoiceLive] Muted');
    }, []);

    /** Unmute mic — resume streaming */
    const unmute = useCallback(() => {
        mutedRef.current = false;
        setMuted(false);
        console.log('[VoiceLive] Unmuted');
    }, []);

    /** Disconnect the session */
    const disconnect = useCallback(() => {
        cleanup();
        setState('idle');
        setMuted(false);
    }, [cleanup]);

    // Cleanup on unmount
    useEffect(() => {
        return () => { cleanup(); };
    }, [cleanup]);

    return {
        state,
        muted,
        userText,
        assistantText,
        micLevel,
        jarvisSpeaking,
        connect,
        disconnect,
        mute,
        unmute,
    };
}
