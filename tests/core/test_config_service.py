"""Tests for :mod:`openjarvis.core.config_service`."""

from __future__ import annotations

from pathlib import Path

import pytest

from openjarvis.core.config import load_config
from openjarvis.core.config_service import (
    MASKED_PLACEHOLDER,
    ConfigService,
    PatchError,
    _coerce,
    _is_secret_key,
    build_schema,
)


@pytest.fixture
def cfg_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point OPENJARVIS_CONFIG at a fresh tmp file and clear load_config cache."""
    p = tmp_path / "config.toml"
    monkeypatch.setenv("OPENJARVIS_CONFIG", str(p))
    load_config.cache_clear()
    return p


@pytest.fixture
def service(cfg_path: Path) -> ConfigService:
    return ConfigService(path=cfg_path)


class TestSecretDetection:
    @pytest.mark.parametrize(
        "key,expected",
        [
            ("channel.telegram.bot_token", True),
            ("channel.sendblue.api_secret_key", True),
            ("channel.email.password", True),
            ("engine.ollama.host", False),
            ("intelligence.temperature", False),
            ("server.api_key", True),
            ("channel.slack.signing_secret", True),
        ],
    )
    def test_is_secret_key(self, key: str, expected: bool) -> None:
        assert _is_secret_key(key) is expected


class TestCoerce:
    def test_bool_from_string(self) -> None:
        assert _coerce("true", bool) is True
        assert _coerce("false", bool) is False
        assert _coerce("yes", bool) is True
        assert _coerce("", bool) is False

    def test_int_and_float(self) -> None:
        assert _coerce("42", int) == 42
        assert _coerce("3.14", float) == 3.14

    def test_str_from_list(self) -> None:
        assert _coerce(["a", "b"], str) == "a,b"

    def test_bool_is_not_int_passthrough(self) -> None:
        # Python quirk: isinstance(True, int) is True.  We must not return
        # True when the caller asked for an int.
        assert _coerce(True, int) == 1
        # And vice versa — bool target must not get a raw int passthrough.
        assert _coerce(1, bool) is True
        assert _coerce(0, bool) is False


class TestDumpMasking:
    def test_secret_masked_when_set(
        self, service: ConfigService, cfg_path: Path
    ) -> None:
        service.apply_patch({"channel.telegram.bot_token": "super-secret"})
        dump = service.dump(mask_secrets=True)
        assert dump["channel"]["telegram"]["bot_token"] == MASKED_PLACEHOLDER
        # Unmasked dump shows the real value
        raw = service.dump(mask_secrets=False)
        assert raw["channel"]["telegram"]["bot_token"] == "super-secret"

    def test_empty_secret_not_masked(self, service: ConfigService) -> None:
        dump = service.dump(mask_secrets=True)
        assert dump["channel"]["telegram"]["bot_token"] == ""


class TestApplyPatch:
    def test_persists_to_toml(self, service: ConfigService, cfg_path: Path) -> None:
        cfg, changed = service.apply_patch(
            {"intelligence.temperature": 0.25, "intelligence.max_tokens": 1024}
        )
        assert "intelligence.temperature" in changed
        assert cfg.intelligence.temperature == pytest.approx(0.25)
        assert cfg.intelligence.max_tokens == 1024
        # Persisted
        assert cfg_path.exists()
        text = cfg_path.read_text()
        assert "0.25" in text

    def test_preserves_comments(self, cfg_path: Path) -> None:
        cfg_path.write_text(
            "# keep me\n[intelligence]\ntemperature = 0.1\n"
        )
        load_config.cache_clear()
        svc = ConfigService(path=cfg_path)
        svc.apply_patch({"intelligence.temperature": 0.9})
        assert "# keep me" in cfg_path.read_text()

    def test_invalid_key_raises(self, service: ConfigService) -> None:
        with pytest.raises(PatchError) as exc:
            service.apply_patch({"bogus.key": 1})
        assert "bogus.key" in exc.value.errors

    def test_bad_type_raises(self, service: ConfigService) -> None:
        with pytest.raises(PatchError):
            service.apply_patch({"intelligence.temperature": "not-a-number"})

    def test_secret_sentinel_ignored(
        self, service: ConfigService, cfg_path: Path
    ) -> None:
        service.apply_patch({"channel.telegram.bot_token": "real-token"})
        # Frontend echoes the masked sentinel back — we must not overwrite.
        service.apply_patch({"channel.telegram.bot_token": MASKED_PLACEHOLDER})
        assert service.current().channel.telegram.bot_token == "real-token"

    def test_empty_patch_rejected(self, service: ConfigService) -> None:
        with pytest.raises(PatchError):
            service.apply_patch({})

    def test_changed_keys_only_when_different(self, service: ConfigService) -> None:
        t = service.current().intelligence.temperature
        _, changed = service.apply_patch({"intelligence.temperature": t})
        assert changed == []


class TestSchema:
    def test_contains_expected_sections(self, service: ConfigService) -> None:
        schema = service.schema()
        sections = schema["sections"]
        for name in (
            "engine",
            "intelligence",
            "tools",
            "agent",
            "server",
            "security",
            "channel",
            "telemetry",
            "traces",
        ):
            assert name in sections
            assert "properties" in sections[name]

    def test_secret_flag(self, service: ConfigService) -> None:
        schema = service.schema()
        telegram = schema["sections"]["channel"]["properties"]["telegram"]
        assert telegram["properties"]["bot_token"].get("secret") is True
        assert telegram["properties"].get("enabled", {}).get("secret", False) is False

    def test_restart_required_flag(self, service: ConfigService) -> None:
        schema = service.schema()
        engine_default = schema["sections"]["engine"]["properties"]["default"]
        assert engine_default.get("restart_required") is True


class TestReload:
    def test_reload_from_disk_picks_up_external_edits(
        self, cfg_path: Path
    ) -> None:
        svc = ConfigService(path=cfg_path)
        cfg_path.write_text("[intelligence]\ntemperature = 0.77\n")
        cfg = svc.reload_from_disk()
        assert cfg.intelligence.temperature == pytest.approx(0.77)


class TestDefaults:
    def test_defaults_does_not_touch_disk(
        self, cfg_path: Path, service: ConfigService
    ) -> None:
        assert not cfg_path.exists()
        defaults = service.defaults()
        assert "intelligence" in defaults
        assert defaults["intelligence"]["temperature"] is not None
        assert not cfg_path.exists()


class TestBuildSchemaDirect:
    def test_build_schema_from_defaults(self) -> None:
        from openjarvis.core.config import JarvisConfig

        schema = build_schema(JarvisConfig())
        assert "sections" in schema
        assert schema["sections"]["intelligence"]["title"] == "Intelligence"
