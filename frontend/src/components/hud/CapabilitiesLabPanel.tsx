/**
 * CapabilitiesLabPanel — interactive Tools / Skills / Agents surface.
 *
 * The panel itself is a compact status/toggle view.  A gear button to
 * the right of the filter opens a dropdown with three entries — each
 * launches a dedicated configuration dialog (``CapabilityDialog``)
 * for Tools, Skills, and Sub-Agents respectively.  All toggles round-
 * trip to ``/v1/jarvis/{tools,skills,agents}/...`` and persist via
 * :class:`JarvisStateStore`, so the HUD is the single source of truth.
 */

import { AlertTriangle, Bot, Hammer, Power, PowerOff, Search, Settings2, Sparkles, Users } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
    JarvisDelegatableAgent,
    JarvisSkill,
    JarvisState,
    JarvisTool,
    getJarvisAgents,
    getJarvisSkills,
    getJarvisTools,
    toggleJarvisAgent,
    toggleJarvisSkill,
    toggleJarvisTool,
} from '../../lib/jarvis-api';
import { CapabilityDialog, CapabilityRow } from './CapabilityDialog';

const ACCENT = '#22d3ee';

type DialogKind = 'tools' | 'skills' | 'agents';

export function CapabilitiesLabPanel({ state }: { state: JarvisState | null }) {
    const [tools, setTools] = useState<JarvisTool[]>([]);
    const [skills, setSkills] = useState<JarvisSkill[]>([]);
    const [agents, setAgents] = useState<JarvisDelegatableAgent[]>([]);
    const [agentsUnrestricted, setAgentsUnrestricted] = useState(true);
    const [pending, setPending] = useState<Set<string>>(new Set());
    const [query, setQuery] = useState('');
    const [menuOpen, setMenuOpen] = useState(false);
    const [openDialog, setOpenDialog] = useState<DialogKind | null>(null);
    const menuRef = useRef<HTMLDivElement | null>(null);

    const refreshAgents = useCallback(async () => {
        try {
            const res = await getJarvisAgents();
            setAgents(res.items);
            setAgentsUnrestricted(res.unrestricted);
        } catch {
            /* ignore transient failure */
        }
    }, []);

    // Lazy-load tools/skills/agents on mount + whenever the polled
    // jarvis state changes its active list on the server.
    useEffect(() => {
        let cancelled = false;
        Promise.allSettled([getJarvisTools(), getJarvisSkills(), getJarvisAgents()]).then(
            ([tRes, sRes, aRes]) => {
                if (cancelled) return;
                if (tRes.status === 'fulfilled') setTools(tRes.value.items);
                if (sRes.status === 'fulfilled') setSkills(sRes.value.items);
                if (aRes.status === 'fulfilled') {
                    setAgents(aRes.value.items);
                    setAgentsUnrestricted(aRes.value.unrestricted);
                }
            },
        );
        return () => {
            cancelled = true;
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [state?.tools.join('|'), state?.active_skills.join('|'), state?.sub_agents.length]);

    // Close the gear dropdown on outside click.
    useEffect(() => {
        if (!menuOpen) return;
        const onClick = (e: MouseEvent) => {
            if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
                setMenuOpen(false);
            }
        };
        document.addEventListener('mousedown', onClick);
        return () => document.removeEventListener('mousedown', onClick);
    }, [menuOpen]);

    const markBusy = (key: string, on: boolean) =>
        setPending((p) => {
            const next = new Set(p);
            if (on) next.add(key);
            else next.delete(key);
            return next;
        });

    async function flipTool(name: string) {
        markBusy(name, true);
        try {
            const res = await toggleJarvisTool(name);
            setTools((prev) =>
                prev.map((t) => (t.name === name ? { ...t, active: res.state === 'enabled' } : t)),
            );
        } finally {
            markBusy(name, false);
        }
    }

    async function flipSkill(name: string) {
        markBusy(name, true);
        try {
            const res = await toggleJarvisSkill(name);
            setSkills((prev) =>
                prev.map((s) => (s.name === name ? { ...s, active: res.state === 'enabled' } : s)),
            );
        } finally {
            markBusy(name, false);
        }
    }

    async function flipAgent(id: string) {
        markBusy(id, true);
        try {
            await toggleJarvisAgent(id);
            await refreshAgents();
        } finally {
            markBusy(id, false);
        }
    }

    const filteredTools = useMemo(() => {
        const q = query.trim().toLowerCase();
        const active = tools.filter((t) => t.active);
        if (!q) return active;
        return active.filter(
            (t) =>
                t.name.toLowerCase().includes(q) ||
                t.description.toLowerCase().includes(q) ||
                t.category.toLowerCase().includes(q),
        );
    }, [tools, query]);

    const filteredSkills = useMemo(() => {
        const q = query.trim().toLowerCase();
        const active = skills.filter((s) => s.active);
        if (!q) return active;
        return active.filter(
            (s) =>
                s.name.toLowerCase().includes(q) ||
                (s.description ?? '').toLowerCase().includes(q) ||
                (s.tags ?? []).some((t) => t.toLowerCase().includes(q)),
        );
    }, [skills, query]);

    const filteredAgents = useMemo(() => {
        const q = query.trim().toLowerCase();
        const active = agentsUnrestricted ? agents : agents.filter((a) => a.active);
        if (!q) return active;
        return active.filter(
            (a) =>
                (a.name ?? '').toLowerCase().includes(q) ||
                (a.agent_type ?? '').toLowerCase().includes(q),
        );
    }, [agents, agentsUnrestricted, query]);

    const toolsActive = tools.filter((t) => t.active).length;
    const skillsActive = skills.filter((s) => s.active).length;
    const agentsActive = agents.filter((a) => a.active).length;

    // Dialog row adapters
    const toolRows: CapabilityRow[] = useMemo(
        () =>
            tools.map((t) => ({
                key: t.name,
                label: t.name,
                description: t.description,
                meta: t.category || undefined,
                active: t.active,
                busy: pending.has(t.name),
                warning: t.sensitive
                    ? t.sensitive_reason ||
                    'Potentially destructive capability — review before enabling.'
                    : undefined,
            })),
        [tools, pending],
    );
    const skillRows: CapabilityRow[] = useMemo(
        () =>
            skills.map((s) => ({
                key: s.name,
                label: s.name,
                description: s.description || undefined,
                meta:
                    s.tags && s.tags.length > 0
                        ? s.tags.slice(0, 2).join(' · ')
                        : s.version || undefined,
                active: s.active,
                busy: pending.has(s.name),
            })),
        [skills, pending],
    );
    const agentRows: CapabilityRow[] = useMemo(
        () =>
            agents.map((a) => ({
                key: a.id ?? a.name ?? '',
                label: a.name ?? '(unnamed)',
                description: [a.agent_type, a.model].filter(Boolean).join(' · ') || undefined,
                meta: a.status ?? undefined,
                active: a.active,
                busy: pending.has(a.id ?? ''),
                disabled: !a.id,
            })),
        [agents, pending],
    );

    return (
        <div className="flex flex-col h-full min-h-0">
            {/* Search + gear dropdown */}
            <div className="flex items-center gap-1.5 mb-2">
                <div
                    className="flex-1 flex items-center gap-1.5 px-2 py-1 rounded"
                    style={{ border: `1px solid ${ACCENT}33`, background: `${ACCENT}0a` }}
                >
                    <Search size={11} style={{ color: `${ACCENT}aa` }} />
                    <input
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        placeholder="filter capabilities…"
                        className="flex-1 bg-transparent outline-none text-[11px]"
                        style={{ color: '#e6fcff' }}
                    />
                </div>
                <div ref={menuRef} className="relative">
                    <button
                        onClick={() => setMenuOpen((v) => !v)}
                        className="p-1 rounded cursor-pointer"
                        title="Configure capabilities"
                        style={{
                            border: `1px solid ${menuOpen ? ACCENT : `${ACCENT}33`}`,
                            color: menuOpen ? '#e6fcff' : `${ACCENT}cc`,
                            background: menuOpen ? `${ACCENT}22` : 'transparent',
                        }}
                    >
                        <Settings2 size={12} />
                    </button>
                    {menuOpen && (
                        <div
                            className="absolute right-0 mt-1 z-20 min-w-[180px] rounded py-1"
                            style={{
                                background: 'rgba(8,16,22,0.98)',
                                border: `1px solid ${ACCENT}55`,
                                boxShadow: `0 0 24px ${ACCENT}22`,
                            }}
                        >
                            <MenuItem
                                icon={<Hammer size={12} />}
                                label="Configure Tools"
                                badge={`${toolsActive}/${tools.length}`}
                                onClick={() => {
                                    setOpenDialog('tools');
                                    setMenuOpen(false);
                                }}
                            />
                            <MenuItem
                                icon={<Sparkles size={12} />}
                                label="Configure Skills"
                                badge={`${skillsActive}/${skills.length}`}
                                onClick={() => {
                                    setOpenDialog('skills');
                                    setMenuOpen(false);
                                }}
                            />
                            <MenuItem
                                icon={<Users size={12} />}
                                label="Configure Agents"
                                badge={agentsUnrestricted ? `${agents.length}/${agents.length}` : `${agentsActive}/${agents.length}`}
                                onClick={() => {
                                    setOpenDialog('agents');
                                    setMenuOpen(false);
                                }}
                            />
                        </div>
                    )}
                </div>
            </div>

            {/* Status sections (inline summary) — three equal-height
                panes, each scrollable; only *active* capabilities are
                shown inline, while the header count reflects the
                active/total ratio. */}
            <div className="flex-1 min-h-0 flex flex-col gap-3">
                <Section
                    title="Tools"
                    icon={<Hammer size={12} />}
                    countLabel={`${toolsActive}/${tools.length}`}
                >
                    {filteredTools.length === 0 ? (
                        <Empty
                            label={
                                tools.length === 0
                                    ? 'no tools wired'
                                    : toolsActive === 0
                                        ? 'no active tools'
                                        : 'no matches'
                            }
                        />
                    ) : (
                        <ul className="flex flex-col gap-1">
                            {filteredTools.map((t) => (
                                <ToolRow
                                    key={t.name}
                                    tool={t}
                                    busy={pending.has(t.name)}
                                    onToggle={() => flipTool(t.name)}
                                />
                            ))}
                        </ul>
                    )}
                </Section>

                <Section
                    title="Skills"
                    icon={<Sparkles size={12} />}
                    countLabel={`${skillsActive}/${skills.length}`}
                >
                    {filteredSkills.length === 0 ? (
                        <Empty
                            label={
                                skills.length === 0
                                    ? 'no skills registered'
                                    : skillsActive === 0
                                        ? 'no active skills'
                                        : 'no matches'
                            }
                        />
                    ) : (
                        <ul className="flex flex-col gap-1">
                            {filteredSkills.map((s) => (
                                <SkillRow
                                    key={s.name}
                                    skill={s}
                                    busy={pending.has(s.name)}
                                    onToggle={() => flipSkill(s.name)}
                                />
                            ))}
                        </ul>
                    )}
                </Section>

                <Section
                    title="Sub-Agents"
                    icon={<Users size={12} />}
                    countLabel={
                        agentsUnrestricted ? `${agents.length}` : `${agentsActive}/${agents.length}`
                    }
                >
                    {filteredAgents.length === 0 ? (
                        <Empty
                            label={
                                agents.length === 0
                                    ? 'no sub-agents'
                                    : !agentsUnrestricted && agentsActive === 0
                                        ? 'no active sub-agents'
                                        : 'no matches'
                            }
                        />
                    ) : (
                        <ul className="flex flex-col gap-1">
                            {filteredAgents.map((a) => (
                                <li
                                    key={a.id || a.name || Math.random().toString()}
                                    className="flex items-center justify-between px-2 py-1.5 rounded"
                                    style={{
                                        border: `1px solid ${a.active ? ACCENT : '#64748b'}22`,
                                        background: `${a.active ? ACCENT : '#64748b'}08`,
                                        opacity: a.active ? 1 : 0.6,
                                    }}
                                >
                                    <span
                                        className="flex items-center gap-1.5 text-xs font-mono"
                                        style={{ color: '#e6fcff' }}
                                    >
                                        <Bot size={11} style={{ color: `${ACCENT}aa` }} />
                                        {a.name || '(unnamed)'}
                                    </span>
                                    <span
                                        className="text-[9px] uppercase tracking-wider"
                                        style={{ color: `${ACCENT}99` }}
                                    >
                                        {a.agent_type ?? 'agent'} · {a.status ?? 'idle'}
                                    </span>
                                </li>
                            ))}
                        </ul>
                    )}
                </Section>
            </div>

            <div className="mt-2 text-[9px] uppercase tracking-widest" style={{ color: `${ACCENT}66` }}>
                toggles persist · next turn applies changes
            </div>

            {/* Dialogs */}
            <CapabilityDialog
                open={openDialog === 'tools'}
                title="Configure Tools"
                subtitle="Available tools Jarvis can call during a turn."
                icon={<Hammer size={14} />}
                rows={toolRows}
                onToggle={flipTool}
                onClose={() => setOpenDialog(null)}
                empty="no tools wired"
            />
            <CapabilityDialog
                open={openDialog === 'skills'}
                title="Configure Skills"
                subtitle="Procedural skills advertised in Jarvis's system prompt."
                icon={<Sparkles size={14} />}
                rows={skillRows}
                onToggle={flipSkill}
                onClose={() => setOpenDialog(null)}
                empty="no skills registered"
            />
            <CapabilityDialog
                open={openDialog === 'agents'}
                title="Configure Agents"
                subtitle={
                    agentsUnrestricted
                        ? 'All known sub-agents are delegatable. Toggle one to start an allowlist.'
                        : 'Only enabled sub-agents may be delegation targets.'
                }
                icon={<Users size={14} />}
                rows={agentRows}
                onToggle={flipAgent}
                onClose={() => setOpenDialog(null)}
                empty="no sub-agents registered"
            />
        </div>
    );
}

// ---------------------------------------------------------------------------
// Menu + inline row components
// ---------------------------------------------------------------------------

function MenuItem({
    icon,
    label,
    badge,
    onClick,
}: {
    icon: React.ReactNode;
    label: string;
    badge?: string;
    onClick: () => void;
}) {
    return (
        <button
            onClick={onClick}
            className="flex items-center justify-between w-full px-3 py-1.5 text-left text-[11px] cursor-pointer"
            style={{ color: '#e6fcff' }}
            onMouseEnter={(e) => (e.currentTarget.style.background = `${ACCENT}14`)}
            onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
        >
            <span className="flex items-center gap-2" style={{ color: `${ACCENT}cc` }}>
                {icon}
                <span style={{ color: '#e6fcff' }}>{label}</span>
            </span>
            {badge && (
                <span
                    className="font-mono text-[9px] px-1.5 py-0.5 rounded"
                    style={{ background: `${ACCENT}22`, color: '#e6fcff' }}
                >
                    {badge}
                </span>
            )}
        </button>
    );
}

function ToolRow({ tool, busy, onToggle }: { tool: JarvisTool; busy: boolean; onToggle: () => void }) {
    const color = tool.active ? ACCENT : '#64748b';
    const warn = tool.sensitive
        ? tool.sensitive_reason || 'Potentially destructive capability — review before enabling.'
        : '';
    return (
        <li
            className="flex items-center justify-between gap-2 px-2 py-1.5 rounded"
            style={{ border: `1px solid ${color}33`, background: `${color}08` }}
            title={tool.description}
        >
            <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5 text-xs font-mono truncate" style={{ color: tool.active ? '#e6fcff' : '#a4d5e0aa' }}>
                    {warn && (
                        <span title={warn} className="shrink-0 flex items-center" style={{ color: '#f59e0b' }}>
                            <AlertTriangle size={11} />
                        </span>
                    )}
                    <span className="truncate">{tool.name}</span>
                    {tool.category && (
                        <span
                            className="text-[8px] uppercase tracking-widest px-1 py-[1px] rounded"
                            style={{ border: `1px solid ${color}44`, color: `${color}dd` }}
                        >
                            {tool.category}
                        </span>
                    )}
                </div>
                {tool.description && (
                    <div className="text-[10px] mt-0.5 truncate opacity-70" style={{ color: `${color}cc` }}>
                        {tool.description}
                    </div>
                )}
            </div>
            <ToggleButton active={tool.active} busy={busy} onClick={onToggle} color={color} />
        </li>
    );
}

function SkillRow({ skill, busy, onToggle }: { skill: JarvisSkill; busy: boolean; onToggle: () => void }) {
    const color = skill.active ? ACCENT : '#64748b';
    const meta = skill.tags && skill.tags.length > 0 ? skill.tags[0] : skill.version || undefined;
    return (
        <li
            className="flex items-center justify-between gap-2 px-2 py-1.5 rounded"
            style={{ border: `1px solid ${color}33`, background: `${color}08` }}
            title={skill.description}
        >
            <div className="min-w-0 flex-1">
                <div
                    className="flex items-center gap-1.5 text-xs font-mono truncate"
                    style={{ color: skill.active ? '#e6fcff' : '#a4d5e0aa' }}
                >
                    <span className="truncate">{skill.name}</span>
                    {meta && (
                        <span
                            className="text-[8px] uppercase tracking-widest px-1 py-[1px] rounded shrink-0"
                            style={{ border: `1px solid ${color}44`, color: `${color}dd` }}
                        >
                            {meta}
                        </span>
                    )}
                </div>
                {skill.description && (
                    <div
                        className="text-[10px] mt-0.5 truncate opacity-70"
                        style={{ color: `${color}cc` }}
                    >
                        {skill.description}
                    </div>
                )}
            </div>
            <ToggleButton active={skill.active} busy={busy} onClick={onToggle} color={color} />
        </li>
    );
}

function ToggleButton({
    active,
    busy,
    onClick,
    color,
}: {
    active: boolean;
    busy: boolean;
    onClick: () => void;
    color: string;
}) {
    return (
        <button
            onClick={onClick}
            disabled={busy}
            className="shrink-0 flex items-center gap-1 px-1.5 py-0.5 rounded cursor-pointer transition-colors disabled:opacity-40"
            style={{ border: `1px solid ${color}66`, color, background: 'transparent' }}
            title={active ? 'Disable' : 'Enable'}
        >
            {active ? <Power size={10} /> : <PowerOff size={10} />}
            <span className="text-[9px] uppercase tracking-widest">{active ? 'on' : 'off'}</span>
        </button>
    );
}

function Section({
    title,
    icon,
    countLabel,
    children,
}: {
    title: string;
    icon: React.ReactNode;
    countLabel: string;
    children: React.ReactNode;
}) {
    return (
        <section
            className="flex-1 min-h-0 flex flex-col rounded"
            style={{
                border: `1px solid ${ACCENT}22`,
                background: `${ACCENT}06`,
            }}
        >
            <header
                className="flex items-center justify-between px-2 py-1 shrink-0"
                style={{ borderBottom: `1px solid ${ACCENT}1f` }}
            >
                <div
                    className="flex items-center gap-1.5 text-[10px] uppercase tracking-[0.25em]"
                    style={{ color: `${ACCENT}cc` }}
                >
                    {icon}
                    <span>{title}</span>
                </div>
                <span
                    className="font-mono text-[9px] px-1 rounded"
                    style={{ background: `${ACCENT}22`, color: '#e6fcff' }}
                >
                    {countLabel}
                </span>
            </header>
            <div className="flex-1 min-h-0 overflow-y-auto px-1.5 py-1.5">{children}</div>
        </section>
    );
}

function Empty({ label }: { label: string }) {
    return (
        <div className="text-[11px] opacity-50 p-3 text-center" style={{ color: ACCENT }}>
            {label}
        </div>
    );
}
