/**
 * React hooks for the Jarvis HUD.
 *
 * - `useJarvisState(pollMs)` — 1 Hz polling of `/v1/jarvis/state`.
 * - `useJarvisStream(cap)`   — live SSE event buffer (ring of `cap`).
 * - `useJarvisDelegations()` — recent delegation records, auto-refresh
 *   when a `jarvis_delegation_*` event is observed.
 */

import { useEffect, useRef, useState } from 'react';
import {
    DelegationRecord,
    JarvisState,
    JarvisStreamEvent,
    getJarvisDelegations,
    getJarvisState,
    openJarvisStream,
} from './jarvis-api';

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

export function useJarvisState(pollMs = 1500) {
    const [state, setState] = useState<JarvisState | null>(null);
    const [error, setError] = useState<Error | null>(null);
    const [everLoaded, setEverLoaded] = useState(false);
    const failCountRef = useRef(0);
    // Threshold: surface error only after this many consecutive failures.
    // Avoids flashing the offline fallback during cold start, brief network
    // hiccups or server reloads.
    const FAIL_THRESHOLD = 3;

    useEffect(() => {
        let cancelled = false;
        let timer: ReturnType<typeof setTimeout> | null = null;

        const tick = async () => {
            try {
                const s = await getJarvisState();
                if (!cancelled) {
                    failCountRef.current = 0;
                    setState(s);
                    setEverLoaded(true);
                    setError(null);
                }
            } catch (e) {
                if (!cancelled) {
                    failCountRef.current += 1;
                    if (failCountRef.current >= FAIL_THRESHOLD) {
                        setError(e as Error);
                    }
                    // Never clobber a previously-loaded state on transient errors
                }
            } finally {
                if (!cancelled) timer = setTimeout(tick, pollMs);
            }
        };
        tick();
        return () => {
            cancelled = true;
            if (timer) clearTimeout(timer);
        };
    }, [pollMs]);

    return { state, error, everLoaded };
}

// ---------------------------------------------------------------------------
// Stream — ring buffer of recent events
// ---------------------------------------------------------------------------

export function useJarvisStream(cap = 120) {
    const [events, setEvents] = useState<JarvisStreamEvent[]>([]);
    const [connected, setConnected] = useState(false);
    const listenersRef = useRef<Set<(e: JarvisStreamEvent) => void>>(new Set());

    useEffect(() => {
        setConnected(true);
        const close = openJarvisStream((e) => {
            setEvents((prev) => {
                const next = prev.length >= cap ? prev.slice(prev.length - cap + 1) : prev.slice();
                next.push(e);
                return next;
            });
            listenersRef.current.forEach((fn) => {
                try {
                    fn(e);
                } catch {
                    /* ignore listener errors */
                }
            });
        });
        return () => {
            setConnected(false);
            close();
        };
    }, [cap]);

    const subscribe = (fn: (e: JarvisStreamEvent) => void) => {
        listenersRef.current.add(fn);
        return () => {
            listenersRef.current.delete(fn);
        };
    };

    return { events, connected, subscribe };
}

// ---------------------------------------------------------------------------
// Delegations — refresh when a delegation event is seen
// ---------------------------------------------------------------------------

export function useJarvisDelegations(
    subscribe: (fn: (e: JarvisStreamEvent) => void) => () => void,
    limit = 20,
) {
    const [records, setRecords] = useState<DelegationRecord[]>([]);

    const refresh = async () => {
        try {
            const res = await getJarvisDelegations(limit);
            setRecords(res.items);
        } catch {
            /* silent */
        }
    };

    useEffect(() => {
        refresh();
        const unsub = subscribe((e) => {
            const kind = (e.data as { kind?: string } | undefined)?.kind ?? '';
            if (kind.startsWith('jarvis_delegation_')) refresh();
        });
        const t = setInterval(refresh, 10_000);
        return () => {
            unsub();
            clearInterval(t);
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [subscribe, limit]);

    return { records, refresh };
}
