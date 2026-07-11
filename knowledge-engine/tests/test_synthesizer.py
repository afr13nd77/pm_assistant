"""Tests for synthesizer module with domain-based vault structure."""
import importlib
import os
from pathlib import Path
from unittest.mock import patch


def _setup_vault(tmp_path):
    """Set up vault_paths module to use tmp_path."""
    with patch.dict(os.environ, {"VAULT_PATH": str(tmp_path)}):
        from shared import vault_paths
        importlib.reload(vault_paths)
    return tmp_path


def _create_idea(path: Path, title: str, tags=None, status="inbox"):
    """Create an idea .md file with frontmatter."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fm = ["---"]
    if tags:
        fm.append(f"tags: [{', '.join(tags)}]")
    fm.append(f"status: {status}")
    fm.append("---")
    fm.append(f"# {title}")
    fm.append("")
    fm.append("Idea body content.")
    path.write_text("\n".join(fm), encoding="utf-8")


class TestSynthesizeCollectIdeas:
    def test_collect_ideas_from_multiple_domains(self, tmp_path):
        _setup_vault(tmp_path)

        # Create ideas in two domains
        d1 = tmp_path / "wiki" / "domains" / "search" / "ideas"
        _create_idea(d1 / "idea-01.md", "Search Idea 1")
        _create_idea(d1 / "idea-02.md", "Search Idea 2")

        d2 = tmp_path / "wiki" / "domains" / "booking" / "ideas"
        _create_idea(d2 / "idea-01.md", "Booking Idea 1")

        from app.synthesizer import _collect_ideas
        ideas = _collect_ideas()

        assert len(ideas) == 3
        domains = {i["domain"] for i in ideas}
        assert domains == {"search", "booking"}

    def test_collect_ideas_skips_processed(self, tmp_path):
        _setup_vault(tmp_path)

        d = tmp_path / "wiki" / "domains" / "search" / "ideas"
        _create_idea(d / "idea-01.md", "Inbox Idea", status="inbox")
        _create_idea(d / "idea-02.md", "Enriched Idea", status="enriched")
        _create_idea(d / "idea-03.md", "Processed Idea", status="processed")

        from app.synthesizer import _collect_ideas
        ideas = _collect_ideas()

        assert len(ideas) == 2
        statuses = {i["status"] for i in ideas}
        assert statuses == {"inbox", "enriched"}

    def test_collect_ideas_has_filepath_field(self, tmp_path):
        _setup_vault(tmp_path)

        d = tmp_path / "wiki" / "domains" / "search" / "ideas"
        _create_idea(d / "idea-01.md", "Test Idea")

        from app.synthesizer import _collect_ideas
        ideas = _collect_ideas()

        assert len(ideas) == 1
        assert "filepath" in ideas[0]
        assert ideas[0]["filepath"] == str(d / "idea-01.md")

    def test_collect_ideas_empty_vault(self, tmp_path):
        _setup_vault(tmp_path)

        from app.synthesizer import _collect_ideas
        ideas = _collect_ideas()

        assert ideas == []


class TestSynthesize:
    @patch("app.synthesizer.claude_client")
    @patch("app.synthesizer.send_telegram")
    def test_synthesize_writes_to_reports(self, mock_telegram, mock_claude, tmp_path):
        _setup_vault(tmp_path)

        d = tmp_path / "wiki" / "domains" / "search" / "ideas"
        _create_idea(d / "idea-01.md", "Test Idea")

        mock_claude.synthesize.return_value = "# Synthesis Report\n\nSummary of ideas."

        from app.synthesizer import synthesize
        result = synthesize(str(tmp_path))

        assert result["status"] == "ok"
        assert result["count"] == 1

        # Check file was written to wiki/reports/
        reports_dir = tmp_path / "wiki" / "reports"
        assert reports_dir.exists()
        report_files = list(reports_dir.glob("synthesis-*.md"))
        assert len(report_files) == 1

    @patch("app.synthesizer.claude_client")
    @patch("app.synthesizer.send_telegram")
    def test_synthesize_marks_processed(self, mock_telegram, mock_claude, tmp_path):
        _setup_vault(tmp_path)

        d = tmp_path / "wiki" / "domains" / "search" / "ideas"
        _create_idea(d / "idea-01.md", "Test Idea", status="inbox")

        mock_claude.synthesize.return_value = "# Synthesis\n\nContent."

        from app.synthesizer import synthesize
        result = synthesize(str(tmp_path))

        assert result["status"] == "ok"

        # Check idea was marked as processed
        content = (d / "idea-01.md").read_text(encoding="utf-8")
        assert "processed" in content

    def test_synthesize_skip_not_enough_ideas(self, tmp_path):
        _setup_vault(tmp_path)

        from app.synthesizer import synthesize
        result = synthesize(str(tmp_path), min_ideas=5)

        assert result["status"] == "skip"

    def test_synthesize_dry_run(self, tmp_path):
        _setup_vault(tmp_path)

        d = tmp_path / "wiki" / "domains" / "booking" / "ideas"
        _create_idea(d / "idea-01.md", "Booking Idea")

        from app.synthesizer import synthesize
        result = synthesize(str(tmp_path), dry_run=True)

        assert result["status"] == "dry_run"
        assert result["count"] == 1


class TestUniqueFilename:
    def test_first_file(self, tmp_path):
        from app.synthesizer import _unique_filename
        name = _unique_filename(tmp_path, "synthesis-2026-04-28")
        assert name == "synthesis-2026-04-28.md"

    def test_second_file(self, tmp_path):
        (tmp_path / "synthesis-2026-04-28.md").write_text("exists")
        from app.synthesizer import _unique_filename
        name = _unique_filename(tmp_path, "synthesis-2026-04-28")
        assert name == "synthesis-2026-04-28-02.md"

    def test_third_file(self, tmp_path):
        (tmp_path / "synthesis-2026-04-28.md").write_text("exists")
        (tmp_path / "synthesis-2026-04-28-02.md").write_text("exists")
        from app.synthesizer import _unique_filename
        name = _unique_filename(tmp_path, "synthesis-2026-04-28")
        assert name == "synthesis-2026-04-28-03.md"
