/**
 * Typed client for `/v1/jarvis/*` endpoints.
 *
 * The HUD polls `getJarvisState()` at ~1 Hz and subscribes to
 * `openJarvisStream()` for the SSE feed of live bus events.
 */

import { getBase } from './api';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface JarvisPersonaSnapshot {
    name: string;
    honorific: string;
    voice_id: string;
    tts_backend: string;
    soul_excerpt: string;
    memory_excerpt: string;
    user_excerpt: string;
    soul_tokens: number;
    memory_tokens: number;
    user_tokens: number;
    files: Record<string, { path: string; exists: boolean; size_bytes: number; mtime: number }>;
    updated_at: number;
}

export interface JarvisMetrics {
    total_turns: number;
    total_tokens_in: number;
    total_tokens_out: number;
    total_delegations: number;
    total_errors: number;
    uptime_started_at: number;
}

export interface JarvisSubAgent {
    id: string | null;
    name: string | null;
    agent_type: string | null;
    status: string | null;
    model: string | null;
}

export interface JarvisState {
    agent_id: string;
    model: string;
    persona: JarvisPersonaSnapshot;
    metrics: JarvisMetrics;
    uptime_seconds: number;
    tools: string[];
    sub_agents: JarvisSubAgent[];
    active_skills: string[];
    delegation_enabled: boolean;
}

export interface DelegationRecord {
    id: string;
    sub_agent: string;
    brief: string;
    mode: 'sync' | 'async';
    status: 'running' | 'completed' | 'failed' | 'aborted';
    started_at: number;
    ended_at: number;
    result_summary: string;
    latency_ms: number;
    error: string;
}

export interface JarvisEvent {
    kind: string;
    payload: Record<string, unknown>;
    ts: number;
}

export interface JarvisStreamEvent {
    kind: string;
    ts: number;
    data: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// REST
// ---------------------------------------------------------------------------

async function jget<T>(path: string): Promise<T> {
    const res = await fetch(`${getBase()}${path}`);
    if (!res.ok) throw new Error(`${path}: ${res.status}`);
    return (await res.json()) as T;
}

export const getJarvisState = () => jget<JarvisState>('/v1/jarvis/state');

export const getJarvisDelegations = (limit = 20) =>
    jget<{ items: DelegationRecord[]; count: number }>(`/v1/jarvis/delegations?limit=${limit}`);

export const getJarvisEvents = (limit = 50) =>
    jget<{ items: JarvisEvent[] }>(`/v1/jarvis/events?limit=${limit}`);

export async function reloadJarvisPersona(): Promise<void> {
    const res = await fetch(`${getBase()}/v1/jarvis/reload`, { method: 'POST' });
    if (!res.ok) throw new Error(`reload: ${res.status}`);
}

export async function abortJarvisDelegation(id: string): Promise<void> {
    const res = await fetch(`${getBase()}/v1/jarvis/delegations/${encodeURIComponent(id)}/abort`, {
        method: 'POST',
    });
    if (!res.ok) throw new Error(`abort: ${res.status}`);
}

// ---------------------------------------------------------------------------
// Skills
// ---------------------------------------------------------------------------

export interface JarvisSkill {
    name: string;
    active: boolean;
    description?: string;
    version?: string;
    author?: string;
    tags?: string[];
    steps?: number;
    user_invocable?: boolean;
}

export const getJarvisSkills = () =>
    jget<{ items: JarvisSkill[]; active: string[] }>('/v1/jarvis/skills');

export async function toggleJarvisSkill(
    name: string,
): Promise<{ ok: boolean; name: string; state: string; active: string[] }> {
    const res = await fetch(`${getBase()}/v1/jarvis/skills/${encodeURIComponent(name)}/toggle`, {
        method: 'POST',
    });
    if (!res.ok) throw new Error(`skill toggle: ${res.status}`);
    return res.json();
}

// ---------------------------------------------------------------------------
// Tools (Capabilities Lab)
// ---------------------------------------------------------------------------

export interface JarvisTool {
    name: string;
    description: string;
    category: string;
    latency_estimate: number;
    active: boolean;
    sensitive?: boolean;
    sensitive_reason?: string;
}

export const getJarvisTools = () =>
    jget<{ items: JarvisTool[]; active: string[] }>('/v1/jarvis/tools');

export async function toggleJarvisTool(
    name: string,
): Promise<{ ok: boolean; name: string; state: string; active: string[] }> {
    const res = await fetch(`${getBase()}/v1/jarvis/tools/${encodeURIComponent(name)}/toggle`, {
        method: 'POST',
    });
    if (!res.ok) throw new Error(`tool toggle: ${res.status}`);
    return res.json();
}

// ---------------------------------------------------------------------------
// Sub-agent delegation allowlist
// ---------------------------------------------------------------------------

export interface JarvisDelegatableAgent {
    id: string | null;
    name: string | null;
    agent_type: string | null;
    status: string | null;
    model: string | null;
    active: boolean;
}

export const getJarvisAgents = () =>
    jget<{ items: JarvisDelegatableAgent[]; active: string[]; unrestricted: boolean }>(
        '/v1/jarvis/agents',
    );

export async function toggleJarvisAgent(
    id: string,
): Promise<{ ok: boolean; id: string; state: string; active: string[] }> {
    const res = await fetch(`${getBase()}/v1/jarvis/agents/${encodeURIComponent(id)}/toggle`, {
        method: 'POST',
    });
    if (!res.ok) throw new Error(`agent toggle: ${res.status}`);
    return res.json();
}

// ---------------------------------------------------------------------------
// HUD preferences (tab + section visibility)
// ---------------------------------------------------------------------------

export interface JarvisHudPrefs {
    tabs_visible: {
        capabilities: boolean;
        delegation: boolean;
    };
    sections_visible: {
        tools: boolean;
        skills: boolean;
        agents: boolean;
    };
}

export const getJarvisHudPrefs = () => jget<JarvisHudPrefs>('/v1/jarvis/hud/prefs');

export async function setJarvisHudPrefs(prefs: JarvisHudPrefs): Promise<JarvisHudPrefs> {
    const res = await fetch(`${getBase()}/v1/jarvis/hud/prefs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(prefs),
    });
    if (!res.ok) throw new Error(`hud prefs: ${res.status}`);
    return res.json();
}

// ---------------------------------------------------------------------------
// Manual delegation (HUD quick action)
// ---------------------------------------------------------------------------

export interface DelegateResult {
    ok: boolean;
    content: string;
    metadata: Record<string, unknown>;
}

export async function delegateManually(body: {
    agent: string;
    brief: string;
    mode: 'sync' | 'async';
}): Promise<DelegateResult> {
    const res = await fetch(`${getBase()}/v1/jarvis/delegate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    if (!res.ok) {
        const text = await res.text().catch(() => '');
        throw new Error(`delegate: ${res.status} ${text}`);
    }
    return res.json();
}

// ---------------------------------------------------------------------------
// SSE
// ---------------------------------------------------------------------------

/**
 * Open the Jarvis SSE stream. Returns a close() function.
 *
 * Filters out the initial "hello" greeting and keep-alive pings so the
 * callback only sees real bus events.
 */
export function openJarvisStream(onEvent: (e: JarvisStreamEvent) => void): () => void {
    const src = new EventSource(`${getBase()}/v1/jarvis/stream`);
    src.onmessage = (ev) => {
        if (!ev.data) return;
        try {
            const parsed = JSON.parse(ev.data) as JarvisStreamEvent;
            if (parsed.kind === 'hello') return;
            onEvent(parsed);
        } catch {
            /* ignore malformed */
        }
    };
    src.onerror = () => {
        // Let EventSource auto-reconnect; just log once in dev.
        if (import.meta.env.DEV) console.debug('[jarvis stream] error, will retry');
    };
    return () => src.close();
}
