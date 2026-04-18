import { useCallback, useEffect, useRef, useState } from 'react';
import { getBase } from '../lib/api';

/**
 * Wake word detection using openwakeword on the backend.
 *
 * Streams 16 kHz mono PCM audio from the microphone over a WebSocket to
 * the server's `/v1/speech/wakeword` endpoint, where openwakeword runs
 * a purpose-built neural network for "hey jarvis" detection.
 *
 * This is dramatically more accurate than the browser's SpeechRecognition API
 * or even Whisper-based segment matching, because openwakeword is specifically
 * trained for wake word detection and processes audio in real-time (~80ms chunks).
 */

export type WakeWordState = 'off' | 'listening' | 'triggered';

// Size of audio chunks to send: 1280 samples @ 16kHz = 80ms
const CHUNK_SAMPLES = 1280;

interface UseWakeWordOptions {
    enabled: boolean;
    onWake: () => void;
}

/**
 * Build the WebSocket URL from the HTTP base URL.
 * http://... → ws://...  |  https://... → wss://...
 * Falls back to the current page origin if getBase() is empty.
 */
function getWsBase(): string {
    let base = getBase();
    if (!base) {
        // Derive from current page origin
        const loc = window.location;
        const proto = loc.protocol === 'https:' ? 'wss:' : 'ws:';
        base = `${proto}//${loc.host}`;
        return base;
    }
    return base.replace(/^http/, 'ws');
}

/**
 * Downsample a Float32Array from `fromRate` to `toRate`.
 * Returns an Int16Array suitable for openwakeword.
 */
function downsampleToInt16(buffer: Float32Array, fromRate: number, toRate: number): Int16Array {
    if (fromRate === toRate) {
        const out = new Int16Array(buffer.length);
        for (let i = 0; i < buffer.length; i++) {
            out[i] = Math.max(-32768, Math.min(32767, Math.round(buffer[i] * 32767)));
        }
        return out;
    }
    const ratio = fromRate / toRate;
    const newLength = Math.round(buffer.length / ratio);
    const out = new Int16Array(newLength);
    for (let i = 0; i < newLength; i++) {
        const srcIdx = Math.round(i * ratio);
        const sample = srcIdx < buffer.length ? buffer[srcIdx] : 0;
        out[i] = Math.max(-32768, Math.min(32767, Math.round(sample * 32767)));
    }
    return out;
}

export function useWakeWord({ enabled, onWake }: UseWakeWordOptions) {
    const [state, setState] = useState<WakeWordState>('off');
    const [supported] = useState(
        () => typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia,
    );

    const onWakeRef = useRef(onWake);
    const enabledRef = useRef(enabled);
    const cooldownRef = useRef(false);

    // Cleanup refs
    const wsRef = useRef<WebSocket | null>(null);
    const streamRef = useRef<MediaStream | null>(null);
    const audioCtxRef = useRef<AudioContext | null>(null);
    const processorRef = useRef<ScriptProcessorNode | null>(null);
    const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
    const pcmBufferRef = useRef<Int16Array>(new Int16Array(0));

    useEffect(() => {
        onWakeRef.current = onWake;
    }, [onWake]);
    useEffect(() => {
        enabledRef.current = enabled;
    }, [enabled]);

    /**
     * Tear down mic + audio context + WebSocket.
     */
    const cleanup = useCallback(() => {
        if (processorRef.current) {
            processorRef.current.disconnect();
            processorRef.current = null;
        }
        if (sourceRef.current) {
            sourceRef.current.disconnect();
            sourceRef.current = null;
        }
        if (audioCtxRef.current) {
            audioCtxRef.current.close().catch(() => { });
            audioCtxRef.current = null;
        }
        if (streamRef.current) {
            streamRef.current.getTracks().forEach((t) => t.stop());
            streamRef.current = null;
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
        pcmBufferRef.current = new Int16Array(0);
    }, []);

    const start = useCallback(async () => {
        // Prevent double-start
        if (wsRef.current || audioCtxRef.current) return;

        try {
            // 1. Get mic
            console.log('[WakeWord] Acquiring microphone...');
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            streamRef.current = stream;
            console.log('[WakeWord] Microphone acquired');

            // 2. Open WebSocket
            const wsUrl = `${getWsBase()}/v1/speech/wakeword`;
            console.log('[WakeWord] Connecting WebSocket:', wsUrl);
            const ws = new WebSocket(wsUrl);
            ws.binaryType = 'arraybuffer';
            wsRef.current = ws;

            // Wait for WS to open
            await new Promise<void>((resolve, reject) => {
                ws.onopen = () => {
                    console.log('[WakeWord] WebSocket connected');
                    resolve();
                };
                ws.onerror = () => reject(new Error('WebSocket failed'));
                // Timeout after 5s
                setTimeout(() => reject(new Error('WebSocket timeout')), 5000);
            });

            // 3. Listen for messages from the server
            ws.onmessage = (event) => {
                try {
                    const msg = JSON.parse(event.data);
                    console.log('[WakeWord] Server message:', msg);
                    if (msg.type === 'detected' && !cooldownRef.current) {
                        console.log('[WakeWord] Wake word detected! Score:', msg.score);
                        cooldownRef.current = true;
                        setState('triggered');

                        // Release mic BEFORE calling onWake so the recording
                        // callback can acquire it
                        cleanup();

                        onWakeRef.current();

                        setTimeout(() => {
                            cooldownRef.current = false;
                        }, 3000);
                    }
                } catch {
                    // Non-JSON message — ignore
                }
            };

            ws.onclose = (ev) => {
                console.log('[WakeWord] WebSocket closed:', ev.code, ev.reason);
                // If we should still be listening, reconnect after a delay
                if (enabledRef.current && !cooldownRef.current) {
                    cleanup();
                    setState('off');
                    setTimeout(() => {
                        if (enabledRef.current && !cooldownRef.current) {
                            start();
                        }
                    }, 1000);
                }
            };

            ws.onerror = (ev) => {
                console.warn('[WakeWord] WebSocket error:', ev);
                // onclose will fire after onerror
            };

            // 4. Set up audio processing pipeline
            const audioCtx = new AudioContext();
            audioCtxRef.current = audioCtx;

            // CRITICAL: Resume the AudioContext — it may start suspended
            // when not created inside a direct user gesture.
            if (audioCtx.state === 'suspended') {
                console.log('[WakeWord] AudioContext suspended, resuming...');
                await audioCtx.resume();
            }
            console.log('[WakeWord] AudioContext state:', audioCtx.state, 'sampleRate:', audioCtx.sampleRate);

            const sampleRate = audioCtx.sampleRate;

            const source = audioCtx.createMediaStreamSource(stream);
            sourceRef.current = source;

            // ScriptProcessorNode: grab audio in chunks
            const bufferSize = 4096;
            const processor = audioCtx.createScriptProcessor(bufferSize, 1, 1);
            processorRef.current = processor;

            let chunksSent = 0;
            processor.onaudioprocess = (e) => {
                if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;

                const inputData = e.inputBuffer.getChannelData(0);

                // Downsample to 16kHz int16
                const downsampled = downsampleToInt16(inputData, sampleRate, 16000);

                // Accumulate into buffer; send in CHUNK_SAMPLES-sized frames
                const prev = pcmBufferRef.current;
                const combined = new Int16Array(prev.length + downsampled.length);
                combined.set(prev);
                combined.set(downsampled, prev.length);

                let offset = 0;
                while (offset + CHUNK_SAMPLES <= combined.length) {
                    const chunk = combined.slice(offset, offset + CHUNK_SAMPLES);
                    try {
                        wsRef.current?.send(chunk.buffer);
                        chunksSent++;
                        if (chunksSent === 1 || chunksSent % 100 === 0) {
                            console.log(`[WakeWord] Audio chunks sent: ${chunksSent}`);
                        }
                    } catch {
                        // WS closed mid-send
                    }
                    offset += CHUNK_SAMPLES;
                }

                // Keep remainder
                pcmBufferRef.current = combined.slice(offset);
            };

            source.connect(processor);
            processor.connect(audioCtx.destination);

            setState('listening');
            console.log('[WakeWord] Pipeline active — listening for "Hey Jarvis"');
        } catch (err) {
            console.error('[WakeWord] Failed to start:', err);
            cleanup();
            setState('off');
        }
    }, [cleanup]);

    const stop = useCallback(() => {
        cleanup();
        setState('off');
    }, [cleanup]);

    /**
     * Call after the voice interaction cycle completes to resume listening.
     */
    const resume = useCallback(() => {
        cooldownRef.current = false;
        if (enabledRef.current) {
            start();
        }
    }, [start]);

    // Auto-start/stop based on enabled flag
    useEffect(() => {
        if (enabled && supported) {
            start();
        } else {
            stop();
        }
        return () => {
            stop();
        };
    }, [enabled, supported, start, stop]);

    return {
        state,
        supported,
        start,
        stop,
        resume,
    };
}
