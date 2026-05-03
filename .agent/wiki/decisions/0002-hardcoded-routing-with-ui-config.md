# ADR-0002 — Hardcoded routing with UI↔backend config

**Date:** 2026-05-03
**Status:** accepted

## Context

OpenJarvis (vanilla) shipped an adaptive routing layer in `learning/`: traces
fed a router that updated weights toward minimising a 60/20/10/10 mix of
accuracy, latency, cost, energy. That works at scale (many users, many
requests, statistical signal) but for a personal single-user Jarvis it has
no signal — N=1 means the router is fitting noise.

At the same time, Nikos wants real flexibility: for Jarvis itself and for
each sub-agent he creates, he wants to pick local vs cloud and specific
model (e.g. Jarvis on Claude, "DigestAgent" on a local Llama, "CodeAgent"
on Claude with a different prompt).

## Decision

- **Routing is hardcoded** in user-editable config (`~/.openjarvis/config.toml`
  or equivalent), keyed by agent identity.
- **Per-agent model selection** is a first-class field: `engine` (backend) +
  `model` (specific model id). Jarvis itself counts as one agent.
- **UI surface** in `frontend/` lets Nikos edit these without touching files.
  Backend exposes `GET/PUT /v1/jarvis/config/agents/{id}` (or similar — exact
  shape TBD when implementing).
- **No adaptive layer.** No trace-driven routing updates. No A/B framework.
  No reward functions.

## Consequences

**Easier**
- Predictable behaviour: the agent always uses the model the config says.
  Debugging is "look at the config", not "look at the routing weights".
- Testable: config in, behaviour out, no learned state to mock.
- Aligned with the personal-Jarvis use case: one user is making the
  trade-offs explicit, not relying on noisy automation.

**Harder**
- Nikos must make routing decisions himself (with sensible defaults and
  recommendations from `jarvis init` based on hardware probe).
- Future "automatically pick the cheaper local model when energy is high"
  ideas require either reverting this ADR or a careful additive ADR.

**Reversible** — yes. Adding adaptive routing later is additive: route by
config first, with optional "if config says auto, defer to <new layer>".
The cleanup that depends on this ADR (Phase A.2 — strip `learning/` + `evals/`)
is destructive, but the salvage path is `git revert` + the
`backup/pre-main-dev-merge-20260503` tag.

## Implementation pointers (for the future)

- Config schema: `agents: { jarvis: { engine, model, … }, code_companion: { … } }`.
- Backend endpoints: `routes.py` already hosts `/v1/jarvis/*`; add
  `/v1/jarvis/config/agents` CRUD.
- Frontend: agent settings page reads/writes via those endpoints.
- Defaults: `jarvis init` populates the config with hardware-appropriate
  picks from `engine/model_catalog.py` (post-A.2.c rename).
