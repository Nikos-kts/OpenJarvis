# Gotchas

> Read before touching unfamiliar modules. One entry per gotcha. Add when something bites you.

## Registries are global singletons

Agents and tools register at import time. In tests, `_clean_registries` (auto-use
fixture in `conftest.py`) must clear them between cases. If you're seeing test bleed
or duplicate registration errors, this is why.

## Rust extension must be compiled before full functionality

`uv run maturin develop -m rust/crates/openjarvis-python/Cargo.toml` must run before
importing `openjarvis_rust`. On Python 3.14+, set
`PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1` first.

## Optional deps are truly optional

Many optional dep groups (count fluctuates as we prune). Shared code must not
assume any of them are installed. Import-guard optional dependencies inside the
functions/classes that need them, not at module top-level.

## Hardware-specific tests need markers

Tests that require NVIDIA/AMD/Apple GPU must be marked (`@pytest.mark.nvidia`, etc.)
and will skip without the hardware present. Don't make them fail without markers.

## `make start` manages both servers

Don't start the backend or frontend manually if you used `make start` — use
`make stop` to tear down both. Orphan processes on 8000/5173 will cause confusing
startup errors.

---

*Add entries in the format: `## Short name` / one-paragraph explanation / what to do instead.*
