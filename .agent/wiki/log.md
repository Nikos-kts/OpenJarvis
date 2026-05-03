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
