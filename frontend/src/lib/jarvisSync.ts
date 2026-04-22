import type { JarvisPrimaryConfig } from './api';
import { useAppStore } from './store';

/**
 * Mirror the Jarvis backend config into the legacy `settings` store that
 * VoicePanel and the chat composer still read from. The Jarvis config in
 * the database is the single source of truth; this keeps the ambient
 * client-side voice runtime in sync until those callers are migrated.
 */
export function syncJarvisConfigToSettings(
    next: JarvisPrimaryConfig | null | undefined,
    _prev?: JarvisPrimaryConfig | null,
): void {
    if (!next) return;
    const voice = (next.voice ?? {}) as Record<string, unknown>;
    const patch: Record<string, unknown> = {};

    if (typeof voice.enabled === 'boolean') patch.speechEnabled = voice.enabled;
    if (typeof voice.tts_voice === 'string' && voice.tts_voice)
        patch.liveVoice = voice.tts_voice;
    if (typeof voice.live_model === 'string' && voice.live_model) {
        patch.liveModel = voice.live_model;
        patch.voiceEngineSttModel = voice.live_model;
    }
    if (typeof voice.realtime === 'boolean') {
        patch.voiceMode = voice.realtime ? 'gemini' : 'engine';
    }

    if (Object.keys(patch).length > 0) {
        try {
            useAppStore.getState().updateSettings(patch);
        } catch {
            /* store may not be ready during first render */
        }
    }
}
