"""Tests for :mod:`openjarvis.agents.delegation`."""

from __future__ import annotations

import os
import tempfile
from types import SimpleNamespace

import pytest

from openjarvis.agents.delegation import (
    clear_delegation_context,
    get_delegation_context,
    list_delegatable_agents,
    run_delegated_agent,
    set_delegation_context,
)
from openjarvis.agents.manager import AgentManager


@pytest.fixture(autouse=True)
def _isolate_ctx():
    clear_delegation_context()
    yield
    clear_delegation_context()


@pytest.fixture
def manager():
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "agents.db")
        yield AgentManager(db_path=db)


def test_set_and_get_context(manager):
    assert get_delegation_context() is None
    set_delegation_context(manager, engine="E", model="m", event_bus="bus")
    ctx = get_delegation_context()
    assert ctx is not None
    assert ctx.manager is manager
    assert ctx.engine == "E"
    assert ctx.model == "m"
    assert ctx.event_bus == "bus"


def test_list_delegatable_excludes_jarvis_and_invisible(manager):
    manager.create_agent(name="Jarvis", agent_type="jarvis", config={"visible_to_brain": True})
    manager.create_agent(
        name="Researcher",
        agent_type="monitor_operative",
        config={"visible_to_brain": True, "delegation_tags": ["research"]},
    )
    manager.create_agent(
        name="Hidden",
        agent_type="monitor_operative",
        config={"visible_to_brain": False},
    )
    catalog = list_delegatable_agents(manager)
    names = [a["name"] for a in catalog]
    assert "Researcher" in names
    assert "Jarvis" not in names
    assert "Hidden" not in names
    entry = next(a for a in catalog if a["name"] == "Researcher")
    assert entry["tags"] == ["research"]


def test_list_delegatable_reads_nested_delegation_block(manager):
    manager.create_agent(
        name="Scribe",
        agent_type="monitor_operative",
        config={"delegation": {"visible_to_brain": True, "tags": ["notes"]}},
    )
    catalog = list_delegatable_agents(manager)
    assert [a["name"] for a in catalog] == ["Scribe"]
    assert catalog[0]["tags"] == ["notes"]


class _FakeResult:
    def __init__(self, content="ok", turns=1, tool_results=()):
        self.content = content
        self.turns = turns
        self.tool_results = list(tool_results)


class _FakeAgent:
    last_init_kwargs = None
    last_goal = None

    def __init__(self, **kwargs):
        _FakeAgent.last_init_kwargs = kwargs

    def run(self, goal):
        _FakeAgent.last_goal = goal
        return _FakeResult(content=f"echo: {goal}", turns=2)


class _FakeFailingAgent:
    def __init__(self, **_):
        pass

    def run(self, _):
        raise RuntimeError("boom")


def _patch_registry(monkeypatch, agent_cls):
    from openjarvis.core import registry as _reg

    monkeypatch.setattr(
        _reg.AgentRegistry, "get", staticmethod(lambda _name: agent_cls)
    )


def test_run_delegated_returns_not_found_when_missing(manager):
    out = run_delegated_agent(
        manager, engine=SimpleNamespace(), model="m", agent_id="nope", goal="hi"
    )
    assert out["success"] is False
    assert out["error"] == "not_found"


def test_run_delegated_blocks_self_delegation(manager):
    jarvis = manager.create_agent(
        name="Jarvis",
        agent_type="jarvis",
        config={"visible_to_brain": True},
    )
    out = run_delegated_agent(
        manager,
        engine=SimpleNamespace(),
        model="m",
        agent_id=jarvis["id"],
        goal="hi",
    )
    assert out["success"] is False
    assert out["error"] == "self_delegation"


def test_run_delegated_blocks_invisible(manager):
    rec = manager.create_agent(
        name="Hidden",
        agent_type="monitor_operative",
        config={"visible_to_brain": False},
    )
    out = run_delegated_agent(
        manager,
        engine=SimpleNamespace(),
        model="m",
        agent_id=rec["id"],
        goal="hi",
    )
    assert out["success"] is False
    assert out["error"] == "not_visible"


def test_run_delegated_invokes_agent_and_returns_content(manager, monkeypatch):
    _patch_registry(monkeypatch, _FakeAgent)
    rec = manager.create_agent(
        name="Scribe",
        agent_type="monitor_operative",
        config={"visible_to_brain": True, "tools": [], "max_turns": 3},
    )
    out = run_delegated_agent(
        manager,
        engine=SimpleNamespace(),
        model="m",
        agent_id=rec["id"],
        goal="summarise the news",
    )
    assert out["success"] is True
    assert out["content"] == "echo: summarise the news"
    assert out["turns"] == 2
    assert _FakeAgent.last_goal == "summarise the news"
    # Ensure we passed config-driven kwargs.
    assert _FakeAgent.last_init_kwargs["max_turns"] == 3


def test_run_delegated_resolves_by_name(manager, monkeypatch):
    _patch_registry(monkeypatch, _FakeAgent)
    manager.create_agent(
        name="Researcher",
        agent_type="monitor_operative",
        config={"visible_to_brain": True},
    )
    out = run_delegated_agent(
        manager,
        engine=SimpleNamespace(),
        model="m",
        agent_name="researcher",
        goal="find X",
    )
    assert out["success"] is True


def test_run_delegated_catches_agent_exception(manager, monkeypatch):
    _patch_registry(monkeypatch, _FakeFailingAgent)
    rec = manager.create_agent(
        name="Brittle",
        agent_type="monitor_operative",
        config={"visible_to_brain": True},
    )
    out = run_delegated_agent(
        manager,
        engine=SimpleNamespace(),
        model="m",
        agent_id=rec["id"],
        goal="hi",
    )
    assert out["success"] is False
    assert out["error"] == "run_failed"
    assert "boom" in out["content"]
