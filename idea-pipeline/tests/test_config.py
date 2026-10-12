"""Тесты load_config и dataclass-ов конфигурации."""
import pytest
import yaml

from idea_pipeline.config import AgentConfig, PipelineConfig, load_config


def _write(tmp_path, data):
    p = tmp_path / "cfg.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return str(p)


def test_load_valid_config(tmp_path):
    path = _write(tmp_path, {
        "defaults": {"model": "m1", "max_tokens": 100, "timeout_seconds": 5},
        "agents": {
            "analyst": {"prompt_file": "a.md", "vault_context": {"max_entries": 3}},
            "pm": {"model": "m2", "max_tokens": 200},
            "decomposer": None,
        },
        "notification": {"enabled": True, "on_complete": True, "on_failure": False},
    })
    cfg = load_config(path)
    assert isinstance(cfg, PipelineConfig)
    assert set(cfg.agents) == {"analyst", "pm", "decomposer"}
    assert cfg.agents["analyst"].model == "m1"
    assert cfg.agents["analyst"].prompt_file == "a.md"
    assert cfg.agents["pm"].model == "m2"
    assert cfg.agents["pm"].max_tokens == 200
    assert cfg.agents["pm"].timeout_seconds == 5
    assert cfg.agents["decomposer"].max_tokens == 100
    assert cfg.notification_enabled is True
    assert cfg.notify_on_complete is True
    assert cfg.notify_on_failure is False
    assert cfg.vault_context_max_entries == 3


def test_load_defaults(tmp_path):
    cfg = load_config(_write(tmp_path, {"agents": {"analyst": {}}}))
    a = cfg.agents["analyst"]
    assert (a.model, a.max_tokens, a.timeout_seconds) == ("claude-sonnet-4-6", 4096, 120)
    assert cfg.notification_enabled is False
    assert cfg.vault_context_max_entries == 10


def test_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(str(tmp_path / "nope.yaml"))


def test_invalid_yaml(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("a: [unclosed", encoding="utf-8")
    with pytest.raises(yaml.YAMLError):
        load_config(str(p))


def test_empty_file(tmp_path):
    p = tmp_path / "empty.yaml"
    p.write_text("", encoding="utf-8")
    with pytest.raises(AttributeError):
        load_config(str(p))


def test_dataclasses():
    a = AgentConfig(name="x", model="m", max_tokens=1, timeout_seconds=2, prompt_file="p")
    c = PipelineConfig({"x": a}, True, False, True, 7)
    assert c.agents["x"] is a
    assert a.name == "x" and a.prompt_file == "p"
    assert c.vault_context_max_entries == 7
