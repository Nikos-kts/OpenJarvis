"""Tests for :mod:`openjarvis.server.jarvis_primary_routes`."""

from __future__ import annotations

import os
import tempfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from openjarvis.agents.bootstrap import ensure_default_jarvis_agent
from openjarvis.agents.manager import AgentManager
from openjarvis.server.jarvis_primary_routes import (
    _deep_merge,
    create_jarvis_primary_router,
)


@pytest.fixture
def client():
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "agents.db")
        manager = AgentManager(db_path=db)
        app = FastAPI()
        app.include_router(create_jarvis_primary_router(manager))
        c = TestClient(app)
        c._manager = manager  # type: ignore[attr-defined]
        yield c


def test_deep_merge_merges_nested_dicts():
    base = {"a": 1, "persona": {"tone": "warm", "verbosity": "balanced"}}
    patch = {"persona": {"tone": "cold"}, "new_key": True}
    out = _deep_merge(base, patch)
    assert out == {
        "a": 1,
        "persona": {"tone": "cold", "verbosity": "balanced"},
        "new_key": True,
    }
    # Immutable w.r.t. base.
    assert base["persona"]["tone"] == "warm"


def test_get_primary_404_when_not_bootstrapped(client):
    resp = client.get("/v1/jarvis/primary")
    assert resp.status_code == 404


def test_get_and_patch_primary_config(client):
    ensure_default_jarvis_agent(client._manager, model="m", preferred_engine="ollama")

    resp = client.get("/v1/jarvis/primary/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["config"]["persona"]["verbosity"] == "balanced"
    agent_id = body["agent_id"]

    resp = client.patch(
        "/v1/jarvis/primary/config",
        json={
            "config": {
                "persona": {"tone": "formal"},
                "temperature": 0.15,
            }
        },
    )
    assert resp.status_code == 200
    merged = resp.json()["config"]
    assert merged["persona"]["tone"] == "formal"
    # Untouched nested keys remain.
    assert merged["persona"]["verbosity"] == "balanced"
    assert merged["temperature"] == pytest.approx(0.15)

    # Round-trip via the full record endpoint.
    full = client.get("/v1/jarvis/primary").json()
    assert full["id"] == agent_id
    assert full["config"]["persona"]["tone"] == "formal"


def test_reset_primary_config(client):
    ensure_default_jarvis_agent(client._manager, model="m", preferred_engine="ollama")
    client.patch(
        "/v1/jarvis/primary/config",
        json={"config": {"persona": {"tone": "zzz"}, "max_turns": 1}},
    )
    resp = client.post("/v1/jarvis/primary/reset")
    assert resp.status_code == 200
    cfg = resp.json()["config"]
    assert "butler" in cfg["persona"]["tone"].lower()
    assert cfg["max_turns"] == 8
    # Model is preserved from existing record.
    assert cfg["model"] == "m"
