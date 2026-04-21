import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';
import {
  Bot,
  ChevronDown,
  ChevronUp,
  Cpu,
  Loader2,
  Mic,
  Radio,
  Send,
  Settings as SettingsIcon,
  Sparkles,
  Tag,
  Wrench,
  Zap,
} from 'lucide-react';
import {
  fetchAgentMessages,
  fetchJarvisPrimary,
  sendAgentMessage,
  type AgentMessage,
  type AgentToolCallEnd,
  type AgentToolCallStart,
  type JarvisPrimaryConfig,
  type JarvisPrimaryRecord,
} from '../lib/api';
import { syncJarvisConfigToSettings } from '../lib/jarvisSync';
import {
  HumanoidRobot,
  type RobotState,
} from '../components/Jarvis/HumanoidRobot';
import {
  JarvisSettingsDrawer,
  type TabKey,
} from '../components/Jarvis/JarvisSettingsDrawer';

interface ChatEntry {
  id: string;
  role: 'user' | 'assistant' | 'tool';
  content: string;
  toolName?: string;
  toolSuccess?: boolean;
  toolArgs?: string;
  toolResult?: string;
  pending?: boolean;
}

function toChatEntries(messages: AgentMessage[]): ChatEntry[] {
  const out: ChatEntry[] = [];
  for (const m of messages) {
    out.push({
      id: m.id || `${m.created_at}-${out.length}`,
      role: m.direction === 'user_to_agent' ? 'user' : 'assistant',
      content: m.content || '',
    });
    for (const tc of m.tool_calls || []) {
      out.push({
        id: `${m.id}-tc-${tc.tool}-${out.length}`,
        role: 'tool',
        content: '',
        toolName: tc.tool,
        toolSuccess: tc.success ?? true,
        toolArgs: tc.arguments,
        toolResult: tc.result,
      });
    }
  }
  return out;
}

export function JarvisPage() {
  const [record, setRecord] = useState<JarvisPrimaryRecord | null>(null);
  const [loadingRecord, setLoadingRecord] = useState(true);
  const [entries, setEntries] = useState<ChatEntry[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [settingsTab, setSettingsTab] = useState<TabKey | null>(null);
  const [transcriptOpen, setTranscriptOpen] = useState(true);
  const [robotOverride, setRobotOverride] = useState<RobotState | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  const refreshRecord = useCallback(async () => {
    try {
      const rec = await fetchJarvisPrimary();
      setRecord(rec);
      if (rec) syncJarvisConfigToSettings(rec.config);
    } catch (e) {
      toast.error('Could not load Jarvis', { description: String(e) });
    } finally {
      setLoadingRecord(false);
    }
  }, []);

  useEffect(() => {
    refreshRecord();
  }, [refreshRecord]);

  useEffect(() => {
    if (!record) return;
    fetchAgentMessages(record.id)
      .then((msgs) => setEntries(toChatEntries(msgs)))
      .catch(() => {
        /* non-fatal */
      });
  }, [record?.id]);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [entries.length, transcriptOpen]);

  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || !record || sending) return;
    setSending(true);
    setInput('');
    setTranscriptOpen(true);
    setRobotOverride('thinking');

    const userId = `local-u-${Date.now()}`;
    const assistantId = `local-a-${Date.now()}`;
    setEntries((prev) => [
      ...prev,
      { id: userId, role: 'user', content: text },
      { id: assistantId, role: 'assistant', content: '', pending: true },
    ]);

    const updateAssistant = (patch: Partial<ChatEntry>) => {
      setEntries((prev) =>
        prev.map((e) => (e.id === assistantId ? { ...e, ...patch } : e)),
      );
    };

    try {
      await sendAgentMessage(record.id, text, 'immediate', {
        onContentDelta: (_delta, full) => {
          setRobotOverride('speaking');
          updateAssistant({ content: full, pending: true });
        },
        onToolCallStart: (info: AgentToolCallStart) => {
          setRobotOverride('thinking');
          setEntries((prev) => {
            const withoutAssistant = prev.filter((e) => e.id !== assistantId);
            const assistant = prev.find((e) => e.id === assistantId);
            const toolEntry: ChatEntry = {
              id: `${assistantId}-tc-${info.tool}-${prev.length}`,
              role: 'tool',
              content: '',
              toolName: info.tool,
              toolArgs: info.arguments,
              pending: true,
            };
            return assistant
              ? [...withoutAssistant, toolEntry, assistant]
              : [...withoutAssistant, toolEntry];
          });
        },
        onToolCallEnd: (info: AgentToolCallEnd) => {
          setEntries((prev) =>
            prev.map((e) =>
              e.role === 'tool' && e.pending && e.toolName === info.tool
                ? {
                    ...e,
                    pending: false,
                    toolSuccess: info.success,
                    toolResult: info.result,
                  }
                : e,
            ),
          );
        },
        onDone: (full) => {
          updateAssistant({ content: full, pending: false });
        },
      });
    } catch (e) {
      updateAssistant({
        content: `Error: ${String(e)}`,
        pending: false,
      });
      toast.error('Jarvis failed to respond', { description: String(e) });
    } finally {
      setSending(false);
      setRobotOverride(null);
    }
  }, [input, record, sending]);

  const cfg: JarvisPrimaryConfig = useMemo(
    () => (record?.config ?? {}) as JarvisPrimaryConfig,
    [record],
  );

  const robotState: RobotState = robotOverride
    ? robotOverride
    : !record
    ? 'offline'
    : 'idle';

  if (loadingRecord) {
    return (
      <div className="flex items-center justify-center h-full w-full">
        <Loader2
          className="animate-spin"
          size={22}
          style={{ color: 'var(--color-accent)' }}
        />
      </div>
    );
  }

  if (!record) {
    return (
      <div className="flex flex-col items-center justify-center h-full w-full gap-3 px-6 text-center">
        <Bot size={32} style={{ color: 'var(--color-text-secondary)' }} />
        <h2 style={{ color: 'var(--color-text)' }}>Jarvis isn't online yet</h2>
        <p style={{ color: 'var(--color-text-secondary)', maxWidth: 420 }}>
          No managed agent of type <code>jarvis</code> was found. Enable{' '}
          <code>agent_manager.auto_bootstrap_jarvis</code> in your config, or
          create one via the Agents tab.
        </p>
      </div>
    );
  }

  const voiceEnabled = !!cfg.voice?.enabled;
  const wakeEnabled = !!cfg.wake?.enabled;
  const toolCount = cfg.tools?.length ?? 0;
  const personaTone = cfg.persona?.tone || '—';

  return (
    <div className="flex flex-col h-full w-full overflow-hidden">
      <header
        className="flex items-center justify-between px-5 py-3 shrink-0"
        style={{
          borderBottom: '1px solid var(--color-border)',
          background:
            'color-mix(in srgb, var(--color-bg-secondary) 60%, transparent)',
        }}
      >
        <div className="flex items-center gap-3 min-w-0">
          <div
            className="w-9 h-9 rounded-lg flex items-center justify-center"
            style={{
              background: 'var(--color-accent-subtle)',
              color: 'var(--color-accent)',
              boxShadow: '0 0 18px var(--color-accent-glow)',
            }}
          >
            <Sparkles size={18} />
          </div>
          <div className="min-w-0">
            <div
              className="text-sm font-medium truncate"
              style={{ color: 'var(--color-text)' }}
            >
              {record.name}
            </div>
            <div
              className="text-xs truncate"
              style={{ color: 'var(--color-text-tertiary)' }}
            >
              {cfg.description || 'Primary Jarvis orchestrator'}
            </div>
          </div>
        </div>
        <button
          onClick={() => setSettingsTab('persona')}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs cursor-pointer transition-colors"
          style={{
            background: 'var(--color-bg-tertiary)',
            color: 'var(--color-text-secondary)',
            border: '1px solid var(--color-border)',
          }}
          title="Configure Jarvis"
        >
          <SettingsIcon size={13} />
          Configure
        </button>
      </header>

      <div className="flex-1 flex overflow-hidden">
        <main className="flex-1 flex flex-col items-center justify-center relative overflow-y-auto px-4 py-6">
          <div
            className="absolute inset-0 pointer-events-none"
            style={{
              background:
                'radial-gradient(circle at 50% 35%, color-mix(in srgb, var(--color-accent) 8%, transparent) 0%, transparent 60%)',
            }}
          />

          <div className="relative flex flex-col items-center gap-5">
            <HumanoidRobot state={robotState} size={260} />
            <div className="flex flex-col items-center gap-1">
              <div
                className="text-xs uppercase tracking-widest"
                style={{ color: 'var(--color-text-tertiary)' }}
              >
                {robotState === 'offline'
                  ? 'offline'
                  : robotState === 'idle'
                  ? 'standing by'
                  : robotState}
              </div>
              <div
                className="text-sm font-medium"
                style={{ color: 'var(--color-text)' }}
              >
                {cfg.persona?.wake_phrase || cfg.wake?.phrase || 'Hey Jarvis'}
              </div>
            </div>
          </div>

          <div className="relative grid grid-cols-2 md:grid-cols-4 gap-3 mt-8 w-full max-w-3xl">
            <HudTile
              icon={<Mic size={14} />}
              label="Voice"
              value={
                voiceEnabled
                  ? `${cfg.voice?.tts_voice || 'Kore'}${
                      cfg.voice?.realtime ? ' · live' : ''
                    }`
                  : 'Muted'
              }
              active={voiceEnabled}
              onClick={() => setSettingsTab('voice')}
            />
            <HudTile
              icon={<Radio size={14} />}
              label="Wake"
              value={wakeEnabled ? cfg.wake?.mode || 'clap' : 'Off'}
              active={wakeEnabled}
              onClick={() => setSettingsTab('wake')}
            />
            <HudTile
              icon={<Cpu size={14} />}
              label="Model"
              value={cfg.model || '—'}
              active={!!cfg.model}
              onClick={() => setSettingsTab('advanced')}
            />
            <HudTile
              icon={<Wrench size={14} />}
              label="Tools"
              value={`${toolCount} allowed`}
              active={toolCount > 0}
              onClick={() => setSettingsTab('tools')}
            />
          </div>

          <div
            className="relative flex flex-wrap items-center justify-center gap-3 mt-5 text-[11px]"
            style={{ color: 'var(--color-text-tertiary)' }}
          >
            <span className="flex items-center gap-1.5">
              <Tag size={11} /> {personaTone}
            </span>
            <span>·</span>
            <span className="flex items-center gap-1.5">
              <Zap size={11} /> {cfg.preferred_engine || 'auto'} engine
            </span>
            <span>·</span>
            <span>{cfg.persona?.verbosity || 'balanced'}</span>
            <span>·</span>
            <span>max {cfg.max_turns ?? '—'} turns</span>
          </div>
        </main>

        <aside
          className="hidden lg:flex flex-col shrink-0 w-64 overflow-y-auto py-4 px-3 gap-1"
          style={{
            borderLeft: '1px solid var(--color-border)',
            background:
              'color-mix(in srgb, var(--color-bg-secondary) 40%, transparent)',
          }}
        >
          <div
            className="px-2 text-[10px] uppercase tracking-widest mb-2"
            style={{ color: 'var(--color-text-tertiary)' }}
          >
            Configuration
          </div>
          {(
            [
              { key: 'persona', label: 'Persona', detail: cfg.persona?.tone || 'default' },
              { key: 'intent', label: 'Intent', detail: cfg.intent?.policy || 'hybrid' },
              {
                key: 'voice',
                label: 'Voice',
                detail: voiceEnabled ? cfg.voice?.tts_voice || 'Kore' : 'off',
              },
              {
                key: 'wake',
                label: 'Wake',
                detail: wakeEnabled ? cfg.wake?.mode || 'clap' : 'off',
              },
              { key: 'tools', label: 'Tools', detail: `${toolCount} allowed` },
              {
                key: 'delegation',
                label: 'Delegation',
                detail:
                  cfg.delegation?.visible_to_brain || cfg.visible_to_brain
                    ? 'visible'
                    : 'private',
              },
              { key: 'advanced', label: 'Model & advanced', detail: cfg.model || '—' },
            ] as { key: TabKey; label: string; detail: string }[]
          ).map((row) => (
            <button
              key={row.key}
              onClick={() => setSettingsTab(row.key)}
              className="flex items-center justify-between gap-2 px-3 py-2 rounded-md text-left cursor-pointer transition-colors"
              style={{ background: 'transparent' }}
              onMouseEnter={(e) =>
                (e.currentTarget.style.background = 'var(--color-bg-tertiary)')
              }
              onMouseLeave={(e) =>
                (e.currentTarget.style.background = 'transparent')
              }
            >
              <span
                className="text-xs font-medium"
                style={{ color: 'var(--color-text)' }}
              >
                {row.label}
              </span>
              <span
                className="text-[11px] truncate max-w-[120px]"
                style={{ color: 'var(--color-text-tertiary)' }}
                title={row.detail}
              >
                {row.detail}
              </span>
            </button>
          ))}
        </aside>
      </div>

      <section
        className="shrink-0 flex flex-col"
        style={{
          borderTop: '1px solid var(--color-border)',
          background:
            'color-mix(in srgb, var(--color-bg-secondary) 50%, transparent)',
        }}
      >
        <button
          onClick={() => setTranscriptOpen((v) => !v)}
          className="flex items-center justify-between px-4 py-2 cursor-pointer"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          <span className="text-xs font-medium">
            Transcript · {entries.length}{' '}
            {entries.length === 1 ? 'entry' : 'entries'}
          </span>
          {transcriptOpen ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
        </button>

        {transcriptOpen && (
          <div
            ref={scrollRef}
            className="flex-1 overflow-y-auto px-5 pb-3 flex flex-col gap-3"
            style={{ maxHeight: '40vh' }}
          >
            {entries.length === 0 && (
              <div
                className="text-xs text-center py-3"
                style={{ color: 'var(--color-text-tertiary)' }}
              >
                Say hello. Jarvis is listening.
              </div>
            )}
            {entries.map((e) => (
              <ChatBubble key={e.id} entry={e} />
            ))}
          </div>
        )}

        <div className="px-4 pt-2 pb-3">
          <div
            className="flex items-end gap-2 p-2 rounded-xl"
            style={{
              background: 'var(--color-bg-secondary)',
              border: '1px solid var(--color-border)',
            }}
          >
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  handleSend();
                }
              }}
              placeholder="Ask Jarvis anything…"
              rows={1}
              className="flex-1 bg-transparent outline-none resize-none text-sm px-2 py-1 min-h-[24px] max-h-32"
              style={{ color: 'var(--color-text)' }}
            />
            <button
              onClick={handleSend}
              disabled={!input.trim() || sending}
              className="p-2 rounded-lg transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
              style={{
                background: 'var(--color-accent)',
                color: 'var(--color-bg)',
              }}
              title="Send"
            >
              {sending ? (
                <Loader2 size={16} className="animate-spin" />
              ) : (
                <Send size={16} />
              )}
            </button>
          </div>
        </div>
      </section>

      {settingsTab && record && (
        <JarvisSettingsDrawer
          agent={record}
          initialTab={settingsTab}
          onClose={() => setSettingsTab(null)}
          onUpdated={(next) => {
            setRecord((prev) => (prev ? { ...prev, config: next } : prev));
          }}
        />
      )}
    </div>
  );
}

function HudTile({
  icon,
  label,
  value,
  active,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="flex flex-col items-start gap-1 p-3 rounded-xl text-left cursor-pointer transition-all"
      style={{
        background: active
          ? 'color-mix(in srgb, var(--color-accent) 8%, var(--color-bg-secondary))'
          : 'var(--color-bg-secondary)',
        border: `1px solid ${
          active
            ? 'color-mix(in srgb, var(--color-accent) 30%, transparent)'
            : 'var(--color-border)'
        }`,
        color: 'var(--color-text)',
      }}
    >
      <div
        className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider"
        style={{
          color: active ? 'var(--color-accent)' : 'var(--color-text-tertiary)',
        }}
      >
        {icon}
        {label}
      </div>
      <div
        className="text-sm font-medium truncate w-full"
        style={{ color: 'var(--color-text)' }}
        title={value}
      >
        {value}
      </div>
    </button>
  );
}

function ChatBubble({ entry }: { entry: ChatEntry }) {
  if (entry.role === 'tool') {
    return (
      <div
        className="self-start max-w-[80%] rounded-lg px-3 py-2 text-xs flex flex-col gap-1"
        style={{
          background: 'var(--color-bg-tertiary)',
          border: '1px solid var(--color-border)',
          color: 'var(--color-text-secondary)',
        }}
      >
        <div className="flex items-center gap-2">
          <span
            className="w-1.5 h-1.5 rounded-full inline-block"
            style={{
              background: entry.pending
                ? 'var(--color-warning)'
                : entry.toolSuccess
                ? 'var(--color-success)'
                : 'var(--color-error)',
            }}
          />
          <span style={{ color: 'var(--color-text)' }}>{entry.toolName}</span>
          {entry.pending && <Loader2 size={11} className="animate-spin" />}
        </div>
        {entry.toolArgs && (
          <code
            className="block truncate"
            style={{ color: 'var(--color-text-tertiary)', fontSize: 10.5 }}
          >
            {entry.toolArgs}
          </code>
        )}
        {entry.toolResult && !entry.pending && (
          <code
            className="block truncate"
            style={{ color: 'var(--color-text-tertiary)', fontSize: 10.5 }}
            title={entry.toolResult}
          >
            → {entry.toolResult.slice(0, 120)}
          </code>
        )}
      </div>
    );
  }

  const isUser = entry.role === 'user';
  return (
    <div
      className={`rounded-lg px-3 py-2 text-sm whitespace-pre-wrap ${
        isUser ? 'self-end max-w-[70%]' : 'self-start max-w-[80%]'
      }`}
      style={
        isUser
          ? {
              background: 'var(--color-accent-subtle)',
              color: 'var(--color-text)',
              border:
                '1px solid color-mix(in srgb, var(--color-accent) 25%, transparent)',
            }
          : {
              background: 'var(--color-bg-secondary)',
              color: 'var(--color-text)',
              border: '1px solid var(--color-border)',
            }
      }
    >
      {entry.content || (entry.pending ? '…' : '')}
    </div>
  );
}
