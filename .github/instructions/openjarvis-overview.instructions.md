---
applyTo: "**"
---

# OpenJarvis — repo notes

## Stack
- Python 3.11, FastAPI, SQLite (WAL), `uv` for envs
- Frontend: React 19 + TS 5.7 + Vite + Tailwind v4 + lucide-react + motion + @react-three/fiber
- Rust crates under `rust/crates/` are an *optimization layer* only (used via `openjarvis._rust_bridge.get_rust_module()` inside specific Python tools). No separate registry to enumerate.

## Single source of truth
- Jarvis state persists in `.openJarvis/db/jarvis.db` via `JarvisStateStore` (KV).
- Key KV entries: `active_tools` (list|None), `active_skills` (list|None), `active_agents` (list|None = unrestricted), `hud_prefs`.
- `JarvisAgent._all_tools` / `_tools` / `_active_tool_names` / `_all_skills` / `_active_skills` / `_sensitive_tool_names` / `_active_agents` are the runtime projection of these.

## Validation cadence (run after each implementation step)
- Frontend: `cd frontend && npx tsc -b --noEmit` (no output = pass).
- Backend: `uv run pytest tests/evals/test_jarvis_agent_backend_skills.py tests/test_digest_integration.py tests/test_query_orchestrator.py -x -q` — expect **15 passed**.
- Backend **server restart required** for factory-level wiring changes (toolset, skillset, handle plumbing) to take effect; `tsc`/pytest alone won't prove HUD behavior.

## Implementation conventions
- Do NOT create markdown docs to summarize changes unless asked.
- Do NOT commit/PR unless asked.
- Implementation discipline: no speculative features, no new comments/docstrings on untouched code, no error handling for impossible cases.
- Prefer editing existing files; central enumerators live in `src/openjarvis/jarvis/` (e.g. `toolset.py`, `skillset.py`).

## Test-relevant modules
- `tests/evals/test_jarvis_agent_backend_skills.py` — regression guard for JarvisAgent wiring (tools/skills/active-set resolution).
- `tests/test_digest_integration.py`, `tests/test_query_orchestrator.py` — end-to-end sanity.
