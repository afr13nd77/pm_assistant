import math
import os
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

import frontmatter as fm_lib
import pytest
import yaml

from app.decay_engine import (
    DecayConfig,
    _get_artifact_type,
    calc_relevance,
    calc_tier,
    get_creative,
    init_vault,
    load_config,
    recalc_vault,
    snapshot_vault,
    touch,
)
from shared.frontmatter_utils import read_frontmatter


def _create_md_file(path: Path, metadata: dict, body: str = "Content here"):
    path.parent.mkdir(parents=True, exist_ok=True)
    post = fm_lib.Post(body, **metadata)
    path.write_text(fm_lib.dumps(post), encoding="utf-8")


def _build_vault(tmp_path: Path, files: dict[str, dict]):
    for rel_path, meta in files.items():
        full = tmp_path / rel_path
        _create_md_file(full, meta)


FIXED_TODAY = date(2026, 6, 14)


class _FakeDate(date):
    @classmethod
    def today(cls):
        return FIXED_TODAY


class TestCalcRelevance:
    def test_calc_relevance_basic(self):
        result = calc_relevance(days_since_access=0, access_count=0, rate=0.02)
        assert result == 1.0

    def test_calc_relevance_day10(self):
        result = calc_relevance(days_since_access=10, access_count=0, rate=0.02)
        assert result == pytest.approx(0.8, abs=1e-6)

    def test_calc_relevance_floor(self):
        result = calc_relevance(days_since_access=100, access_count=0, rate=0.02)
        assert result == 0.05

    def test_calc_relevance_high_access(self):
        strength = 1 + math.log(10)
        effective_rate = 0.02 / strength
        expected = 1.0 - effective_rate * 10
        result = calc_relevance(days_since_access=10, access_count=10, rate=0.02)
        assert result == pytest.approx(expected, abs=1e-4)
        assert result > 0.9

    def test_calc_relevance_negative_days(self):
        result = calc_relevance(days_since_access=0, access_count=5, rate=0.05)
        assert result == 1.0


class TestCalcTier:
    def test_calc_tier_active(self):
        thresholds = {"active": 7, "warm": 21, "cold": 60}
        assert calc_tier(3, thresholds) == "active"

    def test_calc_tier_warm(self):
        thresholds = {"active": 7, "warm": 21, "cold": 60}
        assert calc_tier(15, thresholds) == "warm"

    def test_calc_tier_cold(self):
        thresholds = {"active": 7, "warm": 21, "cold": 60}
        assert calc_tier(30, thresholds) == "cold"

    def test_calc_tier_archive(self):
        thresholds = {"active": 7, "warm": 21, "cold": 60}
        assert calc_tier(90, thresholds) == "archive"

    def test_calc_tier_boundary(self):
        thresholds = {"active": 7, "warm": 21, "cold": 60}
        assert calc_tier(7, thresholds) == "active"
        assert calc_tier(8, thresholds) == "warm"


class TestGetArtifactType:
    def test_type_from_frontmatter(self):
        result = _get_artifact_type("/vault/wiki/domains/d/ideas/IDEA-001.md", {"type": "prd"})
        assert result == "prd"

    def test_type_from_path(self):
        result = _get_artifact_type("/vault/wiki/domains/d/ideas/IDEA-001.md", {})
        assert result == "idea"

    def test_type_fallback(self):
        result = _get_artifact_type("/vault/unknown/file.md", {})
        assert result == "idea"


class TestLoadConfig:
    def test_load_config_from_file(self, tmp_path):
        config_data = {
            "floor": 0.10,
            "tier_thresholds": {"active": 5, "warm": 14, "cold": 45},
            "default_rate": 0.030,
            "rates": {"idea": 0.015, "task": 0.030},
        }
        config_file = tmp_path / "decay.yaml"
        config_file.write_text(yaml.dump(config_data), encoding="utf-8")

        cfg = load_config(str(config_file))
        assert cfg.floor == 0.10
        assert cfg.tier_thresholds["active"] == 5
        assert cfg.tier_thresholds["warm"] == 14
        assert cfg.tier_thresholds["cold"] == 45
        assert cfg.default_rate == 0.030
        assert cfg.rates["idea"] == 0.015
        assert cfg.rates["task"] == 0.030

    def test_load_config_defaults(self, tmp_path):
        cfg = load_config(str(tmp_path / "nonexistent.yaml"))
        defaults = DecayConfig()
        assert cfg.floor == defaults.floor
        assert cfg.tier_thresholds == defaults.tier_thresholds
        assert cfg.default_rate == defaults.default_rate
        assert cfg.rates == defaults.rates


class TestRecalcVault:
    def _patch_today(self):
        return patch("app.decay_engine.date", _FakeDate)

    def test_recalc_vault_basic(self, tmp_path):
        created = "2026-06-01"
        days = (FIXED_TODAY - date(2026, 6, 1)).days
        _build_vault(tmp_path, {
            "wiki/domains/test-domain/ideas/IDEA-0001.md": {
                "title": "Test Idea",
                "created": created,
                "type": "idea",
                "status": "Inbox",
            },
        })

        config = DecayConfig()
        with self._patch_today():
            result = recalc_vault(str(tmp_path), config=config)

        assert result["processed"] >= 1
        assert result["errors"] == []

        meta, _ = read_frontmatter(tmp_path / "wiki/domains/test-domain/ideas/IDEA-0001.md")
        assert "relevance" in meta
        assert "tier" in meta

        expected_relevance = round(calc_relevance(days, 0, config.rates["idea"], config.floor), 2)
        assert meta["relevance"] == expected_relevance

    def test_recalc_skips_core(self, tmp_path):
        _build_vault(tmp_path, {
            "wiki/domains/test-domain/ideas/IDEA-0001.md": {
                "title": "Normal Idea",
                "created": "2026-06-01",
                "type": "idea",
                "status": "Inbox",
            },
            "wiki/domains/test-domain/ideas/IDEA-0002.md": {
                "title": "Core Idea",
                "created": "2026-06-01",
                "type": "idea",
                "status": "Inbox",
                "tier": "core",
            },
        })

        config = DecayConfig()
        with self._patch_today():
            result = recalc_vault(str(tmp_path), config=config)

        assert result["processed"] >= 1
        assert result["skipped"] >= 1

        meta_core, _ = read_frontmatter(tmp_path / "wiki/domains/test-domain/ideas/IDEA-0002.md")
        assert meta_core["tier"] == "core"

    def test_recalc_skips_index(self, tmp_path):
        _build_vault(tmp_path, {
            "wiki/domains/test-domain/ideas/IDEA-0001.md": {
                "title": "Normal Idea",
                "created": "2026-06-01",
                "type": "idea",
                "status": "Inbox",
            },
        })
        index_file = tmp_path / "wiki" / "domains" / "test-domain" / "ideas" / "INDEX.md"
        _create_md_file(index_file, {"title": "Index", "created": "2026-06-01"})

        config = DecayConfig()
        with self._patch_today():
            result = recalc_vault(str(tmp_path), config=config)

        assert result["processed"] == 1


class TestInitVault:
    def _patch_today(self):
        return patch("app.decay_engine.date", _FakeDate)

    def test_init_vault_adds_fields(self, tmp_path):
        _build_vault(tmp_path, {
            "wiki/domains/test-domain/tasks/TASK-0001.md": {
                "title": "Test Task",
                "created": "2026-06-10",
                "type": "task",
                "status": "Inbox",
            },
        })

        config = DecayConfig()
        with self._patch_today():
            result = init_vault(str(tmp_path), config=config)

        assert result["migrated"] == 1
        assert result["skipped"] == 0

        meta, _ = read_frontmatter(tmp_path / "wiki/domains/test-domain/tasks/TASK-0001.md")
        assert "relevance" in meta
        assert "tier" in meta
        assert "last_accessed" in meta
        assert "access_count" in meta

    def test_init_vault_skips_existing(self, tmp_path):
        _build_vault(tmp_path, {
            "wiki/domains/test-domain/ideas/IDEA-0001.md": {
                "title": "Already Has Relevance",
                "created": "2026-06-01",
                "type": "idea",
                "status": "Inbox",
                "relevance": 0.8,
                "tier": "active",
            },
        })

        config = DecayConfig()
        with self._patch_today():
            result = init_vault(str(tmp_path), config=config)

        assert result["migrated"] == 0
        assert result["skipped"] >= 1

    def test_init_vault_adr(self, tmp_path):
        _build_vault(tmp_path, {
            "wiki/domains/test-domain/knowledge/ADR-001.md": {
                "title": "Architecture Decision",
                "created": "2026-01-15",
                "type": "adr",
                "status": "accepted",
            },
        })

        config = DecayConfig()
        with self._patch_today():
            result = init_vault(str(tmp_path), config=config)

        assert result["migrated"] == 1

        meta, _ = read_frontmatter(tmp_path / "wiki/domains/test-domain/knowledge/ADR-001.md")
        assert meta["tier"] == "core"
        assert meta["relevance"] == 1.0


class TestTouch:
    def _patch_today(self):
        return patch("app.decay_engine.date", _FakeDate)

    def test_touch_increments_access_count(self, tmp_path):
        _build_vault(tmp_path, {
            "wiki/domains/test-domain/ideas/IDEA-0001.md": {
                "title": "Touch Test",
                "created": "2026-06-01",
                "type": "idea",
                "access_count": 2,
                "tier": "warm",
                "relevance": 0.5,
                "last_accessed": "2026-06-01",
            },
        })

        config = DecayConfig()
        filepath = tmp_path / "wiki/domains/test-domain/ideas/IDEA-0001.md"
        with self._patch_today():
            touch(str(filepath), str(tmp_path), config=config)

        meta, _ = read_frontmatter(filepath)
        assert meta["access_count"] == 3

    def test_touch_updates_last_accessed(self, tmp_path):
        _build_vault(tmp_path, {
            "wiki/domains/test-domain/ideas/IDEA-0001.md": {
                "title": "Touch Date Test",
                "created": "2026-01-01",
                "type": "idea",
                "access_count": 1,
                "tier": "cold",
                "relevance": 0.3,
                "last_accessed": "2026-01-01",
            },
        })

        config = DecayConfig()
        filepath = tmp_path / "wiki/domains/test-domain/ideas/IDEA-0001.md"
        with self._patch_today():
            touch(str(filepath), str(tmp_path), config=config)

        meta, _ = read_frontmatter(filepath)
        assert meta["last_accessed"] == str(FIXED_TODAY)

    def test_touch_promotes_tier(self, tmp_path):
        _build_vault(tmp_path, {
            "wiki/domains/test-domain/ideas/IDEA-0001.md": {
                "title": "Tier Promotion Test",
                "created": "2026-01-01",
                "type": "idea",
                "access_count": 0,
                "tier": "cold",
                "relevance": 0.3,
                "last_accessed": "2026-01-01",
            },
        })

        config = DecayConfig()
        filepath = tmp_path / "wiki/domains/test-domain/ideas/IDEA-0001.md"
        with self._patch_today():
            result = touch(str(filepath), str(tmp_path), config=config)

        assert result["old_tier"] == "cold"
        assert result["new_tier"] == "active"

    def test_touch_adds_defaults(self, tmp_path):
        _build_vault(tmp_path, {
            "wiki/domains/test-domain/ideas/IDEA-0001.md": {
                "title": "No Decay Fields",
                "created": "2026-06-10",
                "type": "idea",
            },
        })

        config = DecayConfig()
        filepath = tmp_path / "wiki/domains/test-domain/ideas/IDEA-0001.md"
        with self._patch_today():
            touch(str(filepath), str(tmp_path), config=config)

        meta, _ = read_frontmatter(filepath)
        assert "relevance" in meta
        assert "tier" in meta
        assert "last_accessed" in meta
        assert "access_count" in meta

    def test_touch_spacing_effect(self, tmp_path):
        _build_vault(tmp_path, {
            "wiki/domains/test-domain/ideas/IDEA-0001.md": {
                "title": "Spacing Effect Test",
                "created": "2026-06-01",
                "type": "idea",
                "access_count": 9,
                "tier": "warm",
                "relevance": 0.5,
                "last_accessed": "2026-06-01",
            },
        })

        config = DecayConfig()
        filepath = tmp_path / "wiki/domains/test-domain/ideas/IDEA-0001.md"
        with self._patch_today():
            touch(str(filepath), str(tmp_path), config=config)

        meta, _ = read_frontmatter(filepath)
        assert meta["access_count"] == 10
        assert meta["relevance"] == 1.0


class TestGetCreative:
    def test_creative_returns_cold_archive(self, tmp_path):
        _build_vault(tmp_path, {
            "wiki/domains/test-domain/ideas/IDEA-0001.md": {
                "title": "Active Idea",
                "created": "2026-06-14",
                "type": "idea",
                "status": "Inbox",
                "tier": "active",
                "relevance": 1.0,
            },
            "wiki/domains/test-domain/ideas/IDEA-0002.md": {
                "title": "Cold Idea",
                "created": "2026-05-01",
                "type": "idea",
                "status": "Inbox",
                "tier": "cold",
                "relevance": 0.4,
            },
            "wiki/domains/test-domain/ideas/IDEA-0003.md": {
                "title": "Archive Idea",
                "created": "2026-03-01",
                "type": "idea",
                "status": "Inbox",
                "tier": "archive",
                "relevance": 0.1,
            },
        })

        result = get_creative(str(tmp_path))
        titles = {item["title"] for item in result}
        assert "Active Idea" not in titles
        assert "Cold Idea" in titles
        assert "Archive Idea" in titles
        assert len(result) == 2

    def test_creative_excludes_otsev(self, tmp_path):
        _build_vault(tmp_path, {
            "wiki/domains/test-domain/ideas/IDEA-0001.md": {
                "title": "Rejected Idea",
                "created": "2026-03-01",
                "type": "idea",
                "status": "Отсев",
                "tier": "archive",
                "relevance": 0.1,
            },
            "wiki/domains/test-domain/ideas/IDEA-0002.md": {
                "title": "Inbox Idea",
                "created": "2026-03-01",
                "type": "idea",
                "status": "Inbox",
                "tier": "archive",
                "relevance": 0.1,
            },
        })

        result = get_creative(str(tmp_path))
        titles = {item["title"] for item in result}
        assert "Rejected Idea" not in titles
        assert "Inbox Idea" in titles
        assert len(result) == 1

    def test_creative_empty_when_all_active(self, tmp_path):
        _build_vault(tmp_path, {
            "wiki/domains/test-domain/ideas/IDEA-0001.md": {
                "title": "Active One",
                "created": "2026-06-14",
                "type": "idea",
                "status": "Inbox",
                "tier": "active",
                "relevance": 1.0,
            },
            "wiki/domains/test-domain/ideas/IDEA-0002.md": {
                "title": "Active Two",
                "created": "2026-06-13",
                "type": "idea",
                "status": "Inbox",
                "tier": "active",
                "relevance": 0.98,
            },
        })

        result = get_creative(str(tmp_path))
        assert result == []

    def test_creative_max_count(self, tmp_path):
        files = {}
        for i in range(1, 11):
            files[f"wiki/domains/test-domain/ideas/IDEA-{i:04d}.md"] = {
                "title": f"Archive Idea {i}",
                "created": "2026-01-01",
                "type": "idea",
                "status": "Inbox",
                "tier": "archive",
                "relevance": 0.1,
            }
        _build_vault(tmp_path, files)

        result = get_creative(str(tmp_path), count=3)
        assert len(result) == 3


class TestSnapshotVault:
    def _patch_today(self):
        return patch("app.decay_engine.date", _FakeDate)

    def test_snapshot_vault_empty(self, tmp_path):
        result = snapshot_vault(str(tmp_path), config=DecayConfig())
        assert result["total"] == 0
        assert result["items"] == []

    def test_snapshot_vault_basic(self, tmp_path):
        _build_vault(tmp_path, {
            "wiki/domains/search-engine/ideas/IDEA-001.md": {
                "title": "Test Idea",
                "tier": "active",
                "relevance": 0.9,
                "last_accessed": str(FIXED_TODAY),
                "access_count": 5,
            },
            "wiki/domains/general/tasks/TASK-001.md": {
                "title": "Test Task",
                "tier": "warm",
                "relevance": 0.7,
                "last_accessed": str(FIXED_TODAY),
                "access_count": 3,
            },
        })

        with self._patch_today():
            result = snapshot_vault(str(tmp_path), config=DecayConfig())

        assert result["total"] == 2
        assert len(result["items"]) == 2

        expected_fields = {
            "filepath", "title", "domain", "type", "tier",
            "relevance", "days_since_access", "access_count",
        }
        for item in result["items"]:
            assert set(item.keys()) == expected_fields

    def test_snapshot_vault_core_included(self, tmp_path):
        _build_vault(tmp_path, {
            "wiki/domains/search-engine/ideas/IDEA-001.md": {
                "title": "Core Idea",
                "tier": "core",
                "last_accessed": str(FIXED_TODAY),
                "access_count": 2,
            },
        })

        with self._patch_today():
            result = snapshot_vault(str(tmp_path), config=DecayConfig())

        assert result["total"] == 1
        assert result["items"][0]["tier"] == "core"
        assert result["items"][0]["relevance"] == 1.0

    def test_snapshot_vault_no_frontmatter_skipped(self, tmp_path):
        plain_dir = tmp_path / "wiki" / "domains" / "test" / "ideas"
        plain_dir.mkdir(parents=True, exist_ok=True)
        (plain_dir / "IDEA-001.md").write_text("just plain text", encoding="utf-8")

        result = snapshot_vault(str(tmp_path), config=DecayConfig())
        assert result["total"] == 0
        assert result["items"] == []

    def test_snapshot_vault_tier_thresholds(self, tmp_path):
        result = snapshot_vault(str(tmp_path), config=DecayConfig())
        assert "tier_thresholds" in result
        assert "active" in result["tier_thresholds"]
        assert "warm" in result["tier_thresholds"]
        assert "cold" in result["tier_thresholds"]

    def test_snapshot_vault_domain_extraction(self, tmp_path):
        _build_vault(tmp_path, {
            "wiki/domains/search-engine/ideas/IDEA-001.md": {
                "title": "SE Idea",
                "last_accessed": str(FIXED_TODAY),
                "access_count": 1,
            },
            "wiki/meetings/MEETING-001.md": {
                "title": "Meeting",
                "last_accessed": str(FIXED_TODAY),
                "access_count": 1,
            },
        })

        with self._patch_today():
            result = snapshot_vault(str(tmp_path), config=DecayConfig())

        items_by_path = {item["filepath"]: item for item in result["items"]}

        se_item = items_by_path.get("wiki/domains/search-engine/ideas/IDEA-001.md")
        assert se_item is not None
        assert se_item["domain"] == "search-engine"

        meeting_item = items_by_path.get("wiki/meetings/MEETING-001.md")
        assert meeting_item is not None
        assert meeting_item["domain"] == ""
