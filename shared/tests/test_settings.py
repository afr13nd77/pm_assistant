"""Tests for shared.settings module."""

import os
import pytest
import yaml

from shared import settings


@pytest.fixture(autouse=True)
def _reset_cache():
    """Reset settings cache before each test."""
    settings._settings_cache = None
    yield
    settings._settings_cache = None


class TestDefaults:
    def test_defaults_has_all_sections(self):
        assert "timeouts" in settings.DEFAULTS
        assert "cooldowns" in settings.DEFAULTS
        assert "cache_ttl" in settings.DEFAULTS
        assert "rate_limits" in settings.DEFAULTS
        assert "paths" in settings.DEFAULTS
        assert "ports" in settings.DEFAULTS

    def test_defaults_timeout_values(self):
        t = settings.DEFAULTS["timeouts"]
        assert t["enrich"] == 30
        assert t["synthesize"] == 120
        assert t["default"] == 60


class TestLoadSettings:
    def test_missing_file_returns_defaults(self):
        result = settings.load_settings("/nonexistent/path.yaml")
        assert result == settings.DEFAULTS

    def test_valid_yaml(self, tmp_path):
        cfg = tmp_path / "settings.yaml"
        cfg.write_text(yaml.dump({"timeouts": {"enrich": 45}}))
        result = settings.load_settings(str(cfg))
        assert result["timeouts"]["enrich"] == 45
        # Other defaults preserved
        assert result["timeouts"]["synthesize"] == 120

    def test_invalid_yaml(self, tmp_path):
        cfg = tmp_path / "settings.yaml"
        cfg.write_text(": invalid: yaml: {{{}}}][")
        result = settings.load_settings(str(cfg))
        assert result == settings.DEFAULTS

    def test_empty_yaml(self, tmp_path):
        cfg = tmp_path / "settings.yaml"
        cfg.write_text("")
        result = settings.load_settings(str(cfg))
        assert result == settings.DEFAULTS

    def test_partial_override(self, tmp_path):
        cfg = tmp_path / "settings.yaml"
        cfg.write_text(yaml.dump({"cooldowns": {"enrichment_reminder_hours": 48}}))
        result = settings.load_settings(str(cfg))
        assert result["cooldowns"]["enrichment_reminder_hours"] == 48
        assert result["cooldowns"]["health_history_days"] == 90

    def test_env_path(self, tmp_path, monkeypatch):
        cfg = tmp_path / "custom.yaml"
        cfg.write_text(yaml.dump({"ports": {"ke_api": 9999}}))
        monkeypatch.setenv("SETTINGS_PATH", str(cfg))
        result = settings.load_settings()
        assert result["ports"]["ke_api"] == 9999


class TestGet:
    def test_dot_notation(self, tmp_path):
        cfg = tmp_path / "settings.yaml"
        cfg.write_text(yaml.dump({"timeouts": {"enrich": 99}}))
        settings.load_settings(str(cfg))
        assert settings.get("timeouts.enrich") == 99

    def test_missing_key_returns_default(self):
        assert settings.get("nonexistent.key", 42) == 42

    def test_missing_key_returns_none(self):
        assert settings.get("nonexistent.key") is None

    def test_top_level_key(self):
        result = settings.get("timeouts")
        assert isinstance(result, dict)
        assert "enrich" in result


class TestGetSettings:
    def test_singleton(self):
        s1 = settings.get_settings()
        s2 = settings.get_settings()
        assert s1 is s2

    def test_returns_dict(self):
        result = settings.get_settings()
        assert isinstance(result, dict)
