/**
 * Per-field help text for the Settings UI.
 *
 * Keyed by the fully-qualified dotted path as emitted by the backend
 * schema (same value shown under every field's `code` tag in the form).
 * Each entry contains:
 *   - `text`: 1-3 sentence description of what the setting does.
 *   - `scope`: where the value is consumed (backend/frontend/rust/…).
 *             Rendered as a small badge inside the tooltip.
 *
 * Adding a hint is optional: fields without an entry simply don't show
 * the help icon.  Keep descriptions short and user-facing — linger
 * tutorials belong in mkdocs.
 */

export interface FieldHint {
    text: string;
    scope?: string;
}

export const FIELD_HINTS: Record<string, FieldHint> = {
    // -------------------------------------------------------------------
    // Agent harness
    // -------------------------------------------------------------------
    'agent.default_agent': {
        text:
            "Which built-in agent harness to run when an HTTP request doesn't " +
            "name one. Common values: 'simple' (single LLM call), 'orchestrator' " +
            "(planner + workers), 'react' (tool-using ReAct loop), 'claude_code'.",
        scope: 'Backend (Python)',
    },
    'agent.max_turns': {
        text:
            'Hard cap on tool/LLM round-trips per request. Prevents runaway ' +
            'loops when a tool keeps returning data the model wants to refine.',
        scope: 'Backend (Python)',
    },
    'agent.tools': {
        text:
            'Comma-separated tool names the default agent may call. Leave empty ' +
            'to allow every tool enabled in the [tools] section.',
        scope: 'Backend (Python)',
    },
    'agent.objective': {
        text:
            'Free-form one-liner describing what this agent is for. Surfaced in ' +
            'the router, docs, and learning logs — it does not steer generation.',
        scope: 'Backend (Python)',
    },
    'agent.system_prompt': {
        text:
            'Inline system prompt. Takes precedence over system_prompt_path when ' +
            'non-empty. Use this for quick experiments; prefer a file in source ' +
            'control for anything permanent.',
        scope: 'Backend (Python)',
    },
    'agent.system_prompt_path': {
        text:
            'Filesystem path to a .txt or .md file loaded at startup. Ignored if ' +
            'system_prompt is set. Path may be absolute or relative to the repo.',
        scope: 'Backend (Python)',
    },
    'agent.context_from_memory': {
        text:
            'When enabled, the agent retrieves the top-k matches from ' +
            '[tools.storage] and prepends them to the prompt as context. Disable ' +
            'for stateless requests or privacy-sensitive workflows.',
        scope: 'Backend (Python)',
    },
    'agent.default_system_prompt': {
        text:
            'Fallback prompt used when neither system_prompt nor ' +
            'system_prompt_path is configured. The packaged default establishes ' +
            'the local/private posture.',
        scope: 'Backend (Python)',
    },

    // -------------------------------------------------------------------
    // Tools — memory, MCP, browser
    // -------------------------------------------------------------------
    'tools.enabled': {
        text:
            'Comma-separated whitelist of tools the runtime exposes to agents. ' +
            'Empty = every registered tool. Use to lock down a deployment.',
        scope: 'Backend (Python)',
    },
    'tools.storage.default_backend': {
        text:
            "Memory store implementation. 'sqlite' = embedded, no external deps. " +
            "'chroma' / 'qdrant' = vector DBs (require their own services).",
        scope: 'Backend (Python)',
    },
    'tools.storage.db_path': {
        text:
            'SQLite file used by the sqlite backend. Created on first write. ' +
            'Lives under the project-local .openJarvis/ folder by default.',
        scope: 'Backend (Python)',
    },
    'tools.storage.context_top_k': {
        text:
            'Number of memory chunks retrieved per query. Higher = more recall ' +
            'but larger prompts and slower generation.',
        scope: 'Backend (Python)',
    },
    'tools.storage.context_min_score': {
        text:
            'Minimum cosine similarity (0-1) required to include a chunk in the ' +
            'prompt. Filters out weakly-related hits.',
        scope: 'Backend (Python)',
    },
    'tools.storage.context_max_tokens': {
        text:
            'Upper bound on retrieved-context tokens injected into the prompt. ' +
            'Protects the model window even when top_k is large.',
        scope: 'Backend (Python)',
    },
    'tools.storage.chunk_size': {
        text:
            'Target token size when ingesting documents. 256-1024 works well for ' +
            'most text corpora.',
        scope: 'Backend (Python)',
    },
    'tools.storage.chunk_overlap': {
        text:
            'Token overlap between adjacent chunks. Preserves context at ' +
            'boundaries; typical values: 16-128.',
        scope: 'Backend (Python)',
    },
    'tools.mcp.enabled': {
        text:
            'Enable the Model Context Protocol client. When on, tools exposed by ' +
            'registered MCP servers become callable by any agent.',
        scope: 'Backend (Python)',
    },
    'tools.mcp.servers': {
        text:
            'JSON list of MCP server definitions (command, args, env, transport). ' +
            'Usually managed via `jarvis mcp add`, not hand-edited.',
        scope: 'Backend (Python)',
    },
    'tools.browser.headless': {
        text:
            'Run the Playwright browser without a visible window. Disable only ' +
            'for interactive debugging of scraping tasks.',
        scope: 'Backend (Python) + Node sidecar',
    },
    'tools.browser.timeout_ms': {
        text:
            'Per-action timeout for Playwright navigation, waits, and clicks. ' +
            'Raise for slow pages or high-latency networks.',
        scope: 'Backend (Python) + Node sidecar',
    },
    'tools.browser.viewport_width': {
        text: 'Emulated browser viewport width in pixels.',
        scope: 'Backend (Python) + Node sidecar',
    },
    'tools.browser.viewport_height': {
        text: 'Emulated browser viewport height in pixels.',
        scope: 'Backend (Python) + Node sidecar',
    },

    // -------------------------------------------------------------------
    // Speech
    // -------------------------------------------------------------------
    'speech.backend': {
        text:
            "'auto' picks the best local install. 'faster-whisper' = local STT " +
            "(GPU or CPU). 'openai' and 'deepgram' are cloud; they require API " +
            "keys set in [security.credentials] or env vars.",
        scope: 'Backend (Python) — Rust fast-path for mic capture',
    },
    'speech.model': {
        text:
            "Whisper model size. tiny < base < small < medium < large-v3. Bigger " +
            "= more accurate but much slower. Ignored for cloud backends.",
        scope: 'Backend (Python)',
    },
    'speech.language': {
        text:
            "ISO language code (e.g. 'en', 'el'). Empty = auto-detect per " +
            "utterance — slightly slower but works across languages.",
        scope: 'Backend (Python)',
    },
    'speech.device': {
        text:
            "'auto' picks cuda if a compatible GPU is detected, else cpu. 'cuda' " +
            "requires an NVIDIA GPU with the proper drivers; 'cpu' always works.",
        scope: 'Backend (Python)',
    },
    'speech.compute_type': {
        text:
            "Precision used by faster-whisper. 'float16' = fastest on GPU, " +
            "'int8' = smallest CPU footprint, 'float32' = highest quality.",
        scope: 'Backend (Python)',
    },

    // -------------------------------------------------------------------
    // Scheduler
    // -------------------------------------------------------------------
    'scheduler.enabled': {
        text:
            'Start the APScheduler worker alongside the API server. Required for ' +
            'any cron job, workflow trigger, or the morning digest.',
        scope: 'Backend (Python). Restart required.',
    },
    'scheduler.poll_interval': {
        text:
            'Seconds between job-queue polls. Lower = tighter cron precision at ' +
            'a small idle CPU cost. 60s is usually plenty.',
        scope: 'Backend (Python)',
    },
    'scheduler.db_path': {
        text:
            'SQLite file where APScheduler stores job state. Empty = default ' +
            '(.openJarvis/db/scheduler.db).',
        scope: 'Backend (Python)',
    },

    // -------------------------------------------------------------------
    // Morning digest
    // -------------------------------------------------------------------
    'digest.enabled': {
        text:
            'Enable the morning digest job. Also requires scheduler.enabled = ' +
            'true, otherwise the cron never fires.',
        scope: 'Backend (Python)',
    },
    'digest.schedule': {
        text:
            "Standard 5-field cron expression. Default '0 6 * * *' = 06:00 every " +
            "day in the configured timezone.",
        scope: 'Backend (Python)',
    },
    'digest.timezone': {
        text:
            "IANA timezone applied to the cron expression (e.g. 'Europe/Athens', " +
            "'America/Los_Angeles').",
        scope: 'Backend (Python)',
    },
    'digest.persona': {
        text:
            "Writer persona used when composing the digest ('jarvis', 'friday', " +
            "'alfred', …). Controls tone and vocabulary.",
        scope: 'Backend (Python)',
    },
    'digest.sections': {
        text:
            'Ordered list of required sections. Each section name must have a ' +
            'matching sub-table below (messages, calendar, health, world, …).',
        scope: 'Backend (Python)',
    },
    'digest.optional_sections': {
        text:
            'Sections included only when their connectors return data. Use for ' +
            'noisy or intermittent feeds like GitHub or financial markets.',
        scope: 'Backend (Python)',
    },
    'digest.honorific': {
        text:
            "How the digest addresses you in its opening line ('sir', 'madam', " +
            "or your first name).",
        scope: 'Backend (Python)',
    },
    'digest.voice_id': {
        text:
            'TTS voice identifier (Cartesia or ElevenLabs voice ID). Empty = the ' +
            "persona's default voice.",
        scope: 'Backend (Python)',
    },
    'digest.voice_speed': {
        text: 'Playback-rate multiplier for the generated audio. 1.0 = normal.',
        scope: 'Backend (Python)',
    },
    'digest.tts_backend': {
        text:
            "Text-to-speech provider: 'cartesia' (recommended), 'elevenlabs', or " +
            "'openai'. Each requires its API key in [security.credentials].",
        scope: 'Backend (Python)',
    },
    'digest.messages.sources': {
        text:
            "Connectors that feed the 'messages' section " +
            '(e.g. gmail, slack, google_tasks, signal).',
        scope: 'Backend (Python)',
    },
    'digest.messages.max_items': {
        text: 'Cap on items shown for this section before summarisation.',
        scope: 'Backend (Python)',
    },
    'digest.messages.priority_contacts': {
        text:
            'Contacts flagged as VIP — their messages are always surfaced, even ' +
            'when below the importance threshold.',
        scope: 'Backend (Python)',
    },
    'digest.calendar.sources': {
        text: "Connectors that feed the 'calendar' section (e.g. gcalendar).",
        scope: 'Backend (Python)',
    },
    'digest.calendar.max_items': {
        text: 'Cap on calendar items in the digest.',
        scope: 'Backend (Python)',
    },
    'digest.health.sources': {
        text:
            "Connectors that feed the 'health' section (e.g. oura, apple_health, " +
            "whoop).",
        scope: 'Backend (Python)',
    },
    'digest.health.max_items': {
        text: 'Cap on health metrics included in the digest.',
        scope: 'Backend (Python)',
    },
    'digest.world.sources': {
        text:
            "Connectors for the 'world' section (news feeds, RSS, hacker-news, " +
            "…). Empty = skip the section.",
        scope: 'Backend (Python)',
    },
    'digest.world.max_items': {
        text: 'Cap on world-news items.',
        scope: 'Backend (Python)',
    },

    // -------------------------------------------------------------------
    // Agent-to-Agent
    // -------------------------------------------------------------------
    'a2a.enabled': {
        text:
            'Expose this OpenJarvis instance as an Agent-to-Agent server so ' +
            'other agents can call it as a tool. Runs on the main HTTP port ' +
            'under /a2a/*.',
        scope: 'Backend (Python). Restart required.',
    },

    // -------------------------------------------------------------------
    // System-prompt assembly
    // -------------------------------------------------------------------
    'system_prompt.soul_max_chars': {
        text:
            'Upper bound on characters from SOUL.md injected into the prompt. ' +
            'Excess is truncated according to truncation_strategy.',
        scope: 'Backend (Python)',
    },
    'system_prompt.memory_max_chars': {
        text: 'Upper bound on characters from MEMORY.md injected into the prompt.',
        scope: 'Backend (Python)',
    },
    'system_prompt.user_max_chars': {
        text: 'Upper bound on characters from USER.md injected into the prompt.',
        scope: 'Backend (Python)',
    },
    'system_prompt.skill_desc_max_chars': {
        text:
            'Per-skill description cap used when listing skills as tools in the ' +
            'prompt. Keeps long manifests from dominating the window.',
        scope: 'Backend (Python)',
    },
    'system_prompt.truncation_strategy': {
        text:
            "'head_tail' keeps the start and end (default). 'head' keeps the " +
            "prefix. 'tail' keeps the suffix. 'smart' asks the LLM to summarise " +
            "the overflow.",
        scope: 'Backend (Python)',
    },

    // -------------------------------------------------------------------
    // Agent manager (persistent user agents)
    // -------------------------------------------------------------------
    'agent_manager.enabled': {
        text:
            'Turn on the persistent-agent subsystem: CRUD of user-authored ' +
            'agents stored in a local SQLite DB. Required for `jarvis agent ' +
            'create/run/edit`.',
        scope: 'Backend (Python)',
    },
    'agent_manager.db_path': {
        text:
            'SQLite file that stores agent definitions, history, and metadata. ' +
            'Safe to back up while the server is stopped.',
        scope: 'Backend (Python)',
    },

    // -------------------------------------------------------------------
    // Memory files
    // -------------------------------------------------------------------
    'memory_files.soul_path': {
        text:
            'Path to SOUL.md — long-term persona, values, and immutable context. ' +
            'Edited by the agent via the memory skill.',
        scope: 'Backend (Python)',
    },
    'memory_files.memory_path': {
        text:
            'Path to MEMORY.md — episodic memory notes (recent events, facts, ' +
            'TODOs). The agent updates this regularly.',
        scope: 'Backend (Python)',
    },
    'memory_files.user_path': {
        text:
            'Path to USER.md — your profile, preferences, and explicit ' +
            'instructions. Merged into every system prompt.',
        scope: 'Backend (Python)',
    },
    'memory_files.nudge_interval': {
        text:
            'After this many conversation turns, the agent is nudged to update ' +
            'the memory files. Lower = more frequent writes.',
        scope: 'Backend (Python)',
    },

    // -------------------------------------------------------------------
    // Operators — long-running background agents
    // -------------------------------------------------------------------
    'operators.enabled': {
        text:
            'Turn on the operator subsystem: long-running background agents ' +
            'defined by TOML manifests, each with their own memory, tools, and ' +
            'schedule. Required for `jarvis operator start/stop/list`.',
        scope: 'Backend (Python). Restart required.',
    },
    'operators.manifests_dir': {
        text:
            'Directory scanned for operator manifest .toml files. Every file in ' +
            'this folder becomes a discoverable operator. Defaults to ' +
            '.openJarvis/operators under the project-local data folder.',
        scope: 'Backend (Python)',
    },
    'operators.auto_activate': {
        text:
            'Comma-separated operator IDs to start automatically when the server ' +
            'boots. Leave empty to activate operators manually via the CLI or API.',
        scope: 'Backend (Python)',
    },
};

export function getFieldHint(dotted: string): FieldHint | undefined {
    return FIELD_HINTS[dotted];
}
