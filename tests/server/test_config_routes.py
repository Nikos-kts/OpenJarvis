"""Integration tests for /v1/config/* endpoints."""

from __future__ import annotations

from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from openjarvis.core.config import load_config  # noqa: E402
from openjarvis.core.config_service import (  # noqa: E402
    MASKED_PLACEHOLDER,
    ConfigService,
)
from openjarvis.server.config_routes import router as config_router  # noqa: E402


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    cfg_path = tmp_path / "config.toml"
    monkeypatch.setenv("OPENJARVIS_CONFIG", str(cfg_path))
    load_config.cache_clear()

    app = FastAPI()
    app.include_router(config_router)
    app.state.config_service = ConfigService(path=cfg_path)
    return TestClient(app)


class TestGetEndpoints:
    def test_get_config(self, client: TestClient) -> None:
        resp = client.get("/v1/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "intelligence" in data
        assert "engine" in data

    def test_get_defaults(self, client: TestClient) -> None:
        resp = client.get("/v1/config/defaults")
        assert resp.status_code == 200
        assert "engine" in resp.json()

    def test_get_schema(self, client: TestClient) -> None:
        resp = client.get("/v1/config/schema")
        assert resp.status_code == 200
        data = resp.json()
        assert "sections" in data
        assert "intelligence" in data["sections"]

    def test_get_hardware(self, client: TestClient) -> None:
        resp = client.get("/v1/config/hardware")
        assert resp.status_code == 200
        assert "platform" in resp.json()


class TestPatchEndpoint:
    def test_patch_valid(self, client: TestClient) -> None:
        resp = client.patch(
            "/v1/config",
            json={"patch": {"intelligence.temperature": 0.42}},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "intelligence.temperature" in body["changed_keys"]
        assert body["config"]["intelligence"]["temperature"] == pytest.approx(0.42)

    def test_patch_invalid_key(self, client: TestClient) -> None:
        resp = client.patch("/v1/config", json={"patch": {"bogus.key": 1}})
        assert resp.status_code == 422
        assert "bogus.key" in resp.json()["detail"]["errors"]

    def test_patch_secret_round_trip(self, client: TestClient) -> None:
        # Set a secret
        r1 = client.patch(
            "/v1/config",
            json={"patch": {"channel.telegram.bot_token": "real"}},
        )
        assert r1.status_code == 200
        assert (
            r1.json()["config"]["channel"]["telegram"]["bot_token"]
            == MASKED_PLACEHOLDER
        )
        # Echo the sentinel back — must not overwrite
        r2 = client.patch(
            "/v1/config",
            json={"patch": {"channel.telegram.bot_token": MASKED_PLACEHOLDER}},
        )
        assert r2.status_code == 200
        # Read raw
        svc = client.app.state.config_service
        assert svc.current().channel.telegram.bot_token == "real"

    def test_patch_empty(self, client: TestClient) -> None:
        resp = client.patch("/v1/config", json={"patch": {}})
        assert resp.status_code == 422

    def test_patch_missing_reloader_flags_restart(
        self, client: TestClient
    ) -> None:
        resp = client.patch(
            "/v1/config",
            json={"patch": {"intelligence.temperature": 0.11}},
        )
        body = resp.json()
        # No reloader is registered → restart_required is true.
        assert body["restart_required"] is True


class TestReload:
    def test_reload_picks_up_external_edits(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        cfg_path = client.app.state.config_service.path
        cfg_path.write_text("[intelligence]\ntemperature = 0.33\n")
        resp = client.post("/v1/config/reload")
        assert resp.status_code == 200
        body = resp.json()
        # Reload now returns the full PatchResponse shape so the UI can
        # surface restart-required reasons for out-of-band edits.
        assert body["config"]["intelligence"]["temperature"] == pytest.approx(0.33)
        assert "intelligence.temperature" in body["changed_keys"]

    def test_reload_flags_restart_when_engine_changes(
        self, client: TestClient
    ) -> None:
        """Out-of-band edits to engine.* must still surface a restart banner."""
        cfg_path = client.app.state.config_service.path
        cfg_path.write_text('[engine]\ndefault = "vllm"\n')
        resp = client.post("/v1/config/reload")
        assert resp.status_code == 200
        body = resp.json()
        assert body["config"]["engine"]["default"] == "vllm"
        assert "engine.default" in body["changed_keys"]
        # No reloader is wired in this fixture → restart_required is true.
        assert body["restart_required"] is True

    def test_reload_no_changes_reports_empty_diff(
        self, client: TestClient
    ) -> None:
        resp = client.post("/v1/config/reload")
        assert resp.status_code == 200
        body = resp.json()
        assert body["changed_keys"] == []
        assert body["restart_required"] is False
