---
applyTo: "src/openjarvis/jarvis/**,frontend/src/**"
---

# Jarvis HUD Capabilities — architecture

## Capability universes
Three capability kinds, each with a "full universe" + "active subset" model:

1. **Tools** — `src/openjarvis/jarvis/toolset.py`
   - `build_jarvis_tools(...)` enumerates every `@ToolRegistry.register(...)` tool and does best-effort DI (`memory_backend`, `channel_backend`, `scheduler`, `knowledge_store`, `retriever`, `engine`, `model`).
   - Proactively imports optional modules (`agent_tools`, `browser`, `knowledge_*`, `scan_chunks`, `git_tool`, `pdf_tool`, `image_tool`, etc.) because `openjarvis.tools.__init__` curates only a subset.
   - Scheduler tools take `_scheduler` as a **class attribute** (not ctor arg); `build_jarvis_tools` sets it on every subclass so all instances share the ref.
   - ChannelBridge is BaseChannel-compatible → passes as `channel_backend` for `channel_send/list/status`.
   - `SENSITIVE_TOOLS` frozenset + `SENSITIVE_REASON` dict flag destructive capabilities (shell_exec, apply_patch, file_write, code_interpreter{,_docker}, repl, git_commit, db_query, agent_spawn, agent_kill). HUD shows amber `AlertTriangle` with tooltip.
   - Currently builds **55 / 55** registered tools.

2. **Skills** — `src/openjarvis/jarvis/skillset.py`
   - `discover_jarvis_skills(config)` scans (in order): workspace `./skills/`, `config.skills.skills_dir` (default `~/.openjarvis/skills/`), `config.learning.skills.overlay_dir`, then **20 bundled defaults** shipped in `src/openjarvis/skills/data/*.toml`.
   - First-seen name wins. `manifest_to_api_dict()` projects to wire shape: `{name, description, version, author, tags, steps, user_invocable}`.
   - A skill = `SkillManifest` (see `src/openjarvis/skills/types.py`): name + steps (tool/skill invocations with Jinja2 templates) + metadata. Discovery in `src/openjarvis/skills/loader.py::discover_skills`. Execution by `SkillManager`.

3. **Sub-agents** — unchanged; `active_agents=None` means unrestricted, list means allowlist. Delegation filter lives in `src/openjarvis/jarvis/delegation.py::_is_allowed`. All 5 `ToolResult(...)` there must pass `tool_name=self.tool_id` (previous bug).

## Composition (factory.py)
`build_jarvis_agent(config, *, engine, model, bus, core_tools, agent_manager, system, memory_backend, channel_backend, scheduler, knowledge_store, retriever, active_skills)`:
- Computes `core_names = {t.spec.name for t in core_tools}`.
- `extra_tools = build_jarvis_tools(..., exclude=core_names)`.
- `all_tools = list(core_tools) + extra_tools`.
- Discovers skill manifests → `all_skills_meta`.
- Passes to `JarvisAgent(..., default_active_tool_names=list(core_names), sensitive_tool_names=SENSITIVE_TOOLS, all_skills=all_skills_meta)`.

## JarvisAgent active-set resolution
For both tools and skills:
- If persisted KV present → use intersection with known universe.
- Else if `default_active_tool_names` given → use that intersection (safety: don't enable every new tool on first boot).
- Else all.

## API wiring
- `cli/serve.py` passes `memory_backend=memory_backend, channel_backend=channel_bridge, scheduler=agent_scheduler` into `build_jarvis_agent`.
- Routes in `src/openjarvis/jarvis/routes.py`:
  - `GET /v1/jarvis/tools` → items carry `{name, description, category, latency_estimate, active, sensitive, sensitive_reason}`.
  - `GET /v1/jarvis/skills` → items carry `{name, description, version, author, tags, steps, user_invocable, active}`. Stale persisted actives are folded in so they can be toggled off even if the manifest disappeared.
  - `POST /{tools,skills,agents}/{name}/toggle` flips persisted state.
  - `/hud/prefs` persists HUD tab visibility.

## Frontend contract
- `frontend/src/lib/jarvis-api.ts` → `JarvisTool` (+ `sensitive?`, `sensitive_reason?`), `JarvisSkill` (+ description/version/author/tags/steps/user_invocable).
- `frontend/src/components/hud/CapabilitiesLabPanel.tsx` — inline panel: three **equal-height** `Section` panes with internal scroll (`flex-1 min-h-0 overflow-y-auto`); inline lists show **only active** capabilities while header badge shows `active/total` ratio. Sub-Agents section respects `agentsUnrestricted` (unrestricted → show all).
- `frontend/src/components/hud/CapabilityDialog.tsx` — modal for full-universe toggling. `CapabilityRow` supports `warning?: string` → amber `AlertTriangle` with `title` tooltip next to the label.
- Inline `ToolRow` also renders the warning icon for sensitive tools.
- Inline `SkillRow` shows tag/version badge + description subtitle.
- Gear dropdown in the panel header opens "Configure Tools/Skills/Agents" dialogs.

## Defaults shipped on disk
- 20 curated skills at `src/openjarvis/skills/data/*.toml` (web-summarize, daily-digest, code-lint, pdf-summarize, security-scan, topic-research, email-draft, meeting-notes, ...).
