/**
 * HudShell — root layout scaffold for the Jarvis HUD.
 *
 * Provides the top status-bar slot and a flexible body area.  The
 * concrete layout of the body (card grid, direct channel, voice orb,
 * right-hand tabs panel) is owned by ``JarvisHudPage`` so the shell
 * stays layout-agnostic.
 */

import { ReactNode } from 'react';

export function HudShell({ top, body }: { top: ReactNode; body: ReactNode }) {
    return (
        <div
            className="hud-shell h-full w-full overflow-hidden grid"
            style={{
                gridTemplateRows: 'auto 1fr',
                gap: '12px',
                padding: '12px',
                background:
                    'radial-gradient(1200px 800px at 80% -10%, rgba(34, 211, 238, 0.08), transparent 60%),' +
                    'radial-gradient(900px 700px at 0% 110%, rgba(34, 211, 238, 0.06), transparent 60%),' +
                    '#05080d',
                color: '#d7f6ff',
            }}
        >
            <div>{top}</div>
            <div className="min-h-0 overflow-hidden">{body}</div>
        </div>
    );
}
