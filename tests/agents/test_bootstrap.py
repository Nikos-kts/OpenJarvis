"""Tests for :mod:`openjarvis.agents.bootstrap`."""

from __future__ import annotations

import os
import tempfile

import pytest

from openjarvis.agents.bootstrap import (
    default_jarvis_config,
    ensure_default_jarvis_agent,
    find_jarvis_agent,
)
from openjarvis.agents.manager import AgentManager


@pytest.fixture
def manager():
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "agents.db")
        m = AgentManager(db_path=db)
        yield m


def test_default_config_shape():
    cfg = default_jarvis_config(model="qwen2.5:7b", preferred_engine="ollama")
    assert cfg["schedule_type"] == "manual"
    assert cfg["model"] == "qwen2.5:7b"
    assert cfg["preferred_engine"] == "ollama"
    assert "think" in cfg["tools"]
    assert cfg["visible_to_brain"] is True
    # Nested settings surfaced for the primary-config UI.
    assert isinstance(cfg["persona"], dict)
    assert "butler" in cfg["persona"]["tone"].lower()
    assert cfg["persona"]["verbosity"] in {"concise", "balanced", "detailed"}
    assert isinstance(cfg["intent"], dict)
    assert cfg["intent"]["policy"] in {"heuristic", "hybrid", "llm"}
    assert 0.0 <= float(cfg["intent"]["confidence_threshold"]) <= 1.0
    assert isinstance(cfg["voice"], dict)
    assert cfg["voice"]["enabled"] is True
    assert cfg["voice"]["realtime"] is True
    assert isinstance(cfg["wake"], dict)
    assert cfg["wake"]["mode"] in {"clap", "wakeword", "off"}
    assert cfg["delegation"]["tags"] == cfg["delegation_tags"]


def test_default_config_reads_toml_template(tmp_path):
    toml = tmp_path / "jarvis_primary.toml"
    toml.write_text(
        """
[general]
description = "Custom description"

[persona]
tone = "dry and laconic"
verbosity = "concise"

[voice]
enabled = false
realtime = false

[runtime]
max_turns = 5
temperature = 0.1

[tools]
allow = ["think"]
""".strip()
    )
    cfg = default_jarvis_config(
        model="m", preferred_engine="ollama", template_path=toml
    )
    assert cfg["description"] == "Custom description"
    assert cfg["persona"]["tone"] == "dry and laconic"
    assert cfg["persona"]["verbosity"] == "concise"
    # Persona keys not in TOML keep their built-in defaults.
    assert cfg["persona"]["proactive_level"] == "medium"
    assert cfg["voice"]["enabled"] is False
    assert cfg["voice"]["realtime"] is False
    assert cfg["max_turns"] == 5
    assert cfg["temperature"] == pytest.approx(0.1)
    assert cfg["tools"] == ["think"]


def test_default_config_falls_back_on_bad_toml(tmp_path):
    toml = tmp_path / "bad.toml"
    toml.write_text("this is not = valid [ toml")
    cfg = default_jarvis_config(template_path=toml)
    # Still valid built-in defaults.
    assert cfg["persona"]["verbosity"] == "balanced"
    assert "think" in cfg["tools"]


def test_find_none_when_empty(manager):
    assert find_jarvis_agent(manager) is None


def test_ensure_creates_when_missing(manager):
    agent, created = ensure_default_jarvis_agent(
        manager, model="qwen2.5:7b", preferred_engine="ollama"
    )
    assert created is True
    assert agent["agent_type"] == "jarvis"
    assert agent["name"] == "Jarvis"
    # Created agent is now discoverable.
    found = find_jarvis_agent(manager)
    assert found is not None
    assert found["id"] == agent["id"]


def test_ensure_is_idempotent(manager):
    first, created1 = ensure_default_jarvis_agent(manager)
    assert created1 is True
    second, created2 = ensure_default_jarvis_agent(manager)
    assert created2 is False
    assert second["id"] == first["id"]
    # Only one jarvis agent exists.
    jarvis_agents = [
        a for a in manager.list_agents() if a.get("agent_type") == "jarvis"
    ]
    assert len(jarvis_agents) == 1


def test_ensure_does_not_replace_user_created_agent(manager):
    # User-created with a custom name — must not be overwritten.
    manager.create_agent(name="My Jarvis", agent_type="jarvis", config={"max_turns": 3})
    agent, created = ensure_default_jarvis_agent(manager)
    assert created is False
    assert agent["name"] == "My Jarvis"
    assert agent["config"]["max_turns"] == 3
