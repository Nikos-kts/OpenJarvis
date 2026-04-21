"""Tests for :mod:`openjarvis.tools.delegate_agent`."""

from __future__ import annotations

import importlib
import json
import os
import tempfile

import pytest

from openjarvis.agents.delegation import (
    clear_delegation_context,
    set_delegation_context,
)
from openjarvis.agents.manager import AgentManager
from openjarvis.core.registry import ToolRegistry


@pytest.fixture(autouse=True)
def _register_delegation_tools():
    """The project-wide ``_clean_registries`` conftest fixture wipes
    ToolRegistry before every test, so we have to re-register the
    delegation tools (they live on decorators executed at import time).
    """
    # Import is idempotent; reload if already imported in this process.
    import openjarvis.tools.delegate_agent as _mod

    importlib.reload(_mod)
    yield


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


def test_list_available_agents_returns_catalog(manager):
    manager.create_agent(
        name="Researcher",
        agent_type="monitor_operative",
        config={"visible_to_brain": True, "delegation_tags": ["research"]},
    )
    set_delegation_context(manager, engine=None, model="m")
    tool = ToolRegistry.get("list_available_agents")()
    result = tool.execute()
    assert result.success is True
    payload = json.loads(result.content)
    assert payload["success"] is True
    assert [a["name"] for a in payload["agents"]] == ["Researcher"]


def test_list_available_agents_no_context():
    tool = ToolRegistry.get("list_available_agents")()
    result = tool.execute()
    assert result.success is False
    assert json.loads(result.content)["error"] == "no_delegation_context"


def test_delegate_to_agent_requires_goal(manager):
    set_delegation_context(manager, engine=None, model="m")
    tool = ToolRegistry.get("delegate_to_agent")()
    result = tool.execute(goal="   ", agent_name="Any")
    assert result.success is False
    assert json.loads(result.content)["error"] == "missing_goal"


def test_delegate_to_agent_requires_target(manager):
    set_delegation_context(manager, engine=None, model="m")
    tool = ToolRegistry.get("delegate_to_agent")()
    result = tool.execute(goal="do thing")
    assert result.success is False
    assert json.loads(result.content)["error"] == "missing_target"


class _FakeResult:
    def __init__(self):
        self.content = "delegated-answer"
        self.turns = 1
        self.tool_results = []


class _FakeAgent:
    def __init__(self, **_):
        pass

    def run(self, _):
        return _FakeResult()


def test_delegate_to_agent_runs_target(manager, monkeypatch):
    from openjarvis.core import registry as _reg

    monkeypatch.setattr(
        _reg.AgentRegistry, "get", staticmethod(lambda _name: _FakeAgent)
    )
    rec = manager.create_agent(
        name="Scribe",
        agent_type="monitor_operative",
        config={"visible_to_brain": True},
    )
    set_delegation_context(manager, engine=None, model="m")
    tool = ToolRegistry.get("delegate_to_agent")()
    result = tool.execute(goal="write it up", agent_id=rec["id"])
    assert result.success is True
    payload = json.loads(result.content)
    assert payload["success"] is True
    assert payload["content"] == "delegated-answer"
    assert payload["agent_name"] == "Scribe"
