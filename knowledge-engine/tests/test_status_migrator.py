"""Tests for status_migrator module."""
import os
from pathlib import Path
from unittest.mock import patch

import pytest

import frontmatter


def _import_module(vault_path_str="/test/vault"):
    """Import status_migrator with a custom VAULT_PATH."""
    with patch.dict(os.environ, {"VAULT_PATH": vault_path_str}):
        import importlib
        from app import vault_paths
        importlib.reload(vault_paths)
        from app import status_migrator
        importlib.reload(status_migrator)
        return status_migrator


def _write_idea(filepath: Path, status: str | None, body: str = "some content"):
    """Write a minimal .md file with frontmatter."""
    post = frontmatter.Post(body)
    if status is not None:
        post["status"] = status
    filepath.write_text(frontmatter.dumps(post), encoding="utf-8")


class TestClassifyStatus:
    def setup_method(self):
        self.mod = _import_module()

    def test_none_returns_missing(self):
        action, new = self.mod._classify_status(None)
        assert action == "missing"
        assert new == "Новая"

    def test_empty_string_returns_missing(self):
        action, new = self.mod._classify_status("")
        assert action == "missing"
        assert new == "Новая"

    def test_whitespace_only_returns_missing(self):
        action, new = self.mod._classify_status("   ")
        assert action == "missing"
        assert new == "Новая"

    def test_valid_status_skip(self):
        for status in ("Новая", "Проверка гипотезы", "Готова к производству", "Отсев"):
            action, new = self.mod._classify_status(status)
            assert action == "skip"
            assert new == status

    def test_mapped_status_migrate(self):
        action, new = self.mod._classify_status("inbox")
        assert action == "migrate"
        assert new == "Новая"

    def test_mapped_status_processed(self):
        action, new = self.mod._classify_status("processed")
        assert action == "migrate"
        assert new == "Проверка гипотезы"

    def test_mapped_status_done(self):
        action, new = self.mod._classify_status("done")
        assert action == "migrate"
        assert new == "Готова к производству"

    def test_mapped_status_rejected(self):
        action, new = self.mod._classify_status("rejected")
        assert action == "migrate"
        assert new == "Отсев"

    def test_mapped_status_case_insensitive(self):
        action, new = self.mod._classify_status("INBOX")
        assert action == "migrate"
        assert new == "Новая"

    def test_mapped_status_with_whitespace(self):
        action, new = self.mod._classify_status("  draft  ")
        assert action == "migrate"
        assert new == "Новая"

    def test_mapped_status_cyrillic(self):
        action, new = self.mod._classify_status("бэклог")
        assert action == "migrate"
        assert new == "Новая"

    def test_unknown_status(self):
        action, new = self.mod._classify_status("totally-unknown")
        assert action == "unknown"
        assert new is None

    def test_valid_status_case_sensitive_no_migrate(self):
        """Valid statuses are case-sensitive; lowercase valid name is unknown if not in STATUS_MAP."""
        action, new = self.mod._classify_status("новая")
        assert action == "unknown"
        assert new is None


class TestMigrateStatuses:

    def _setup_vault(self, tmp_path, domain, files: dict[str, str | None]):
        """Create domain/ideas/ dir and populate with files.

        files: {filename: status_value_or_None}
        If status_value is the string "__no_key__", the file is written without a status key.
        """
        ideas_dir = tmp_path / "wiki" / "domains" / domain / "ideas"
        ideas_dir.mkdir(parents=True, exist_ok=True)
        for fname, status in files.items():
            fpath = ideas_dir / fname
            if status == "__no_key__":
                _write_idea(fpath, status=None)
            else:
                _write_idea(fpath, status=status)
        return ideas_dir

    def test_empty_vault(self, tmp_path):
        mod = _import_module(str(tmp_path))
        report = mod.migrate_statuses(str(tmp_path))
        assert report["status"] == "ok"
        assert report["migrated"] == 0
        assert report["skipped"] == 0
        assert report["errors"] == 0
        assert report["unknown_statuses"] == 0
        assert report["details"] == []

    def test_skip_valid_statuses(self, tmp_path):
        mod = _import_module(str(tmp_path))
        self._setup_vault(tmp_path, "hotels", {
            "idea-1.md": "Новая",
            "idea-2.md": "Отсев",
        })
        report = mod.migrate_statuses(str(tmp_path))
        assert report["skipped"] == 2
        assert report["migrated"] == 0

    def test_migrate_old_statuses(self, tmp_path):
        mod = _import_module(str(tmp_path))
        self._setup_vault(tmp_path, "hotels", {
            "idea-1.md": "inbox",
            "idea-2.md": "processed",
            "idea-3.md": "done",
        })
        report = mod.migrate_statuses(str(tmp_path))
        assert report["migrated"] == 3
        assert report["skipped"] == 0

        post1 = frontmatter.load(str(tmp_path / "wiki/domains/hotels/ideas/idea-1.md"))
        assert post1["status"] == "Новая"

        post2 = frontmatter.load(str(tmp_path / "wiki/domains/hotels/ideas/idea-2.md"))
        assert post2["status"] == "Проверка гипотезы"

        post3 = frontmatter.load(str(tmp_path / "wiki/domains/hotels/ideas/idea-3.md"))
        assert post3["status"] == "Готова к производству"

    def test_missing_status_gets_set(self, tmp_path):
        mod = _import_module(str(tmp_path))
        self._setup_vault(tmp_path, "hotels", {
            "idea-no-status.md": "__no_key__",
        })
        report = mod.migrate_statuses(str(tmp_path))
        assert report["migrated"] == 1
        details = report["details"]
        assert len(details) == 1
        assert details[0]["action"] == "missing"
        assert details[0]["new_status"] == "Новая"

        post = frontmatter.load(str(tmp_path / "wiki/domains/hotels/ideas/idea-no-status.md"))
        assert post["status"] == "Новая"

    def test_unknown_status_not_modified(self, tmp_path):
        mod = _import_module(str(tmp_path))
        self._setup_vault(tmp_path, "hotels", {
            "idea-weird.md": "some-random-status",
        })
        report = mod.migrate_statuses(str(tmp_path))
        assert report["unknown_statuses"] == 1
        assert report["migrated"] == 0

        post = frontmatter.load(str(tmp_path / "wiki/domains/hotels/ideas/idea-weird.md"))
        assert post["status"] == "some-random-status"

    def test_dry_run_does_not_modify_files(self, tmp_path):
        mod = _import_module(str(tmp_path))
        self._setup_vault(tmp_path, "hotels", {
            "idea-1.md": "inbox",
        })
        report = mod.migrate_statuses(str(tmp_path), dry_run=True)
        assert report["migrated"] == 1

        post = frontmatter.load(str(tmp_path / "wiki/domains/hotels/ideas/idea-1.md"))
        assert post["status"] == "inbox"

    def test_service_files_skipped(self, tmp_path):
        mod = _import_module(str(tmp_path))
        ideas_dir = self._setup_vault(tmp_path, "hotels", {
            "index.md": "inbox",
            "log.md": "processed",
            "real-idea.md": "Новая",
        })
        report = mod.migrate_statuses(str(tmp_path))
        assert report["skipped"] == 1
        assert report["migrated"] == 0
        assert len(report["details"]) == 1

    def test_multiple_domains(self, tmp_path):
        mod = _import_module(str(tmp_path))
        self._setup_vault(tmp_path, "hotels", {
            "idea-1.md": "inbox",
        })
        self._setup_vault(tmp_path, "flights", {
            "idea-2.md": "done",
        })
        report = mod.migrate_statuses(str(tmp_path))
        assert report["migrated"] == 2
        domains = {d["domain"] for d in report["details"]}
        assert domains == {"hotels", "flights"}

    def test_domain_without_ideas_dir(self, tmp_path):
        mod = _import_module(str(tmp_path))
        (tmp_path / "wiki" / "domains" / "empty-domain").mkdir(parents=True)
        report = mod.migrate_statuses(str(tmp_path))
        assert report["migrated"] == 0
        assert report["details"] == []

    def test_error_handling_continues(self, tmp_path):
        mod = _import_module(str(tmp_path))
        self._setup_vault(tmp_path, "hotels", {
            "good-idea.md": "inbox",
        })
        bad_file = tmp_path / "wiki" / "domains" / "hotels" / "ideas" / "bad-idea.md"
        bad_file.write_text("not valid frontmatter \x00\x01\x02", encoding="utf-8")

        report = mod.migrate_statuses(str(tmp_path))
        assert report["migrated"] + report["errors"] + report["skipped"] + report["unknown_statuses"] >= 1
        actions = {d["action"] for d in report["details"]}
        assert "migrate" in actions or "error" in actions

    def test_report_structure(self, tmp_path):
        mod = _import_module(str(tmp_path))
        self._setup_vault(tmp_path, "hotels", {
            "idea-1.md": "inbox",
        })
        report = mod.migrate_statuses(str(tmp_path))
        assert set(report.keys()) == {"status", "migrated", "skipped", "errors", "unknown_statuses", "details"}
        detail = report["details"][0]
        assert set(detail.keys()) == {"file", "domain", "old_status", "new_status", "action", "error"}

    def test_updated_field_is_set(self, tmp_path):
        mod = _import_module(str(tmp_path))
        self._setup_vault(tmp_path, "hotels", {
            "idea-1.md": "inbox",
        })
        mod.migrate_statuses(str(tmp_path))
        post = frontmatter.load(str(tmp_path / "wiki/domains/hotels/ideas/idea-1.md"))
        from datetime import date
        assert post["updated"] == date.today().isoformat()
