/**
 * Banner shown at the top of the SettingsPage when at least one recent
 * config change requires a server restart to take effect.
 */
import { useConfigStore } from '../../lib/configStore';

export function RestartBanner() {
  const reasons = useConfigStore((s) => s.restartReasons);
  const dismiss = useConfigStore((s) => s.dismissRestartBanner);
  if (reasons.length === 0) return null;

  return (
    <div
      className="rounded-lg p-3 flex items-start justify-between gap-3"
      style={{
        background: 'var(--color-warn-bg, #fef3c7)',
        border: '1px solid var(--color-warn-border, #fbbf24)',
        color: 'var(--color-warn-fg, #92400e)',
      }}
    >
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium">
          Restart required for {reasons.length} recent change
          {reasons.length === 1 ? '' : 's'}
        </div>
        <p className="text-xs mt-0.5 opacity-90">
          The values were saved to <code>.openJarvis/config.toml</code>,
          but these changes can't be applied to a running server safely.
          Restart the backend to pick them up.
        </p>
        <ul className="mt-2 text-xs list-disc pl-5 space-y-0.5">
          {reasons.map((r) => (
            <li key={r} className="font-mono break-all">
              {r}
            </li>
          ))}
        </ul>
      </div>
      <button
        type="button"
        onClick={dismiss}
        className="text-xs px-2 py-1 rounded shrink-0"
        style={{
          background: 'transparent',
          border: '1px solid var(--color-warn-border, #fbbf24)',
          color: 'var(--color-warn-fg, #92400e)',
        }}
      >
        Dismiss
      </button>
    </div>
  );
}
