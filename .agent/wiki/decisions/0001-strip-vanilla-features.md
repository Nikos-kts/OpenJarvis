# ADR-0001 — Strip vanilla openJarvis features (phased)

**Date:** 2026-05-03
**Status:** in progress (Phase A + A.1 landed)

## Context

Project was forked from open-jarvis/OpenJarvis and personalised on `main-dev`.
After merging `main-dev` → `main` (2026-05-03), the codebase still carries
~250K LOC of vanilla openJarvis surface that the personalised `src/openjarvis/jarvis/`
package does not depend on. Goal: keep what supports a personal, local-first,
voice-capable Jarvis on M3 Pro; drop the rest.

The personalised package imports only from `core`, `agents`, `engine`, `tools`,
`skills`, `server`. Anything else is candidate territory until proven otherwise.

## Decision

Strip in phases, each its own commit, smoke-tested before commit. No tags.

### Phase A — clean cuts (landed 2026-05-03)

- `src/openjarvis/voice/` — empty placeholder, 0 inbound refs.
- `examples/` — 10 vanilla demo projects, 0 src refs.

### Phase A.1 — `bench/` strip (landed 2026-05-03)

Small (68K, 6 files). Cut: `bench/` + `cli/bench_cmd.py` + `tests/bench/` +
bench refs in `tests/integration/test_integration.py` + `bench` cli command
registration. `BenchmarkRegistry` in `core/registry.py` left as-is (generic).
Energy/GPU optional deps left intact — they're shared with `telemetry/`.

### Phase A.2 — `evals/` + `learning/` (deferred, needs review)

`learning/` (1.1M) and `evals/` (2.6M) are co-dependent and have ~30 inbound
import sites across `agents/`, `server/`, `system/`, `skills/`, `recipes/`,
`cli/`. **Both are listed as core architectural primitives in
[[architecture]] (primitives 1+5).** Stripping them is not cleanup —
it's a redesign.

Open question for the architecture revision:
- Does personalised Jarvis need a trace → routing → eval → train loop at all?
- If yes, can it be a much lighter "lite-learning" module (route policy +
  trace recording), dropping LoRA/SFT/distillation/optimize/GRPO?
- If no, replace with a stub or remove entirely + delete dependent CLI
  commands (`eval_cmd`, `compose_cmd`, `bench_cmd`, `optimize_cmd`).

### Phase A.3 — `intelligence/` rename (optional, low priority)

`intelligence/` is just `model_catalog.py` (1024 LOC). Used by `core/config.py`
and several `cli/*`. Load-bearing — **keep**. A cosmetic move into `engine/`
or `core/` is possible but is gratuitous churn. No action unless it earns its
keep elsewhere.

### Phase B — module reviews (case-by-case)

`a2a`, `workflow`, `operators`, `prompt`, `templates`, `daemon`, `scheduler`,
`sandbox`, `mcp`. Decide per-module after per-module inbound-import survey.

### Phase C — connector / channel pruning

`connectors/` (36 files) and `channels/` (34 files). Keep the packages,
prune individual integrations to what Nikos actually uses. Recommended
keep-list to be drafted; user picks.

### Phase D — `pyproject.toml` extras prune

39 extras → ~10–15. Wait until A–C land so we know what remains.

### Phase E — verify + commit per phase

`uv run ruff check . && uv run ruff format --check . && uv run pytest tests/ -v`
plus `make start` + smoke `/v1/jarvis/*`. Per-phase commits. No tags.

## Consequences

**Easier**
- Repo size and import surface shrink to what personalised Jarvis actually uses.
- Future agents reading [[architecture]] won't be misled by primitives
  the project doesn't intend to keep.
- Fewer optional deps → lighter `uv sync`, less hardware-gated test surface.

**Harder**
- `architecture.md` will need a partial rewrite once Phase A.2 lands —
  the "five primitives" framing is no longer accurate after intelligence/learning
  decisions.
- The CLI loses `eval`, `optimize`, `bench`, `compose` subcommands. If anything
  external (CI, scripts, the wiki) referenced those, it breaks.
- Some reachability of trace-based "self-improving" features is lost. If we
  later want them back, recover from `backup/pre-main-dev-merge-20260503` or
  re-implement leaner.

**Reversible?** Yes — each phase is its own commit; `git revert <phase>` rolls
back without disturbing later phases.
