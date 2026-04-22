/**
 * HudPanel — consistent bordered / glowing container for HUD widgets.
 *
 * Every HUD panel shares this visual chrome so the layout reads as a
 * single cohesive interface rather than a grid of unrelated cards.
 */

import { ReactNode } from 'react';

export function HudPanel({
    title,
    accent,
    children,
    right,
    dense,
}: {
    title?: string;
    accent?: string;
    children: ReactNode;
    right?: ReactNode;
    dense?: boolean;
}) {
    const color = accent ?? '#22d3ee';
    return (
        <div
            className="relative rounded-lg overflow-hidden flex flex-col h-full min-h-0"
            style={{
                background: 'linear-gradient(180deg, rgba(12,22,32,0.85), rgba(6,12,20,0.85))',
                border: `1px solid ${color}33`,
                boxShadow: `0 0 0 1px ${color}11 inset, 0 0 24px ${color}12`,
            }}
        >
            {/* Corner ticks */}
            <Corner pos="tl" color={color} />
            <Corner pos="tr" color={color} />
            <Corner pos="bl" color={color} />
            <Corner pos="br" color={color} />

            {title && (
                <div
                    className="flex items-center justify-between px-3 py-1.5 text-[10px] uppercase tracking-[0.2em]"
                    style={{ color: `${color}cc`, borderBottom: `1px solid ${color}22` }}
                >
                    <span>{title}</span>
                    {right}
                </div>
            )}
            <div className={`flex-1 min-h-0 ${dense ? 'p-2' : 'p-3'}`}>{children}</div>
        </div>
    );
}

function Corner({ pos, color }: { pos: 'tl' | 'tr' | 'bl' | 'br'; color: string }) {
    const size = 10;
    const borders: Record<typeof pos, React.CSSProperties> = {
        tl: { top: 0, left: 0, borderTop: `1px solid ${color}`, borderLeft: `1px solid ${color}` },
        tr: { top: 0, right: 0, borderTop: `1px solid ${color}`, borderRight: `1px solid ${color}` },
        bl: { bottom: 0, left: 0, borderBottom: `1px solid ${color}`, borderLeft: `1px solid ${color}` },
        br: { bottom: 0, right: 0, borderBottom: `1px solid ${color}`, borderRight: `1px solid ${color}` },
    };
    return (
        <span
            aria-hidden
            style={{
                position: 'absolute',
                width: size,
                height: size,
                pointerEvents: 'none',
                ...borders[pos],
            }}
        />
    );
}
