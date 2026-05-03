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
