import { Mic, MicOff, Phone, PhoneOff } from 'lucide-react';
import { useCallback, useEffect, useRef } from 'react';
import { useVoiceLive } from '../hooks/useVoiceLive';
import { storeMemory } from '../lib/api';
import { generateId, useAppStore } from '../lib/store';

/**
 * Floating voice control panel — visible globally.
 *
 * Single connect/disconnect button.
 * Connect = open Gemini Live session + mic immediately active.
 * Session stays open until user clicks disconnect.
 */
export function VoicePanel() {
    const speechEnabled = useAppStore((s) => s.settings.speechEnabled);
    const liveVoice = useAppStore((s) => s.settings.liveVoice);
    const liveModel = useAppStore((s) => s.settings.liveModel);
    const voiceMode = useAppStore((s) => s.settings.voiceMode);
    const voiceEngineModel = useAppStore((s) => s.settings.voiceEngineModel);
    const voiceEngineSttModel = useAppStore((s) => s.settings.voiceEngineSttModel);
    const voiceEngineTtsMode = useAppStore((s) => s.settings.voiceEngineTtsMode);
    const voiceEngineTtsModel = useAppStore((s) => s.settings.voiceEngineTtsModel);
    const voicePlaybackSpeed = useAppStore((s) => s.settings.voicePlaybackSpeed);
    const selectedModel = useAppStore((s) => s.selectedModel);
    const createConversation = useAppStore((s) => s.createConversation);
    const addMessage = useAppStore((s) => s.addMessage);

    const fullUserTextRef = useRef('');
    const fullAssistantTextRef = useRef('');

    /** Ensure an active conversation exists, return its id */
    const ensureConvId = useCallback(() => {
        let convId = useAppStore.getState().activeId;
        if (!convId) {
            convId = createConversation(selectedModel);
        }
        return convId;
    }, [createConversation, selectedModel]);

    /** Flush the current turn's accumulated text as chat messages + memory */
    const flushTurn = useCallback(() => {
        const userContent = fullUserTextRef.current.trim();
        const assistantContent = fullAssistantTextRef.current.trim();
        if (!userContent && !assistantContent) return;

        const convId = ensureConvId();
        if (userContent) {
            addMessage(convId, {
                id: generateId(),
                role: 'user',
                content: userContent,
                timestamp: Date.now(),
            });
        }
        if (assistantContent) {
            addMessage(convId, {
                id: generateId(),
                role: 'assistant',
                content: assistantContent,
                timestamp: Date.now(),
            });
        }

        const transcript = [
            userContent && `User: ${userContent}`,
            assistantContent && `Jarvis: ${assistantContent}`,
        ].filter(Boolean).join('\n');
        if (transcript) {
            storeMemory(transcript, { source: 'voice', timestamp: new Date().toISOString() })
                .catch((err) => console.warn('[Voice] Failed to store memory:', err));
        }

        fullUserTextRef.current = '';
        fullAssistantTextRef.current = '';
    }, [ensureConvId, addMessage]);

    const {
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
    } = useVoiceLive({
        voice: liveVoice,
        model: liveModel,
        mode: voiceMode || 'engine',
        // Use the dedicated voice engine model setting (empty = server default).
        // This avoids loading a second Ollama model just because the chat
        // dropdown has a different model selected.
        engineModel: voiceEngineModel || undefined,
        engineSttModel: voiceEngineSttModel || undefined,
        engineTtsMode: voiceEngineTtsMode || 'native-audio-repeat',
        engineTtsModel: voiceEngineTtsModel || undefined,
        playbackSpeed: voicePlaybackSpeed || 1.0,
        onUserTranscript: (text) => { fullUserTextRef.current += text; },
        onAssistantTranscript: (text) => { fullAssistantTextRef.current += text; },
        onTurnComplete: () => { flushTurn(); },
        onSessionEnd: () => { flushTurn(); },
    });

    const isActive = state === 'active';

    const handleConnectionToggle = useCallback(() => {
        if (state === 'active' || state === 'connecting') {
            disconnect();
            flushTurn();
        } else {
            connect(liveVoice, liveModel);
        }
    }, [state, connect, disconnect, liveVoice, liveModel, flushTurn]);

    const handleMicToggle = useCallback(() => {
        if (muted) {
            unmute();
        } else {
            mute();
        }
    }, [muted, mute, unmute]);

    // Cmd+M keyboard shortcut for mute/unmute
    useEffect(() => {
        const onKeyDown = (e: KeyboardEvent) => {
            if (e.metaKey && e.key === 'u') {
                e.preventDefault();
                if (state === 'active') {
                    if (muted) unmute();
                    else mute();
                }
            }
        };
        window.addEventListener('keydown', onKeyDown);
        return () => window.removeEventListener('keydown', onKeyDown);
    }, [state, muted, mute, unmute]);

    if (!speechEnabled) return null;

    // Visual state
    let indicatorColor = 'var(--color-text-tertiary)';
    let indicatorAnimation = '';
    let stateLabel = 'Voice idle';
    if (state === 'connecting') {
        indicatorColor = 'var(--color-warning)';
        indicatorAnimation = 'pulse 1s ease-in-out infinite';
        stateLabel = 'Connecting…';
    } else if (isActive && muted) {
        indicatorColor = 'var(--color-error)';
        stateLabel = 'Muted';
    } else if (isActive) {
        indicatorColor = jarvisSpeaking ? 'var(--color-warning)' : 'var(--color-success)';
        indicatorAnimation = 'pulse 2s ease-in-out infinite';
        stateLabel = jarvisSpeaking ? 'Jarvis speaking' : 'Listening';
    }

    const transcript = assistantText
        ? assistantText.slice(-200)
        : userText
            ? userText.slice(-200)
            : '';

    return (
        <div
            className="fixed bottom-6 right-6 z-50 flex flex-col items-end gap-3"
            style={{ pointerEvents: 'none' }}
        >
            {/* Transcript bubble */}
            {isActive && transcript && (
                <div
                    className="rounded-2xl px-4 py-3 text-sm leading-relaxed max-w-[360px] shadow-lg"
                    style={{
                        background: 'var(--color-bg-secondary)',
                        border: '1px solid var(--color-border)',
                        color: 'var(--color-text-primary)',
                        pointerEvents: 'auto',
                    }}
                >
                    {transcript}
                </div>
            )}

            {/* Main panel */}
            <div
                className="flex items-center gap-4 rounded-2xl px-5 py-4 shadow-xl"
                style={{
                    background: 'var(--color-bg-secondary)',
                    border: '1px solid var(--color-border)',
                    pointerEvents: 'auto',
                }}
            >
                {/* Indicator dot + label */}
                <div className="flex items-center gap-2.5 min-w-0">
                    <span
                        className="w-3 h-3 rounded-full shrink-0"
                        style={{
                            background: indicatorColor,
                            animation: indicatorAnimation || undefined,
                            boxShadow: isActive
                                ? `0 0 ${Math.round(micLevel * 30)}px ${Math.round(micLevel * 15)}px ${indicatorColor}`
                                : undefined,
                            transition: 'box-shadow 0.1s, background 0.2s',
                        }}
                    />
                    <span
                        className="text-sm font-medium truncate"
                        style={{ color: 'var(--color-text-secondary)', maxWidth: '120px' }}
                    >
                        {stateLabel}
                    </span>
                </div>

                {/* Mic toggle — only shown when connected */}
                {isActive && (
                    <button
                        onClick={handleMicToggle}
                        className="p-3 rounded-xl transition-all shrink-0 cursor-pointer"
                        style={{
                            background: muted ? 'var(--color-error)' : 'var(--color-success)',
                            color: 'white',
                        }}
                        title={muted ? 'Unmute microphone (⌘M)' : 'Mute microphone (⌘M)'}
                    >
                        {muted ? <MicOff size={20} /> : <Mic size={20} />}
                    </button>
                )}

                {/* Connect / disconnect */}
                <button
                    onClick={handleConnectionToggle}
                    disabled={state === 'connecting'}
                    className="p-3 rounded-xl transition-all shrink-0 cursor-pointer disabled:opacity-50"
                    style={{
                        background: isActive ? 'var(--color-bg-tertiary)' : 'var(--color-accent)',
                        color: isActive ? 'var(--color-text-secondary)' : 'white',
                    }}
                    title={isActive ? 'Disconnect voice channel' : 'Connect voice channel'}
                >
                    {isActive ? <PhoneOff size={20} /> : <Phone size={20} />}
                </button>
            </div>
        </div>
    );
}
