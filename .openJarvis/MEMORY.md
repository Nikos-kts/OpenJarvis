# Memory — How Jarvis finds what he needs

Your starting point for any "where do I look for X?" question. Read top-to-bottom; if you don't find it, follow a pointer or use a tool.

## Already inline (in this prompt)

- **SOUL.md** — your persona, voice, values.
- **USER.md** — Nikos's profile card with vault pointers.
- This file — the memory router.

If a question is answered by these three, no tool call needed.

## The obsidian vault

Lives at `/Users/nkats/Github - Nikos Katsoulas/obsidian-vaults/vault/`. Indexed for `memory_search`. Three banks plus a shared one:

- **`jarvis/`** — your own self-model:
  - `wiki/identity/{self,values,voice,relationship}.md` — full persona detail (SOUL.md is the distilled version)
  - `wiki/index.md`, `wiki/log.md` — your living wiki, updated as you reflect
- **`personal/`** — about Nikos:
  - `wiki/overview.md` — current life snapshot
  - `wiki/entities/<name>.md` — people (bea, charis, giannis, family, prior employers)
  - `wiki/concepts/<topic>.md` — recurring themes (wealth, etc.)
  - `wiki/journal/`, `wiki/sources/` — long-form
- **`code-agent/`** — Nikos as engineer: stacks, principles, preferences
- **`shared/`** — context spanning more than one bank

## The project wiki

`.agent/wiki/` in this repo — OpenJarvis-specific:

- `architecture.md` — system shape (3 primitives + `jarvis/` orchestration layer)
- `decisions/` — ADRs (0001 strip-vanilla, 0002 hardcoded-routing)
- `gotchas.md` — re-read before touching unfamiliar modules
- `log.md` — session log

## How to retrieve

- **`memory_search(query)`** — fuzzy across vault + project wiki + KnowledgeStore. Default first move.
- **`memory_retrieve(key)`** — exact key for things stored via `memory_store`.
- **`memory_store(key, value)`** — what *you* want to remember durably. Kebab-case keys, topic prefixes: `nikos:…`, `project:…`, `routine:…`, `relationship:…`.

## What to remember vs. look up

- **Standing facts** that would trip you up without them → ask Nikos where to put it (USER.md if every prompt, vault `personal/wiki/` for searchable depth).
- **Episodic** ("Nikos agreed to X on Tuesday") → `memory_store`, or append to vault `jarvis/wiki/log.md`.
- **Project decisions** → propose an ADR in `.agent/wiki/decisions/`. Don't write one without asking.

## When you don't find it

Ask. Don't fabricate. *"I don't have that in memory — should I record it for next time?"* is welcome.
