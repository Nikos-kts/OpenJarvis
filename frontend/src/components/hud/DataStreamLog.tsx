/**
 * DataStreamLog — scrolling marquee of live bus events.
 */

import { useEffect, useRef } from 'react';
import { JarvisStreamEvent } from '../../lib/jarvis-api';

const KIND_COLORS: Record<string, string> = {
    AGENT_TURN_START: '#22d3ee',
    AGENT_TURN_END: '#22d3ee',
    INFERENCE_START: '#a78bfa',
    INFERENCE_END: '#a78bfa',
    TOOL_CALL_START: '#f59e0b',
    TOOL_CALL_END: '#f59e0b',
    AGENT_TICK_START: '#34d399',
    AGENT_TICK_END: '#34d399',
};

export function DataStreamLog({ events }: { events: JarvisStreamEvent[] }) {
    const ref = useRef<HTMLDivElement>(null);

    useEffect(() => {
        if (ref.current) ref.current.scrollTop = ref.current.scrollHeight;
    }, [events]);

    if (events.length === 0) {
        return (
            <div className="text-[11px] opacity-50 p-2 text-center" style={{ color: '#22d3ee' }}>
                awaiting telemetry…
            </div>
        );
    }

    return (
        <div ref={ref} className="h-full min-h-0 overflow-y-auto font-mono text-[10px] leading-relaxed">
            {events.map((e, i) => {
                const color = KIND_COLORS[e.kind] ?? '#22d3ee';
                const label = labelFor(e);
                return (
                    <div key={i} className="flex items-start gap-2 py-0.5">
                        <span style={{ color: `${color}66`, minWidth: 44 }}>{fmtTime(e.ts)}</span>
                        <span style={{ color, minWidth: 100 }}>{e.kind.toLowerCase()}</span>
                        <span className="flex-1 truncate" style={{ color: '#a4d5e0' }}>
                            {label}
                        </span>
                    </div>
                );
            })}
        </div>
    );
}

function labelFor(e: JarvisStreamEvent): string {
    const d = e.data;
    if (!d) return '';
    const parts: string[] = [];
    for (const k of ['agent', 'tool', 'model', 'kind', 'sub_agent', 'mode']) {
        const v = (d as Record<string, unknown>)[k];
        if (typeof v === 'string' && v) parts.push(`${k}=${v}`);
    }
    return parts.join(' · ');
}

function fmtTime(ts: number): string {
    const d = new Date(ts * (ts > 1e12 ? 1 : 1000));
    return d.toTimeString().slice(0, 8);
}
