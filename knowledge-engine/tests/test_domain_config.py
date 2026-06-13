"""Tests for domain_config module."""

import importlib
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reload_modules(tmp_path: Path):
    """Reload vault_paths and domain_config so VAULT_PATH points to tmp_path."""
    with patch.dict(os.environ, {"VAULT_PATH": str(tmp_path)}):
        # Force module cache reset for vault_paths
        if "shared.vault_paths" in sys.modules:
            importlib.reload(sys.modules["shared.vault_paths"])
        else:
            import shared.vault_paths  # noqa: F401

    if "shared.domain_config" in sys.modules:
        mod = sys.modules["shared.domain_config"]
        importlib.reload(mod)
        # Reset module-level cache after reload
        mod._cache = None
        mod._cache_mtime = 0.0
    else:
        import shared.domain_config  # noqa: F401

    from shared import domain_config as dc
    dc._cache = None
    dc._cache_mtime = 0.0
    return dc


def _import_dc(tmp_path: Path):
    """Return a freshly-reloaded domain_config module bound to tmp_path."""
    return _reload_modules(tmp_path)


# ---------------------------------------------------------------------------
# config_path
# ---------------------------------------------------------------------------


class TestConfigPath:
    def test_returns_path_inside_vault(self, tmp_path):
        dc = _import_dc(tmp_path)
        path = dc.config_path()
        assert isinstance(path, Path)
        assert path.name == "domain-config.yaml"
        assert str(tmp_path) in str(path)


# ---------------------------------------------------------------------------
# load
# ---------------------------------------------------------------------------


class TestLoad:
    def test_load_missing_file_returns_empty(self, tmp_path):
        dc = _import_dc(tmp_path)
        result = dc.load()
        assert result == {"domains": {}}

    def test_load_valid_file(self, tmp_path):
        dc = _import_dc(tmp_path)
        config = {
            "domains": {
                "search": {
                    "display_name": "Search",
                    "description": "",
                    "color": "#607D8B",
                    "jira_labels": ["search"],
                }
            }
        }
        dc.config_path().write_text(
            yaml.dump(config, allow_unicode=True), encoding="utf-8"
        )
        result = dc.load()
        assert "search" in result["domains"]

    def test_load_invalid_yaml_returns_empty(self, tmp_path):
        dc = _import_dc(tmp_path)
        dc.config_path().parent.mkdir(parents=True, exist_ok=True)
        # Indentation error forces a YAML scanner/parser exception
        dc.config_path().write_text(
            "domains:\n  alpha:\n   bad_indent:\n  - broken\n",
            encoding="utf-8",
        )
        result = dc.load()
        assert result == {"domains": {}}

    def test_load_non_dict_yaml_returns_empty(self, tmp_path):
        dc = _import_dc(tmp_path)
        dc.config_path().parent.mkdir(parents=True, exist_ok=True)
        dc.config_path().write_text("- item1\n- item2\n", encoding="utf-8")
        result = dc.load()
        assert result == {"domains": {}}

    def test_load_missing_domains_key_adds_it(self, tmp_path):
        dc = _import_dc(tmp_path)
        dc.config_path().parent.mkdir(parents=True, exist_ok=True)
        dc.config_path().write_text("some_key: some_value\n", encoding="utf-8")
        result = dc.load()
        assert "domains" in result
        assert isinstance(result["domains"], dict)

    def test_load_cache_hit_returns_same_object(self, tmp_path):
        dc = _import_dc(tmp_path)
        config = {"domains": {"alpha": {"display_name": "Alpha", "description": "", "color": "#607D8B", "jira_labels": []}}}
        dc.config_path().parent.mkdir(parents=True, exist_ok=True)
        dc.config_path().write_text(yaml.dump(config), encoding="utf-8")

        first = dc.load()
        second = dc.load()
        assert first is second  # same object from cache

    def test_load_cache_invalidated_on_file_change(self, tmp_path):
        dc = _import_dc(tmp_path)
        config1 = {"domains": {"alpha": {"display_name": "Alpha", "description": "", "color": "#607D8B", "jira_labels": []}}}
        config2 = {"domains": {"beta": {"display_name": "Beta", "description": "", "color": "#607D8B", "jira_labels": []}}}

        path = dc.config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.dump(config1), encoding="utf-8")
        dc.load()  # prime cache

        # Overwrite file and bump mtime by manipulating cache directly
        path.write_text(yaml.dump(config2), encoding="utf-8")
        dc._cache_mtime = 0.0  # force cache miss

        result = dc.load()
        assert "beta" in result["domains"]


# ---------------------------------------------------------------------------
# validate_domain_entry
# ---------------------------------------------------------------------------


class TestValidateDomainEntry:
    def test_valid_minimal_entry(self, tmp_path):
        dc = _import_dc(tmp_path)
        errors = dc.validate_domain_entry("my-domain", {"display_name": "My Domain"})
        assert errors == []

    def test_valid_full_entry(self, tmp_path):
        dc = _import_dc(tmp_path)
        entry = {
            "display_name": "My Domain",
            "description": "A test domain",
            "color": "#A1B2C3",
            "jira_labels": ["label-one", "label-two"],
        }
        errors = dc.validate_domain_entry("my-domain", entry)
        assert errors == []

    def test_invalid_slug_uppercase(self, tmp_path):
        dc = _import_dc(tmp_path)
        errors = dc.validate_domain_entry("MyDomain", {"display_name": "X"})
        assert any("slug" in e for e in errors)

    def test_invalid_slug_underscore(self, tmp_path):
        dc = _import_dc(tmp_path)
        errors = dc.validate_domain_entry("my_domain", {"display_name": "X"})
        assert any("slug" in e for e in errors)

    def test_invalid_slug_empty(self, tmp_path):
        dc = _import_dc(tmp_path)
        errors = dc.validate_domain_entry("", {"display_name": "X"})
        assert any("slug" in e for e in errors)

    def test_missing_display_name(self, tmp_path):
        dc = _import_dc(tmp_path)
        errors = dc.validate_domain_entry("ok-slug", {})
        assert any("display_name" in e for e in errors)

    def test_empty_display_name(self, tmp_path):
        dc = _import_dc(tmp_path)
        errors = dc.validate_domain_entry("ok-slug", {"display_name": ""})
        assert any("display_name" in e for e in errors)

    def test_display_name_too_long(self, tmp_path):
        dc = _import_dc(tmp_path)
        errors = dc.validate_domain_entry("ok-slug", {"display_name": "x" * 101})
        assert any("display_name" in e for e in errors)

    def test_display_name_max_length_ok(self, tmp_path):
        dc = _import_dc(tmp_path)
        errors = dc.validate_domain_entry("ok-slug", {"display_name": "x" * 100})
        assert errors == []

    def test_description_too_long(self, tmp_path):
        dc = _import_dc(tmp_path)
        errors = dc.validate_domain_entry(
            "ok-slug",
            {"display_name": "X", "description": "y" * 501},
        )
        assert any("description" in e for e in errors)

    def test_description_max_length_ok(self, tmp_path):
        dc = _import_dc(tmp_path)
        errors = dc.validate_domain_entry(
            "ok-slug",
            {"display_name": "X", "description": "y" * 500},
        )
        assert errors == []

    def test_invalid_color_no_hash(self, tmp_path):
        dc = _import_dc(tmp_path)
        errors = dc.validate_domain_entry(
            "ok-slug", {"display_name": "X", "color": "AABBCC"}
        )
        assert any("color" in e for e in errors)

    def test_invalid_color_too_short(self, tmp_path):
        dc = _import_dc(tmp_path)
        errors = dc.validate_domain_entry(
            "ok-slug", {"display_name": "X", "color": "#AAB"}
        )
        assert any("color" in e for e in errors)

    def test_valid_color_uppercase(self, tmp_path):
        dc = _import_dc(tmp_path)
        errors = dc.validate_domain_entry(
            "ok-slug", {"display_name": "X", "color": "#AABBCC"}
        )
        assert errors == []

    def test_valid_color_lowercase(self, tmp_path):
        dc = _import_dc(tmp_path)
        errors = dc.validate_domain_entry(
            "ok-slug", {"display_name": "X", "color": "#aabbcc"}
        )
        assert errors == []

    def test_jira_labels_not_a_list(self, tmp_path):
        dc = _import_dc(tmp_path)
        errors = dc.validate_domain_entry(
            "ok-slug", {"display_name": "X", "jira_labels": "label"}
        )
        assert any("jira_labels" in e for e in errors)

    def test_jira_labels_contains_empty_string(self, tmp_path):
        dc = _import_dc(tmp_path)
        errors = dc.validate_domain_entry(
            "ok-slug", {"display_name": "X", "jira_labels": ["ok", ""]}
        )
        assert any("jira_labels" in e for e in errors)

    def test_entry_not_a_dict(self, tmp_path):
        dc = _import_dc(tmp_path)
        errors = dc.validate_domain_entry("ok-slug", "not-a-dict")
        assert any("dict" in e for e in errors)


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


class TestValidate:
    def test_empty_domains_is_valid(self, tmp_path):
        dc = _import_dc(tmp_path)
        assert dc.validate({"domains": {}}) == []

    def test_valid_single_domain(self, tmp_path):
        dc = _import_dc(tmp_path)
        config = {
            "domains": {
                "alpha": {
                    "display_name": "Alpha",
                    "description": "",
                    "color": "#607D8B",
                    "jira_labels": ["alpha-label"],
                }
            }
        }
        assert dc.validate(config) == []

    def test_duplicate_labels_across_domains(self, tmp_path):
        dc = _import_dc(tmp_path)
        config = {
            "domains": {
                "alpha": {"display_name": "Alpha", "jira_labels": ["shared-label"]},
                "beta": {"display_name": "Beta", "jira_labels": ["Shared-Label"]},
            }
        }
        errors = dc.validate(config)
        assert any("shared-label" in e.lower() or "Shared-Label" in e for e in errors)

    def test_duplicate_labels_same_domain_is_ok(self, tmp_path):
        dc = _import_dc(tmp_path)
        config = {
            "domains": {
                "alpha": {"display_name": "Alpha", "jira_labels": ["lbl", "lbl"]},
            }
        }
        # Duplicate within same domain is not a cross-domain conflict
        errors = dc.validate(config)
        assert not any("lbl" in e for e in errors)

    def test_not_a_dict_returns_error(self, tmp_path):
        dc = _import_dc(tmp_path)
        errors = dc.validate("not-a-dict")
        assert errors

    def test_missing_domains_key(self, tmp_path):
        dc = _import_dc(tmp_path)
        errors = dc.validate({})
        assert any("domains" in e for e in errors)

    def test_too_many_domains(self, tmp_path):
        dc = _import_dc(tmp_path)
        domains = {
            f"domain-{i:03d}": {"display_name": f"Domain {i}"}
            for i in range(101)
        }
        errors = dc.validate({"domains": domains})
        assert any("too many" in e for e in errors)

    def test_100_domains_is_ok(self, tmp_path):
        dc = _import_dc(tmp_path)
        domains = {
            f"domain-{i:03d}": {"display_name": f"Domain {i}", "jira_labels": [f"lbl-{i}"]}
            for i in range(100)
        }
        errors = dc.validate({"domains": domains})
        # No "too many" error (though individual entries may have color defaults missing — that is fine)
        assert not any("too many" in e for e in errors)


# ---------------------------------------------------------------------------
# save
# ---------------------------------------------------------------------------


class TestSave:
    def test_save_creates_file(self, tmp_path):
        dc = _import_dc(tmp_path)
        config = {"domains": {}}
        dc.save(config)
        assert dc.config_path().exists()

    def test_save_writes_header(self, tmp_path):
        dc = _import_dc(tmp_path)
        dc.save({"domains": {}})
        content = dc.config_path().read_text(encoding="utf-8")
        assert "# Domain Configuration" in content

    def test_save_roundtrip(self, tmp_path):
        dc = _import_dc(tmp_path)
        config = {
            "domains": {
                "search": {
                    "display_name": "Search",
                    "description": "Search domain",
                    "color": "#607D8B",
                    "jira_labels": ["search"],
                }
            }
        }
        dc.save(config)
        loaded = dc.load()
        assert loaded["domains"]["search"]["display_name"] == "Search"

    def test_save_updates_cache(self, tmp_path):
        dc = _import_dc(tmp_path)
        config = {"domains": {}}
        dc.save(config)
        assert dc._cache is config

    def test_save_invalid_config_raises_value_error(self, tmp_path):
        dc = _import_dc(tmp_path)
        bad_config = {"domains": {"BAD-SLUG": {"display_name": "X"}}}
        with pytest.raises(ValueError):
            dc.save(bad_config)

    def test_save_uses_atomic_write(self, tmp_path):
        """No .tmp file left behind after a successful save."""
        dc = _import_dc(tmp_path)
        dc.save({"domains": {}})
        tmp_file = dc.config_path().with_suffix(".tmp")
        assert not tmp_file.exists()


# ---------------------------------------------------------------------------
# get_domain
# ---------------------------------------------------------------------------


class TestGetDomain:
    def test_get_existing_domain(self, tmp_path):
        dc = _import_dc(tmp_path)
        config = {
            "domains": {
                "search": {
                    "display_name": "Search",
                    "description": "",
                    "color": "#607D8B",
                    "jira_labels": [],
                }
            }
        }
        dc.save(config)
        result = dc.get_domain("search")
        assert result is not None
        assert result["display_name"] == "Search"

    def test_get_missing_domain_returns_none(self, tmp_path):
        dc = _import_dc(tmp_path)
        dc.save({"domains": {}})
        assert dc.get_domain("nonexistent") is None

    def test_get_domain_no_file_returns_none(self, tmp_path):
        dc = _import_dc(tmp_path)
        assert dc.get_domain("anything") is None


# ---------------------------------------------------------------------------
# set_domain
# ---------------------------------------------------------------------------


class TestSetDomain:
    def test_set_domain_creates_entry(self, tmp_path):
        dc = _import_dc(tmp_path)
        entry = {"display_name": "Alpha", "jira_labels": ["alpha"]}
        result = dc.set_domain("alpha", entry)
        assert "alpha" in result["domains"]

    def test_set_domain_updates_existing_entry(self, tmp_path):
        dc = _import_dc(tmp_path)
        dc.set_domain("alpha", {"display_name": "Alpha v1"})
        result = dc.set_domain("alpha", {"display_name": "Alpha v2"})
        assert result["domains"]["alpha"]["display_name"] == "Alpha v2"

    def test_set_domain_fills_defaults(self, tmp_path):
        dc = _import_dc(tmp_path)
        result = dc.set_domain("alpha", {"display_name": "Alpha"})
        entry = result["domains"]["alpha"]
        assert entry["description"] == ""
        assert entry["color"] == "#607D8B"
        assert entry["jira_labels"] == []

    def test_set_domain_persists_to_disk(self, tmp_path):
        dc = _import_dc(tmp_path)
        dc.set_domain("alpha", {"display_name": "Alpha"})
        assert dc.config_path().exists()
        loaded = dc.load()
        assert "alpha" in loaded["domains"]

    def test_set_domain_invalid_slug_raises(self, tmp_path):
        dc = _import_dc(tmp_path)
        with pytest.raises(ValueError, match="invalid"):
            dc.set_domain("INVALID", {"display_name": "X"})

    def test_set_domain_missing_display_name_raises(self, tmp_path):
        dc = _import_dc(tmp_path)
        with pytest.raises(ValueError):
            dc.set_domain("alpha", {})

    def test_set_domain_label_conflict_raises(self, tmp_path):
        dc = _import_dc(tmp_path)
        dc.set_domain("alpha", {"display_name": "Alpha", "jira_labels": ["shared"]})
        with pytest.raises(ValueError, match="shared"):
            dc.set_domain("beta", {"display_name": "Beta", "jira_labels": ["shared"]})

    def test_set_domain_label_conflict_case_insensitive(self, tmp_path):
        dc = _import_dc(tmp_path)
        dc.set_domain("alpha", {"display_name": "Alpha", "jira_labels": ["MyLabel"]})
        with pytest.raises(ValueError):
            dc.set_domain("beta", {"display_name": "Beta", "jira_labels": ["mylabel"]})

    def test_set_domain_update_own_labels_no_conflict(self, tmp_path):
        dc = _import_dc(tmp_path)
        dc.set_domain("alpha", {"display_name": "Alpha", "jira_labels": ["lbl"]})
        # Updating the same domain with the same label should not raise
        result = dc.set_domain("alpha", {"display_name": "Alpha Updated", "jira_labels": ["lbl"]})
        assert result["domains"]["alpha"]["display_name"] == "Alpha Updated"

    def test_set_domain_uses_provided_config(self, tmp_path):
        dc = _import_dc(tmp_path)
        existing_config = {"domains": {}}
        result = dc.set_domain("alpha", {"display_name": "Alpha"}, config=existing_config)
        assert "alpha" in result["domains"]


# ---------------------------------------------------------------------------
# build_label_map
# ---------------------------------------------------------------------------


class TestBuildLabelMap:
    def test_empty_config_returns_empty_map(self, tmp_path):
        dc = _import_dc(tmp_path)
        assert dc.build_label_map() == {}

    def test_labels_mapped_to_slug(self, tmp_path):
        dc = _import_dc(tmp_path)
        config = {
            "domains": {
                "search": {
                    "display_name": "Search",
                    "description": "",
                    "color": "#607D8B",
                    "jira_labels": ["Search-Label", "ANOTHER"],
                }
            }
        }
        dc.save(config)
        label_map = dc.build_label_map()
        assert label_map["search-label"] == "search"
        assert label_map["another"] == "search"

    def test_multiple_domains_map_correctly(self, tmp_path):
        dc = _import_dc(tmp_path)
        config = {
            "domains": {
                "alpha": {"display_name": "Alpha", "description": "", "color": "#607D8B", "jira_labels": ["alpha-lbl"]},
                "beta": {"display_name": "Beta", "description": "", "color": "#607D8B", "jira_labels": ["beta-lbl"]},
            }
        }
        dc.save(config)
        label_map = dc.build_label_map()
        assert label_map["alpha-lbl"] == "alpha"
        assert label_map["beta-lbl"] == "beta"

    def test_keys_are_lowercase(self, tmp_path):
        dc = _import_dc(tmp_path)
        config = {
            "domains": {
                "alpha": {"display_name": "Alpha", "description": "", "color": "#607D8B", "jira_labels": ["MixedCase"]},
            }
        }
        dc.save(config)
        label_map = dc.build_label_map()
        assert "mixedcase" in label_map
        assert "MixedCase" not in label_map


# ---------------------------------------------------------------------------
# seed_from_defaults
# ---------------------------------------------------------------------------


class TestSeedFromDefaults:
    def test_creates_config_when_missing(self, tmp_path):
        dc = _import_dc(tmp_path)
        hardcoded = {"label-a": "domain-a", "label-b": "domain-b"}
        result = dc.seed_from_defaults(hardcoded, [])
        assert "domain-a" in result["domains"]
        assert "domain-b" in result["domains"]
        assert dc.config_path().exists()

    def test_idempotent_when_file_exists(self, tmp_path):
        dc = _import_dc(tmp_path)
        existing = {
            "domains": {
                "existing": {
                    "display_name": "Existing",
                    "description": "kept",
                    "color": "#607D8B",
                    "jira_labels": [],
                }
            }
        }
        dc.save(existing)
        result = dc.seed_from_defaults({"new-label": "new-domain"}, ["new-domain"])
        # Must not overwrite
        assert "existing" in result["domains"]
        assert result["domains"]["existing"]["description"] == "kept"
        assert "new-domain" not in result["domains"]

    def test_labels_grouped_by_domain(self, tmp_path):
        dc = _import_dc(tmp_path)
        hardcoded = {
            "label-x": "my-domain",
            "label-y": "my-domain",
            "label-z": "other-domain",
        }
        result = dc.seed_from_defaults(hardcoded, [])
        assert set(result["domains"]["my-domain"]["jira_labels"]) == {"label-x", "label-y"}
        assert result["domains"]["other-domain"]["jira_labels"] == ["label-z"]

    def test_filesystem_domains_added(self, tmp_path):
        dc = _import_dc(tmp_path)
        result = dc.seed_from_defaults({}, ["fs-domain-one", "fs-domain-two"])
        assert "fs-domain-one" in result["domains"]
        assert "fs-domain-two" in result["domains"]
        assert result["domains"]["fs-domain-one"]["jira_labels"] == []

    def test_filesystem_domain_already_in_hardcoded_not_duplicated(self, tmp_path):
        dc = _import_dc(tmp_path)
        hardcoded = {"lbl": "shared-domain"}
        result = dc.seed_from_defaults(hardcoded, ["shared-domain"])
        # Only one entry, labels from hardcoded
        assert result["domains"]["shared-domain"]["jira_labels"] == ["lbl"]

    def test_invalid_slugs_skipped(self, tmp_path):
        dc = _import_dc(tmp_path)
        hardcoded = {"lbl": "INVALID_SLUG"}
        result = dc.seed_from_defaults(hardcoded, ["also_invalid"])
        assert "INVALID_SLUG" not in result["domains"]
        assert "also_invalid" not in result["domains"]

    def test_default_color_assigned(self, tmp_path):
        dc = _import_dc(tmp_path)
        result = dc.seed_from_defaults({"lbl": "my-domain"}, [])
        assert result["domains"]["my-domain"]["color"] == "#607D8B"

    def test_seeded_config_saved_to_disk(self, tmp_path):
        dc = _import_dc(tmp_path)
        dc.seed_from_defaults({"lbl": "my-domain"}, [])
        assert dc.config_path().exists()
        reloaded = dc.load()
        assert "my-domain" in reloaded["domains"]


# ---------------------------------------------------------------------------
# build_keyword_map
# ---------------------------------------------------------------------------


class TestBuildKeywordMap:
    def test_two_domains_with_keywords(self, tmp_path):
        dc = _import_dc(tmp_path)
        config = {
            "domains": {
                "search": {
                    "display_name": "Search",
                    "description": "",
                    "color": "#607D8B",
                    "jira_labels": [],
                    "keywords": ["Search", "fulltext"],
                },
                "catalog": {
                    "display_name": "Catalog",
                    "description": "",
                    "color": "#607D8B",
                    "jira_labels": [],
                    "keywords": ["Catalog", "directory"],
                },
            }
        }
        dc.save(config)
        kw_map = dc.build_keyword_map()
        assert kw_map["search"] == "search"
        assert kw_map["fulltext"] == "search"
        assert kw_map["catalog"] == "catalog"
        assert kw_map["directory"] == "catalog"

    def test_empty_config_returns_empty_dict(self, tmp_path):
        dc = _import_dc(tmp_path)
        # No config file at all
        kw_map = dc.build_keyword_map()
        assert kw_map == {}

    def test_duplicate_keyword_first_domain_wins(self, tmp_path):
        dc = _import_dc(tmp_path)
        # Manually write YAML so order is preserved and both domains have same keyword
        path = dc.config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        # YAML preserves insertion order; "alpha" comes first
        content = yaml.dump(
            {
                "domains": {
                    "alpha": {
                        "display_name": "Alpha",
                        "description": "",
                        "color": "#607D8B",
                        "jira_labels": ["alpha-lbl"],
                        "keywords": ["shared"],
                    },
                    "beta": {
                        "display_name": "Beta",
                        "description": "",
                        "color": "#607D8B",
                        "jira_labels": ["beta-lbl"],
                        "keywords": ["shared"],
                    },
                }
            },
            allow_unicode=True,
            sort_keys=False,
        )
        path.write_text(content, encoding="utf-8")
        dc._cache = None
        dc._cache_mtime = 0.0
        kw_map = dc.build_keyword_map()
        assert kw_map["shared"] == "alpha"


# ---------------------------------------------------------------------------
# build_prompt_section
# ---------------------------------------------------------------------------


class TestBuildPromptSection:
    def test_prompt_hint_used(self, tmp_path):
        dc = _import_dc(tmp_path)
        config = {
            "domains": {
                "search": {
                    "display_name": "Search",
                    "description": "Generic description",
                    "color": "#607D8B",
                    "jira_labels": [],
                    "prompt_hint": "Custom hint for LLM",
                }
            }
        }
        dc.save(config)
        section = dc.build_prompt_section()
        assert "Custom hint for LLM" in section
        assert "Generic description" not in section

    def test_fallback_to_description(self, tmp_path):
        dc = _import_dc(tmp_path)
        config = {
            "domains": {
                "search": {
                    "display_name": "Search",
                    "description": "Fallback description",
                    "color": "#607D8B",
                    "jira_labels": [],
                    "prompt_hint": "",
                }
            }
        }
        dc.save(config)
        section = dc.build_prompt_section()
        assert "Fallback description" in section

    def test_empty_config_returns_empty_string(self, tmp_path):
        dc = _import_dc(tmp_path)
        # No config file — load returns {"domains": {}}
        section = dc.build_prompt_section()
        assert section == ""


# ---------------------------------------------------------------------------
# get_valid_domains
# ---------------------------------------------------------------------------


class TestGetValidDomains:
    def test_three_domains_returns_tuple(self, tmp_path):
        dc = _import_dc(tmp_path)
        config = {
            "domains": {
                "alpha": {"display_name": "Alpha", "description": "", "color": "#607D8B", "jira_labels": []},
                "beta": {"display_name": "Beta", "description": "", "color": "#607D8B", "jira_labels": []},
                "gamma": {"display_name": "Gamma", "description": "", "color": "#607D8B", "jira_labels": []},
            }
        }
        dc.save(config)
        result = dc.get_valid_domains()
        assert isinstance(result, tuple)
        assert len(result) == 3
        assert set(result) == {"alpha", "beta", "gamma"}

    def test_empty_config_returns_empty_tuple(self, tmp_path):
        dc = _import_dc(tmp_path)
        result = dc.get_valid_domains()
        assert isinstance(result, tuple)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# validate_domain_entry — keywords
# ---------------------------------------------------------------------------


class TestValidateKeywords:
    def test_valid_keywords_list(self, tmp_path):
        dc = _import_dc(tmp_path)
        errors = dc.validate_domain_entry(
            "ok-slug",
            {"display_name": "X", "keywords": ["a", "b"]},
        )
        assert not any("keywords" in e for e in errors)

    def test_keywords_not_a_list(self, tmp_path):
        dc = _import_dc(tmp_path)
        errors = dc.validate_domain_entry(
            "ok-slug",
            {"display_name": "X", "keywords": "not-a-list"},
        )
        assert any("keywords" in e for e in errors)

    def test_keywords_contains_empty_string(self, tmp_path):
        dc = _import_dc(tmp_path)
        errors = dc.validate_domain_entry(
            "ok-slug",
            {"display_name": "X", "keywords": ["a", ""]},
        )
        assert any("keywords" in e for e in errors)


# ---------------------------------------------------------------------------
# validate_domain_entry — prompt_hint
# ---------------------------------------------------------------------------


class TestValidatePromptHint:
    def test_valid_prompt_hint(self, tmp_path):
        dc = _import_dc(tmp_path)
        errors = dc.validate_domain_entry(
            "ok-slug",
            {"display_name": "X", "prompt_hint": "ok"},
        )
        assert not any("prompt_hint" in e for e in errors)

    def test_prompt_hint_too_long(self, tmp_path):
        dc = _import_dc(tmp_path)
        errors = dc.validate_domain_entry(
            "ok-slug",
            {"display_name": "X", "prompt_hint": "x" * 501},
        )
        assert any("prompt_hint" in e for e in errors)

    def test_prompt_hint_not_a_string(self, tmp_path):
        dc = _import_dc(tmp_path)
        errors = dc.validate_domain_entry(
            "ok-slug",
            {"display_name": "X", "prompt_hint": 123},
        )
        assert any("prompt_hint" in e for e in errors)


# ---------------------------------------------------------------------------
# set_domain — merge preserves keywords
# ---------------------------------------------------------------------------


class TestSetDomainMergeKeywords:
    def test_update_display_name_preserves_keywords(self, tmp_path):
        dc = _import_dc(tmp_path)
        # Create domain with keywords
        dc.set_domain("alpha", {
            "display_name": "Alpha v1",
            "keywords": ["a", "b"],
        })
        # Update only display_name — do NOT pass keywords
        result = dc.set_domain("alpha", {
            "display_name": "Alpha v2",
        })
        entry = result["domains"]["alpha"]
        assert entry["display_name"] == "Alpha v2"
        assert entry["keywords"] == ["a", "b"]


# ---------------------------------------------------------------------------
# seed_from_defaults — full data from _SEED_DOMAIN_DATA
# ---------------------------------------------------------------------------


class TestSeedWithFullData:
    def test_seed_includes_keywords_and_prompt_hint(self, tmp_path):
        dc = _import_dc(tmp_path)
        # Use a slug that exists in _SEED_DOMAIN_DATA
        result = dc.seed_from_defaults({"search-lbl": "search-engine"}, [])
        entry = result["domains"]["search-engine"]
        # keywords come from _SEED_DOMAIN_DATA["search-engine"]["keywords"]
        assert isinstance(entry["keywords"], list)
        assert len(entry["keywords"]) > 0
        # prompt_hint comes from _SEED_DOMAIN_DATA["search-engine"]["prompt_hint"]
        assert isinstance(entry["prompt_hint"], str)
        assert len(entry["prompt_hint"]) > 0
        # Verify specific values from _SEED_DOMAIN_DATA
        assert "search-engine" in result["domains"]
        assert entry["display_name"] == dc._SEED_DOMAIN_DATA["search-engine"]["display_name"]
