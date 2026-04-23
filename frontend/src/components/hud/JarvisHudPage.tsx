/**
 * JarvisHudPage — Iron-Man-style HUD for the primary Jarvis agent.
 *
 * Layout (per user reference mockup):
 *
 *   ┌─────────────────────── TopStatusBar ───────────────────────┐
 *   ├──────────┬───────────┬───────────┬─────────────────────────┤
 *   │ Identity │ Neural    │ Perf.     │                         │
 *   │          │ Core      │           │  Right tabs panel       │
 *   ├──────────┴───────────┼───────────┤  · Capabilities         │
 *   │                      │ Telemetry │  · Delegation           │
 *   │  Direct Channel      ├───────────┤                         │
 *   │                      │ VoiceOrb  │                         │
 *   └──────────────────────┴───────────┴─────────────────────────┘
 *
 * Right-column tab order is fixed; each tab's visibility is persisted
 * via ``/v1/jarvis/hud/prefs`` alongside tools/skills.
 */

import { AlertTriangle } from 'lucide-react';
import { useMemo } from 'react';
import { useNavigate } from 'react-router';
import { useJarvisDelegations, useJarvisState, useJarvisStream } from '../../lib/useJarvis';
import { AgentCoreViz, Mood } from './AgentCoreViz';
import { CapabilitiesLabPanel } from './CapabilitiesLabPanel';
import { ChatDock } from './ChatDock';
import { DataStreamLog } from './DataStreamLog';
import { DelegateQuickAction } from './DelegateQuickAction';
import { DelegationTimeline } from './DelegationTimeline';
import { HudPanel } from './HudPanel';
import { HudShell } from './HudShell';
import { IdentityCard } from './IdentityCard';
import { PerformanceRings } from './PerformanceRings';
import { RightTabsPanel } from './RightTabsPanel';
import { TopStatusBar } from './TopStatusBar';


export function JarvisHudPage() {
    const { state, error, everLoaded } = useJarvisState(1500);
    const { events, connected, subscribe } = useJarvisStream(120);
    const { records } = useJarvisDelegations(subscribe, 20);
    const navigate = useNavigate();

    const mood = useMemo<Mood>(() => deriveMood(events), [events]);
    const tokens = (state?.metrics.total_tokens_in ?? 0) + (state?.metrics.total_tokens_out ?? 0);

    const isFatalError = Boolean(error && !everLoaded && /5\d{2}/.test(error.message));
    if (isFatalError) {
        return (
            <div className="h-full w-full flex items-center justify-center p-8" style={{ background: '#05080d', color: '#d7f6ff' }}>
                <div
                    className="max-w-md text-center rounded-lg p-6"
                    style={{ border: '1px solid #f59e0b55', background: 'rgba(20,14,0,0.6)' }}
                >
                    <AlertTriangle size={32} className="mx-auto mb-3" style={{ color: '#f59e0b' }} />
                    <div className="text-lg font-semibold mb-1">Jarvis primary agent is offline</div>
                    <p className="text-sm opacity-80 mb-4">
                        The Jarvis HUD requires <code className="font-mono">jarvis.enabled = true</code> in your
                        config. Enable it and restart the server, or continue with the classic chat surface.
                    </p>
                    <button
                        className="px-3 py-1.5 rounded text-xs cursor-pointer"
                        style={{ background: '#22d3ee22', border: '1px solid #22d3ee66', color: '#e6fcff' }}
                        onClick={() => navigate('/settings')}
                    >
                        Open Settings
                    </button>
                </div>
            </div>
        );
    }

    return (
        <HudShell
            top={<TopStatusBar state={state} connected={connected} error={error} />}
            body={
                <div
                    className="grid h-full min-h-0 gap-3"
                    style={{
                        gridTemplateColumns:
                            'minmax(0, 1fr) minmax(0, 1fr) minmax(0, 1fr) minmax(320px, 1.2fr)',
                        gridTemplateRows: 'minmax(0, 0.85fr) minmax(0, 2fr)',
                    }}
                >
                    {/* Row 1 · three cards across cols 1-3 */}
                    <div className="min-h-0 h-full" style={{ gridColumn: '1', gridRow: '1' }}>
                        <HudPanel title="Identity" dense>
                            <IdentityCard state={state} mood={mood} />
                        </HudPanel>
                    </div>
                    <div className="min-h-0 h-full" style={{ gridColumn: '2', gridRow: '1' }}>
                        <HudPanel title="Neural Core" dense>
                            <AgentCoreViz mood={mood} tokens={tokens} />
                        </HudPanel>
                    </div>
                    <div className="min-h-0 h-full" style={{ gridColumn: '3', gridRow: '1' }}>
                        <HudPanel title="Performance" dense>
                            <PerformanceRings state={state} />
                        </HudPanel>
                    </div>

                    {/* Col 4 · full-height tabs panel (Capabilities | Delegation) */}
                    <div className="min-h-0 h-full" style={{ gridColumn: '4', gridRow: '1 / span 2' }}>
                        <RightTabsPanel
                            capabilities={<CapabilitiesLabPanel state={state} />}
                            delegation={
                                <div className="flex flex-col h-full min-h-0 gap-2">
                                    <div className="flex items-center justify-end shrink-0">
                                        <DelegateQuickAction subAgents={state?.sub_agents ?? []} />
                                    </div>
                                    <div className="flex-1 min-h-0">
                                        <DelegationTimeline records={records} />
                                    </div>
                                </div>
                            }
                        />
                    </div>

                    {/* Row 2 · Direct Channel spans cols 1-2 */}
                    <div className="min-h-0 h-full" style={{ gridColumn: '1 / span 2', gridRow: '2' }}>
                        <ChatDock />
                    </div>

                    {/* Row 2 · col 3 — Telemetry on top, Voice Orb below */}
                    <div
                        className="min-h-0 h-full grid gap-3"
                        style={{
                            gridColumn: '3',
                            gridRow: '2',
                            gridTemplateRows: 'minmax(0, 1fr) minmax(0, 1fr)',
                        }}
                    >
                        <HudPanel title="Telemetry" dense right={<StreamDot connected={connected} />}>
                            <DataStreamLog events={events} />
                        </HudPanel>
                        <div className="min-h-0">
                            <HudPanel title="Voice" dense>
                                <div
                                    className="flex items-center justify-center w-full h-full text-xs"
                                    style={{ color: 'var(--color-text-tertiary)' }}
                                >
                                    voice pipeline offline
                                </div>
                            </HudPanel>
                        </div>
                    </div>
                </div>
            }
        />
    );
}

function StreamDot({ connected }: { connected: boolean }) {
    const color = connected ? '#22d3ee' : '#6b7280';
    return (
        <span
            className="inline-block w-1.5 h-1.5 rounded-full"
            style={{ background: color, boxShadow: `0 0 8px ${color}` }}
        />
    );
}

function deriveMood(events: { kind: string; ts: number }[]): Mood {
    for (let i = events.length - 1; i >= 0 && i >= events.length - 10; i--) {
        const k = events[i].kind;
        if (k === 'TOOL_CALL_START') return 'tool';
        if (k === 'TOOL_CALL_END') return 'thinking';
        if (k === 'INFERENCE_START') return 'thinking';
        if (k === 'INFERENCE_END') return 'speaking';
        if (k === 'AGENT_TURN_START') return 'thinking';
        if (k === 'AGENT_TURN_END') return 'idle';
    }
    return 'idle';
}
