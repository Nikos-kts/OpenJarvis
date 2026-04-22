/**
 * RightTabsPanel — stacked-tab container for the HUD's right column.
 *
 * Tabs (fixed order): Capabilities | Delegation Timeline.
 * Visibility of each tab is persisted via ``/v1/jarvis/hud/prefs``;
 * hidden tabs don't render and the first visible tab becomes active.
 */

import { Hammer, Workflow } from 'lucide-react';
import { ReactNode, useEffect, useMemo, useState } from 'react';
import { JarvisHudPrefs, getJarvisHudPrefs } from '../../lib/jarvis-api';

const ACCENT = '#22d3ee';

export type RightTabKey = 'capabilities' | 'delegation';

interface TabDef {
    key: RightTabKey;
    label: string;
    icon: ReactNode;
    render: () => ReactNode;
    headerRight?: ReactNode;
}

const FIXED_ORDER: RightTabKey[] = ['capabilities', 'delegation'];

export function RightTabsPanel({
    capabilities,
    delegation,
}: {
    capabilities: ReactNode;
    delegation: ReactNode;
}) {
    const [prefs, setPrefs] = useState<JarvisHudPrefs | null>(null);
    const [active, setActive] = useState<RightTabKey>('capabilities');

    useEffect(() => {
        let cancelled = false;
        getJarvisHudPrefs()
            .then((p) => {
                if (!cancelled) setPrefs(p);
            })
            .catch(() => {
                /* fall back to defaults */
            });
        return () => {
            cancelled = true;
        };
    }, []);

    const tabs: TabDef[] = useMemo(
        () => [
            {
                key: 'capabilities',
                label: 'Capabilities',
                icon: <Hammer size={12} />,
                render: () => capabilities,
            },
            {
                key: 'delegation',
                label: 'Delegation',
                icon: <Workflow size={12} />,
                render: () => delegation,
            },
        ],
        [capabilities, delegation],
    );

    const visibleTabs = useMemo(() => {
        const vis = prefs?.tabs_visible ?? { capabilities: true, delegation: true };
        return FIXED_ORDER.filter((k) => vis[k]).map((k) => tabs.find((t) => t.key === k)!).filter(Boolean);
    }, [prefs, tabs]);

    useEffect(() => {
        if (visibleTabs.length === 0) return;
        if (!visibleTabs.some((t) => t.key === active)) {
            setActive(visibleTabs[0].key);
        }
    }, [visibleTabs, active]);

    const current = visibleTabs.find((t) => t.key === active) ?? visibleTabs[0];

    return (
        <div
            className="flex flex-col h-full min-h-0 rounded-lg overflow-hidden"
            style={{
                border: `1px solid ${ACCENT}33`,
                background: 'rgba(8, 14, 22, 0.85)',
            }}
        >
            <div
                className="flex items-center gap-0.5 px-2 py-1.5 shrink-0"
                style={{ borderBottom: `1px solid ${ACCENT}22` }}
            >
                <div className="flex items-center gap-0.5 flex-1 min-w-0 overflow-x-auto">
                    {visibleTabs.map((t) => (
                        <button
                            key={t.key}
                            onClick={() => setActive(t.key)}
                            className="flex items-center gap-1 px-2 py-1 rounded text-[10px] uppercase tracking-[0.2em] cursor-pointer transition-colors whitespace-nowrap"
                            style={{
                                background: active === t.key ? `${ACCENT}22` : 'transparent',
                                border: `1px solid ${active === t.key ? ACCENT : `${ACCENT}22`}`,
                                color: active === t.key ? '#e6fcff' : `${ACCENT}cc`,
                            }}
                        >
                            {t.icon}
                            {t.label}
                        </button>
                    ))}
                </div>
                {current?.headerRight && <div className="ml-2 shrink-0">{current.headerRight}</div>}
            </div>

            <div className="flex-1 min-h-0 p-2 overflow-hidden">
                {current ? current.render() : <EmptyTabs />}
            </div>
        </div>
    );
}

function EmptyTabs() {
    return (
        <div className="h-full flex items-center justify-center text-[11px] opacity-60" style={{ color: ACCENT }}>
            all tabs hidden
        </div>
    );
}
