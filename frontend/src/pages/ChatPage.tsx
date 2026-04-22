/**
 * ChatPage — the primary landing surface.
 *
 * As of the Jarvis revamp, `/` renders the `JarvisHudPage` instead of
 * the classic chat layout.  The classic `ChatArea` + `SystemPanel` are
 * still reachable from inside the HUD (via `ChatDock`) and remain
 * importable if the HUD is ever feature-flagged off.
 */

import { JarvisHudPage } from '../components/hud/JarvisHudPage';

export function ChatPage() {
  return <JarvisHudPage />;
}
