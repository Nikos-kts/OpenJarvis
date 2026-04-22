/**
 * ChatDock — compact chat thread + existing InputArea, docked at the
 * bottom of the HUD.
 *
 * Re-uses `MessageBubble`, `InputArea`, and `StreamingDots` from the
 * existing chat module so no chat logic is re-implemented.  The Zustand
 * store continues to drive messages/streamState exactly as before.
 */

import { useEffect, useRef } from 'react';
import { useAppStore } from '../../lib/store';
import { InputArea } from '../Chat/InputArea';
import { MessageBubble } from '../Chat/MessageBubble';
import { StreamingDots } from '../Chat/StreamingDots';

export function ChatDock() {
    const messages = useAppStore((s) => s.messages);
    const streamState = useAppStore((s) => s.streamState);
    const scrollRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }, [messages, streamState.content]);

    const accent = '#22d3ee';

    return (
        <div
            className="flex flex-col h-full min-h-0 rounded-lg"
            style={{
                border: `1px solid ${accent}33`,
                background: 'rgba(8, 14, 22, 0.85)',
            }}
        >
            <div className="flex items-center justify-between px-3 py-1.5 shrink-0" style={{ borderBottom: `1px solid ${accent}22` }}>
                <span className="text-[10px] uppercase tracking-[0.25em]" style={{ color: `${accent}bb` }}>
                    Direct Channel
                </span>
                <span className="text-[10px]" style={{ color: `${accent}88` }}>
                    {messages.length} msg
                </span>
            </div>

            <div ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto px-3 py-2">
                {messages.length === 0 && !streamState.isStreaming ? (
                    <div className="text-[11px] text-center py-6" style={{ color: `${accent}88` }}>
                        Ready, Sir. How may I assist?
                    </div>
                ) : (
                    <>
                        {messages.map((m) => (
                            <MessageBubble key={m.id} message={m} />
                        ))}
                        {streamState.isStreaming && <StreamingDots phase={streamState.phase ?? ''} />}
                    </>
                )}
            </div>

            <div className="shrink-0" style={{ borderTop: `1px solid ${accent}22` }}>
                <InputArea />
            </div>
        </div>
    );
}
