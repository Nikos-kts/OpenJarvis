# Log

> One entry per session. Format: `## [YYYY-MM-DD] <op> | <subject>`

## [2026-04-30] setup | scaffold .agent/ and .claude/

- Created `.claude/CLAUDE.md` (agent operating manual with vault links)
- Created `.agent/wiki/` (index, architecture, gotchas, log, decisions/)
- Architecture notes seeded from root CLAUDE.md
- Gotchas seeded from known registry and Rust extension constraints

## [2026-05-03] merge | reset main → main-dev

- Hard reset: local + origin `main` now at `ed6a3ff` (was main-dev's tip; 34 commits ahead, ~117 files, +11.7K/-1.3K)
- Backup tag `backup/pre-main-dev-merge-20260503` preserves prior main HEAD (the local-only `.agent/wiki/` docs commit)
- `.agent/wiki/` was wiped by the reset (only existed on old main); restored from backup before continuing

## [2026-05-03] cleanup | Phase A — drop voice/ + examples/

- Deleted `src/openjarvis/voice/` (empty placeholder, only stale `__pycache__`; 0 inbound src refs; all speech lives in sibling `src/openjarvis/speech/`)
- Deleted `examples/` (10 vanilla showcase projects: twitter_bot, browser_assistant, code_companion, daily_digest, deep_research, doc_qa, messaging_hub, multi_model_router, scheduled_ops, security_scanner; 0 src refs)
- Smoke: `import openjarvis` + full `openjarvis.jarvis.*` imports OK; 31 ruff E501s in `server/routes.py` are pre-existing
- Other Phase A targets (learning/, evals/, bench/, intelligence/) deferred — entanglement + architectural-primitive status, see [[decisions/0001-strip-vanilla-features]]

## [2026-05-03] cleanup | Phase A.1 — strip bench/

- Deleted `src/openjarvis/bench/` (6 files, ~500 LOC), `src/openjarvis/cli/bench_cmd.py`, `tests/bench/`
- Removed `bench` import + `cli.add_command(bench, ...)` in `cli/__init__.py`
- Surgically removed two bench test classes from `tests/integration/test_integration.py` (TestBenchmarkRegistryDiscovery, TestBenchmarkSuiteRunAll)
- Left `BenchmarkRegistry` in `core/registry.py` — generic registry, no remaining callers but harmless
- Smoke: cli import OK; `bench` no longer in command list

## [2026-05-03] cleanup | Phase B — cut a2a/ + templates/

- Deleted `src/openjarvis/a2a/` (5 files, 460 LOC) and `tests/a2a/` — only inbound refs were tests
- Deleted `src/openjarvis/templates/` (2 files, 115 LOC) and `tests/templates/` — only inbound ref was its own test
- Updated `architecture.md` to drop the Agent-to-Agent RPC mention
- Smoke: imports OK; no orphan refs

Phase B "review" modules (prompt, workflow, daemon) deferred — not yet cut, pending closer look.

## [2026-05-03] decision | ADR-0002 — hardcoded routing with UI↔backend config

- Adaptive routing has no signal at N=1; replaced with per-agent hardcoded routing in user-editable config, exposed via UI
- Per-agent (Jarvis + each sub-agent) `engine` + `model` selection — local OR cloud, user's call
- Unblocks A.2 — `learning/` adaptive layer no longer needed; `evals/` not relevant for single-user
- See [[decisions/0002-hardcoded-routing-with-ui-config]]

## [2026-05-03] cleanup | Phase A.2.a — drop CLI commands tied to learning/evals

- Deleted `src/openjarvis/cli/{compose,eval,optimize}_cmd.py`
- Removed 4 imports + 4 `cli.add_command(...)` calls from `cli/__init__.py`: `compose`, `eval_group`, `optimize_group`, `learning_group` (last from `learning.distillation.cli`)
- `feedback_cmd` left intact — it uses `traces.store`, not learning/evals; trace recording stays per ADR-0001 (Q1)
- Smoke: cli imports OK; eval/compose/optimize/learning not in command list
- Next: A.2.b — salvage skill_discovery, strip rest of learning/ + evals/

## [2026-05-03] cleanup | Phase A.2.b — strip learning/ + evals/, salvage skill_discovery

- Salvaged `learning/agents/skill_discovery.py` → `skills/discovery.py` (verbatim — already lean ~200 LOC, no ML/RL/LoRA, just frequency-based pattern miner)
- Moved `tests/learning/test_skill_discovery.py` → `tests/skills/test_discovery.py` (import updated)
- Patched 9 inbound import sites:
  - `agents/orchestrator.py` — replaced `learning.intelligence.orchestrator.prompt_registry.build_system_prompt` fallback with inline default `"You are a helpful assistant."` (Jarvis overrides via persona)
  - `agents/executor.py` — removed router_policy override block (per ADR-0002 hardcoded routing)
  - `server/api_routes.py` — updated skill_discovery import path; deleted `/v1/learning/policy` endpoint and entire `/v1/optimize/*` router (3 endpoints + `OptimizeRunRequest` model + include + `__all__`)
  - `server/routes.py` — removed complexity-based max_tokens bump; `complexity_info = None` per ADR-0002
  - `cli/ask.py` — removed `learning.routing.complexity` import + score_complexity call + debug log
  - `system/core.py` — dropped TYPE_CHECKING imports of `RouterPolicy`/`LearningOrchestrator`; removed `router` field and `_learning_orchestrator` field from JarvisSystem
  - `system/builder.py` — removed `_setup_learning_orchestrator` static method + its caller (lines 214 + 298)
  - `recipes/composer.py` — deleted `recipe_to_eval_suite` (kept `recipe_to_operator`); updated `__all__` and `recipes/__init__.py`
  - `skills/manager.py` — updated skill_discovery import path
- Deleted `src/openjarvis/learning/` (~14K LOC, 7 subpackages) and `src/openjarvis/evals/` (~32K LOC, datasets + scorers + benchmarks)
- Deleted broken/obsolete tests: `tests/learning/`, `tests/evals/`, `tests/intelligence/{test_router,test_routing_models}.py`, `tests/agents/test_learning_integration.py`, `tests/telemetry/test_energy_wiring.py` (CLI bench-tied), `tests/test_orchestrator_learning/` (whole dir)
- pyproject.toml: removed extras `orchestrator-training`, `learning-dspy`, `learning-gepa`, `eval-wandb`, `eval-sheets`
- Smoke: imports OK; pytest collect = 4583 tests, 0 errors (down from 4592)
- Architecture is now effectively 4 primitives (Engine, Agents, Tools+Memory, Intelligence-as-model-catalog). A.2.c renames intelligence/ into engine/ next; A.2.d rewrites architecture.md.

## [2026-05-03] cleanup | Phase A.2.d — architecture.md rewrite (3 primitives)

- Rewrote `architecture.md` to reflect the post-strip shape: 3 primitives (Engine, Agents, Tools+Memory) + `jarvis/` orchestration layer + Skills + Trace recording + channels/connectors as supporting cast
- Added a "History note" pointing to ADR-0001 and ADR-0002 so future readers know why the 5-primitive frame is gone
- Documented `engine/model_catalog.py` (post-A.2.c home of BUILTIN_MODELS), per-agent hardcoded routing (per ADR-0002), and `skills/discovery.py` (salvaged frequency-based pattern miner)
- Tidied `gotchas.md` — replaced concrete "39 optional dep groups" with "many" since the count fluctuates as we prune
- A.2 fully landed. Next: implement per-agent UI↔backend config endpoints per ADR-0002, when the user is ready.

## [2026-05-03] cleanup | Phase A.2.c — absorb intelligence/ into engine/

- `git mv src/openjarvis/intelligence/model_catalog.py → src/openjarvis/engine/model_catalog.py`; deleted empty `src/openjarvis/intelligence/__init__.py` + dir
- `git mv tests/intelligence/test_model_catalog{,_extended}.py → tests/engine/`
- Updated 7 import sites: `core/config.py`, `cli/{ask,chat_cmd,model,serve}.py`, `tests/integration/test_integration_extended.py`, `tests/cli/test_chat_cmd.py`, plus the two moved tests
- Pattern: `from openjarvis.intelligence(.model_catalog) import X` → `from openjarvis.engine.model_catalog import X`
- The `config.intelligence` namespace in `core/config.py` is unrelated (runtime knobs like temperature/max_tokens) and stays as-is
- Smoke: imports OK; 65 BUILTIN_MODELS; pytest collect = 4583 tests, 0 errors
- Architecture is now 3 primitives — Engine, Agents, Tools+Memory. A.2.d will rewrite architecture.md to reflect this and elevate `jarvis/` as the orchestration layer over them.

## [2026-05-03] cleanup | Phase C — connector + channel pruning

- Connectors cut: `dropbox`, `gmail_imap`, `apple_music`, `outlook`, `google_tasks` (5)
- Spotify kept; user prefers spotify over apple_music for the music data source (correction during execution)
- Channels cut: 12 niche/broadcast adapters — `line`, `viber`, `messenger`, `reddit`, `mastodon`, `xmpp`, `rocketchat`, `zulip`, `twitter`, `twitch`, `nostr`, `twilio_sms`
- WhatsApp kept (`whatsapp.py` + `whatsapp_baileys.py` + `whatsapp_baileys_bridge/`); telegram, slack, discord, gmail, signal, teams, matrix, mattermost, feishu, bluebubbles, sendblue, google_chat, irc, webhook, webchat, email also kept
- Edits:
  - `channels/__init__.py` — 12 entries removed from `_CHANNEL_MODULES`
  - `connectors/__init__.py` — 5 try/except auto-import blocks removed
  - `tests/connectors/test_connector_health.py` — gmail_imap, outlook, dropbox removed from `_TOKEN_CONNECTORS`
  - `tests/connectors/test_new_connectors_live.py` — `TestGoogleTasksLive` class removed
  - `cli/deep_research_setup_cmd.py` — gmail_imap + outlook elif branches removed in `_instantiate_connector`
  - `pyproject.toml` — 12 `channel-*` extras removed
- Tests deleted: `test_twilio_sms`, `test_twitter_channel`, `test_twitter_bot_e2e`, `test_channels_phase21`, `test_dropbox`, `test_outlook`, `test_google_tasks`, `test_apple_music`
- Smoke: imports OK; no orphan refs to cut targets
