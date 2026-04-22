"""Tests for :mod:`openjarvis.core.reloader`."""

from __future__ import annotations

from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from openjarvis.core.config import load_config  # noqa: E402
from openjarvis.core.config_service import ConfigService  # noqa: E402
from openjarvis.core.events import EventBus, EventType  # noqa: E402
from openjarvis.core.reloader import SubsystemReloader  # noqa: E402
from openjarvis.server.config_routes import router as config_router  # noqa: E402


@pytest.fixture
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    cfg_path = tmp_path / "config.toml"
    monkeypatch.setenv("OPENJARVIS_CONFIG", str(cfg_path))
    load_config.cache_clear()

    app = FastAPI()
    app.include_router(config_router)
    app.state.bus = EventBus(record_history=True)
    app.state.config_service = ConfigService(path=cfg_path)
    app.state.config = app.state.config_service.current()
    app.state.subsystem_reloader = SubsystemReloader(app)
    return app


class TestReloaderMatching:
    def test_engine_prefix_is_restart_required(self, app: FastAPI) -> None:
        reloader: SubsystemReloader = app.state.subsystem_reloader
        reasons = reloader.apply(["engine.ollama.host"])
        assert reasons
        assert "engine" in reasons[0].lower()

    def test_server_host_is_restart_required(self, app: FastAPI) -> None:
        reloader: SubsystemReloader = app.state.subsystem_reloader
        reasons = reloader.apply(["server.host"])
        assert reasons
        assert "server" in reasons[0].lower()

    def test_intelligence_is_hot_reloadable(self, app: FastAPI) -> None:
        reloader: SubsystemReloader = app.state.subsystem_reloader
        reasons = reloader.apply(["intelligence.temperature"])
        assert reasons == []

    def test_empty_changes(self, app: FastAPI) -> None:
        reloader: SubsystemReloader = app.state.subsystem_reloader
        assert reloader.apply([]) == []

    def test_longest_prefix_wins(self, app: FastAPI) -> None:
        reloader: SubsystemReloader = app.state.subsystem_reloader
        captured: list[str] = []

        def handler(app, cfg, keys):  # noqa: ARG001
            captured.append("specific")
            return None

        reloader.register("intelligence.temperature", handler)
        reloader.apply(["intelligence.temperature"])
        assert captured == ["specific"]


class TestReloaderEvents:
    def test_publishes_config_updated(self, app: FastAPI) -> None:
        reloader: SubsystemReloader = app.state.subsystem_reloader
        reloader.apply(["intelligence.temperature", "engine.ollama.host"])
        history = app.state.bus.history
        updated = [e for e in history if e.event_type == EventType.CONFIG_UPDATED]
        assert len(updated) == 1
        data = updated[0].data
        assert set(data["changed_keys"]) == {
            "intelligence.temperature",
            "engine.ollama.host",
        }
        assert data["restart_required"] is True


class TestReloaderE2E:
    def test_patch_route_returns_hot_reload(self, app: FastAPI) -> None:
        client = TestClient(app)
        resp = client.patch(
            "/v1/config",
            json={"patch": {"intelligence.temperature": 0.42}},
        )
        body = resp.json()
        assert body["restart_required"] is False
        assert body["restart_reasons"] == []

    def test_patch_route_flags_restart(self, app: FastAPI) -> None:
        client = TestClient(app)
        resp = client.patch(
            "/v1/config",
            json={"patch": {"server.host": "0.0.0.0"}},
        )
        body = resp.json()
        assert body["restart_required"] is True
        assert body["restart_reasons"]

    def test_app_state_config_is_swapped(self, app: FastAPI) -> None:
        client = TestClient(app)
        original = app.state.config
        client.patch(
            "/v1/config",
            json={"patch": {"intelligence.temperature": 0.37}},
        )
        assert app.state.config is not original
        assert app.state.config.intelligence.temperature == pytest.approx(0.37)
