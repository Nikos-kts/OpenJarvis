import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';
import {
  Bot,
  ChevronsUpDown,
  Loader2,
  Send,
  Settings as SettingsIcon,
  Sparkles,
  Volume2,
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
import { JarvisSettingsDrawer } from '../components/Jarvis/JarvisSettingsDrawer';

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
  const [settingsOpen, setSettingsOpen] = useState(false);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  const refreshRecord = useCallback(async () => {
    try {
      const rec = await fetchJarvisPrimary();
      setRecord(rec);
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
        // Missing messages is non-fatal.
      });
  }, [record?.id]);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [entries.length]);

  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || !record || sending) return;
    setSending(true);
    setInput('');

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
          updateAssistant({ content: full, pending: true });
        },
        onToolCallStart: (info: AgentToolCallStart) => {
          setEntries((prev) => [
            ...prev.filter((e) => e.id !== assistantId),
            {
              id: `${assistantId}-tc-${info.tool}-${prev.length}`,
              role: 'tool',
              content: '',
              toolName: info.tool,
              toolArgs: info.arguments,
              pending: true,
            },
            prev.find((e) => e.id === assistantId)!,
          ]);
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
    }
  }, [input, record, sending]);

  const cfg: JarvisPrimaryConfig = useMemo(
    () => (record?.config ?? {}) as JarvisPrimaryConfig,
    [record],
  );

  if (loadingRecord) {
    return (
      <div className="flex items-center justify-center h-full w-full">
        <Loader2 className="animate-spin" size={22} style={{ color: 'var(--color-accent)' }} />
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

  return (
    <div className="flex flex-col h-full w-full overflow-hidden">
      {/* Header */}
      <header
        className="flex items-center justify-between px-5 py-3 shrink-0"
        style={{
          borderBottom: '1px solid var(--color-border)',
          background: 'color-mix(in srgb, var(--color-bg-secondary) 60%, transparent)',
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
        <div className="flex items-center gap-2 shrink-0">
          <Badge
            active={!!cfg.voice?.enabled}
            label="Voice"
            icon={<Volume2 size={12} />}
          />
          <Badge
            active={!!cfg.wake?.enabled}
            label={cfg.wake?.mode ? `Wake · ${cfg.wake?.mode}` : 'Wake'}
            icon={<ChevronsUpDown size={12} />}
          />
          <button
            onClick={() => setSettingsOpen(true)}
            className="p-2 rounded-lg transition-colors cursor-pointer"
            style={{ color: 'var(--color-text-secondary)' }}
            onMouseEnter={(e) =>
              (e.currentTarget.style.background = 'var(--color-bg-tertiary)')
            }
            onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
            title="Jarvis settings"
          >
            <SettingsIcon size={16} />
          </button>
        </div>
      </header>

      {/* Transcript */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto px-5 py-4 flex flex-col gap-3"
      >
        {entries.length === 0 && (
          <div
            className="text-sm text-center mt-10"
            style={{ color: 'var(--color-text-tertiary)' }}
          >
            Say hello. Jarvis is listening.
          </div>
        )}
        {entries.map((e) => (
          <ChatBubble key={e.id} entry={e} />
        ))}
      </div>

      {/* Composer */}
      <div
        className="px-5 py-3 shrink-0"
        style={{ borderTop: '1px solid var(--color-border)' }}
      >
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
            className="flex-1 bg-transparent outline-none resize-none text-sm px-2 py-1 min-h-[24px] max-h-40"
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

      {settingsOpen && record && (
        <JarvisSettingsDrawer
          agent={record}
          onClose={() => setSettingsOpen(false)}
          onUpdated={(next) => {
            setRecord((prev) => (prev ? { ...prev, config: next } : prev));
          }}
        />
      )}
    </div>
  );
}

function Badge({
  active,
  label,
  icon,
}: {
  active: boolean;
  label: string;
  icon: React.ReactNode;
}) {
  return (
    <span
      className="flex items-center gap-1.5 px-2 py-1 rounded-full text-[11px]"
      style={{
        background: active
          ? 'color-mix(in srgb, var(--color-accent) 12%, transparent)'
          : 'var(--color-bg-tertiary)',
        color: active ? 'var(--color-accent)' : 'var(--color-text-tertiary)',
        border: `1px solid ${
          active
            ? 'color-mix(in srgb, var(--color-accent) 30%, transparent)'
            : 'var(--color-border)'
        }`,
      }}
    >
      {icon}
      {label}
    </span>
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
          {entry.pending && (
            <Loader2 size={11} className="animate-spin" />
          )}
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
              border: '1px solid color-mix(in srgb, var(--color-accent) 25%, transparent)',
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
