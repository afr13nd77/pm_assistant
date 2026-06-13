"""Tests for artifact_extractor module."""

import importlib
import json
import os
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

# We need to reload vault_paths with a temp VAULT_PATH before importing
# artifact_extractor, since vault_paths.VAULT_PATH is set at import time.


def _setup_vault(tmp_path):
    """Reload vault_paths with VAULT_PATH pointing to tmp_path."""
    with patch.dict(os.environ, {"VAULT_PATH": str(tmp_path)}):
        from shared import vault_paths
        importlib.reload(vault_paths)
    return tmp_path


def _import_extractor(tmp_path):
    """Set up vault and import artifact_extractor with fresh state."""
    _setup_vault(tmp_path)
    from app import artifact_extractor
    importlib.reload(artifact_extractor)
    return artifact_extractor


# ---------------------------------------------------------------------------
# _extract_action_items
# ---------------------------------------------------------------------------


class TestExtractActionItems:
    def test_basic_checkboxes(self, tmp_path):
        ext = _import_extractor(tmp_path)
        body = textwrap.dedent("""\
            # Meeting

            ## Action Items

            - [ ] Fix search ranking algorithm @igor
            - [ ] Update filters for hotels @anna
            - [x] Already done task

            ## Other Section
        """)
        result = ext._extract_action_items(body)
        assert len(result) == 2
        assert result[0]["text"] == "Fix search ranking algorithm @igor"
        assert result[0]["assignee"] == "igor"
        assert result[1]["text"] == "Update filters for hotels @anna"
        assert result[1]["assignee"] == "anna"

    def test_no_assignee(self, tmp_path):
        ext = _import_extractor(tmp_path)
        body = textwrap.dedent("""\
            ## Action Items

            - [ ] Do something without assignee
        """)
        result = ext._extract_action_items(body)
        assert len(result) == 1
        assert result[0]["assignee"] == ""

    def test_no_section(self, tmp_path):
        ext = _import_extractor(tmp_path)
        body = "# Meeting\n\nSome text without action items section.\n"
        result = ext._extract_action_items(body)
        assert result == []

    def test_empty_section(self, tmp_path):
        ext = _import_extractor(tmp_path)
        body = textwrap.dedent("""\
            ## Action Items

            ## Next Section
        """)
        result = ext._extract_action_items(body)
        assert result == []

    def test_case_insensitive_header(self, tmp_path):
        ext = _import_extractor(tmp_path)
        body = textwrap.dedent("""\
            ## action items

            - [ ] Task one
        """)
        result = ext._extract_action_items(body)
        assert len(result) == 1

    def test_section_at_end_of_file(self, tmp_path):
        ext = _import_extractor(tmp_path)
        body = textwrap.dedent("""\
            # Meeting

            ## Action Items

            - [ ] Last task in file
        """)
        result = ext._extract_action_items(body)
        assert len(result) == 1
        assert result[0]["text"] == "Last task in file"


# ---------------------------------------------------------------------------
# _extract_decisions
# ---------------------------------------------------------------------------


class TestExtractDecisions:
    def test_basic_decisions(self, tmp_path):
        ext = _import_extractor(tmp_path)
        body = textwrap.dedent("""\
            # Meeting

            ## Решения

            - Переходим на новый индекс для поиска
            - Откладываем миграцию справочников до Q3

            ## Other
        """)
        result = ext._extract_decisions(body)
        assert len(result) == 2
        assert "новый индекс" in result[0]
        assert "справочников" in result[1]

    def test_no_section(self, tmp_path):
        ext = _import_extractor(tmp_path)
        body = "# Meeting\n\nNo decisions here.\n"
        result = ext._extract_decisions(body)
        assert result == []

    def test_empty_section(self, tmp_path):
        ext = _import_extractor(tmp_path)
        body = textwrap.dedent("""\
            ## Решения

            ## Next
        """)
        result = ext._extract_decisions(body)
        assert result == []

    def test_asterisk_bullets(self, tmp_path):
        ext = _import_extractor(tmp_path)
        body = textwrap.dedent("""\
            ## Решения

            * Decision one
            * Decision two
        """)
        result = ext._extract_decisions(body)
        assert len(result) == 2

    def test_decisions_english_header(self, tmp_path):
        ext = _import_extractor(tmp_path)
        body = textwrap.dedent("""\
            ## Decisions

            - Use Elasticsearch for search
        """)
        result = ext._extract_decisions(body)
        assert len(result) == 1

    def test_plain_text_decisions(self, tmp_path):
        ext = _import_extractor(tmp_path)
        body = textwrap.dedent("""\
            ## Решения

            Мы решили перейти на новую архитектуру поиска.

            ## Next
        """)
        result = ext._extract_decisions(body)
        assert len(result) == 1
        assert "новую архитектуру" in result[0]


# ---------------------------------------------------------------------------
# _extract_ideas
# ---------------------------------------------------------------------------


class TestExtractIdeas:
    def test_basic_ideas(self, tmp_path):
        ext = _import_extractor(tmp_path)
        body = textwrap.dedent("""\
            # Meeting

            ## Идеи

            - Можно добавить автокомплит по отелям
            - Стоит попробовать ML для ранжирования

            ## Next
        """)
        result = ext._extract_ideas(body)
        assert len(result) == 2
        assert "автокомплит" in result[0]
        assert "ранжирования" in result[1]

    def test_no_section(self, tmp_path):
        ext = _import_extractor(tmp_path)
        body = "# Meeting\n\nNo ideas section.\n"
        result = ext._extract_ideas(body)
        assert result == []

    def test_english_header(self, tmp_path):
        ext = _import_extractor(tmp_path)
        body = textwrap.dedent("""\
            ## Ideas

            - Idea in English
        """)
        result = ext._extract_ideas(body)
        assert len(result) == 1

    def test_empty_section(self, tmp_path):
        ext = _import_extractor(tmp_path)
        body = textwrap.dedent("""\
            ## Идеи

            ## Next
        """)
        result = ext._extract_ideas(body)
        assert result == []


# ---------------------------------------------------------------------------
# _detect_domain
# ---------------------------------------------------------------------------


class TestDetectDomain:
    def test_search_engine_keywords(self, tmp_path):
        ext = _import_extractor(tmp_path)
        assert ext._detect_domain("Нужно улучшить поиск отелей") == "search-engine"
        assert ext._detect_domain("Обновить индексацию документов") == "search-engine"
        assert ext._detect_domain("Пересмотреть ранжирование") == "search-engine"
        assert ext._detect_domain("Настроить фильтры по цене") == "search-engine"

    def test_suggester_keywords(self, tmp_path):
        ext = _import_extractor(tmp_path)
        assert ext._detect_domain("Добавить автокомплит для городов") == "suggester"
        assert ext._detect_domain("Улучшить подсказки") == "suggester"
        assert ext._detect_domain("Настроить typeahead") == "suggester"
        assert ext._detect_domain("Implement suggest endpoint") == "suggester"

    def test_static_metadata_keywords(self, tmp_path):
        ext = _import_extractor(tmp_path)
        assert ext._detect_domain("Обновить справочник стран") == "static-metadata"
        assert ext._detect_domain("Добавить атрибуты отелей") == "static-metadata"
        assert ext._detect_domain("Загрузить метаданные") == "static-metadata"
        assert ext._detect_domain("Новый классификатор") == "static-metadata"
        assert ext._detect_domain("Обновить каталог") == "static-metadata"
        assert ext._detect_domain("Проверить контент") == "static-metadata"

    def test_general_fallback(self, tmp_path):
        ext = _import_extractor(tmp_path)
        assert ext._detect_domain("Провести ретроспективу") == "general"
        assert ext._detect_domain("Обновить документацию") == "general"

    def test_case_insensitive(self, tmp_path):
        ext = _import_extractor(tmp_path)
        assert ext._detect_domain("Улучшить ПОИСК") == "search-engine"

    def test_first_match_wins(self, tmp_path):
        ext = _import_extractor(tmp_path)
        # "поиск" should match search-engine first
        result = ext._detect_domain("Поиск по справочнику")
        assert result == "search-engine"


# ---------------------------------------------------------------------------
# _detect_source_type
# ---------------------------------------------------------------------------


class TestDetectSourceType:
    def test_meeting(self, tmp_path):
        ext = _import_extractor(tmp_path)
        p = Path("/vault/wiki/meetings/2026-05-01-standup.md")
        assert ext._detect_source_type(p) == "meeting"

    def test_daily_log(self, tmp_path):
        ext = _import_extractor(tmp_path)
        p = Path("/vault/wiki/daily-logs/2026-05-01.md")
        assert ext._detect_source_type(p) == "daily-log"

    def test_unknown(self, tmp_path):
        ext = _import_extractor(tmp_path)
        p = Path("/vault/raw/inbound/ideas/something.md")
        assert ext._detect_source_type(p) == "unknown"


# ---------------------------------------------------------------------------
# _write_task_artifact
# ---------------------------------------------------------------------------


class TestWriteTaskArtifact:
    def test_writes_file_with_frontmatter(self, tmp_path):
        ext = _import_extractor(tmp_path)
        ext._TODAY = "2026-05-01"

        rel_source = Path("wiki/meetings/standup.md")
        result = ext._write_task_artifact(
            "Fix search ranking", "search-engine", rel_source, 1,
        )

        assert result.exists()
        assert result.name == "2026-05-01-action-01.md"
        assert result.parent == tmp_path / "wiki" / "domains" / "search-engine" / "tasks"

        content = result.read_text(encoding="utf-8")
        assert "tags: [action-item]" in content
        assert "date: 2026-05-01" in content
        assert "status: inbox" in content
        assert "domain: search-engine" in content
        assert '[[wiki/meetings/standup.md]]' in content
        assert "type: Task" in content
        assert "# Fix search ranking" in content

        ext._TODAY = None


# ---------------------------------------------------------------------------
# _append_decision
# ---------------------------------------------------------------------------


class TestAppendDecision:
    def test_creates_decisions_file_if_missing(self, tmp_path):
        ext = _import_extractor(tmp_path)
        ext._TODAY = "2026-05-01"

        rel_source = Path("wiki/meetings/standup.md")
        ext._append_decision("Use Elasticsearch", "search-engine", rel_source)

        decisions_path = (
            tmp_path / "wiki" / "domains" / "search-engine" / "decisions.md"
        )
        assert decisions_path.exists()
        content = decisions_path.read_text(encoding="utf-8")
        assert "# Решения — search-engine" in content
        assert "### [2026-05-01] Use Elasticsearch" in content
        assert "[[wiki/meetings/standup.md]]" in content

        ext._TODAY = None

    def test_appends_to_existing_decisions(self, tmp_path):
        ext = _import_extractor(tmp_path)
        ext._TODAY = "2026-05-01"

        domain_dir = tmp_path / "wiki" / "domains" / "general"
        domain_dir.mkdir(parents=True)
        decisions_path = domain_dir / "decisions.md"
        decisions_path.write_text(
            "# Решения — general\n\n### [2026-04-30] Old decision\n\n---\n\n",
            encoding="utf-8",
        )

        rel_source = Path("wiki/daily-logs/2026-05-01.md")
        ext._append_decision("New decision", "general", rel_source)

        content = decisions_path.read_text(encoding="utf-8")
        assert "Old decision" in content
        assert "New decision" in content
        assert content.index("Old decision") < content.index("New decision")

        ext._TODAY = None


# ---------------------------------------------------------------------------
# _write_idea_artifact
# ---------------------------------------------------------------------------


class TestWriteIdeaArtifact:
    def test_writes_idea_file(self, tmp_path):
        ext = _import_extractor(tmp_path)
        ext._TODAY = "2026-05-01"

        rel_source = Path("wiki/meetings/standup.md")
        result = ext._write_idea_artifact(
            "ML for ranking", "search-engine", rel_source, 1,
        )

        assert result.exists()
        assert result.name == "2026-05-01-extracted-01.md"
        assert result.parent == tmp_path / "wiki" / "domains" / "search-engine" / "ideas"

        content = result.read_text(encoding="utf-8")
        assert "tags: [idea, extracted]" in content
        assert "domain: search-engine" in content
        assert "type: Idea" in content
        assert "# ML for ranking" in content

        ext._TODAY = None


# ---------------------------------------------------------------------------
# extract_artifacts — full integration
# ---------------------------------------------------------------------------


class TestExtractArtifacts:
    def test_meeting_with_multiple_domains(self, tmp_path):
        ext = _import_extractor(tmp_path)
        ext._TODAY = "2026-05-01"

        # Create a meeting file inside the vault
        meetings_dir = tmp_path / "wiki" / "meetings"
        meetings_dir.mkdir(parents=True)
        meeting_file = meetings_dir / "2026-05-01-standup.md"
        meeting_file.write_text(
            textwrap.dedent("""\
                ---
                date: 2026-05-01
                type: meeting
                ---

                # Standup 2026-05-01

                ## Action Items

                - [ ] Починить ранжирование в поиске @igor
                - [ ] Обновить справочник стран @anna

                ## Решения

                - Переходим на Elasticsearch для индексации

                ## Идеи

                - Добавить автокомплит для городов
            """),
            encoding="utf-8",
        )

        result = ext.extract_artifacts(meeting_file)

        assert result["source"] == "wiki/meetings/2026-05-01-standup.md"

        artifacts = result["artifacts"]
        assert len(artifacts) == 4  # 2 tasks + 1 decision + 1 idea

        # Verify tasks
        tasks = [a for a in artifacts if a["type"] == "task"]
        assert len(tasks) == 2
        task_domains = {t["domain"] for t in tasks}
        assert "search-engine" in task_domains
        assert "static-metadata" in task_domains

        # Verify decision
        decisions = [a for a in artifacts if a["type"] == "decision"]
        assert len(decisions) == 1
        assert decisions[0]["domain"] == "search-engine"

        # Verify idea
        ideas = [a for a in artifacts if a["type"] == "idea"]
        assert len(ideas) == 1
        assert ideas[0]["domain"] == "suggester"

        # Verify files were actually created
        se_tasks = tmp_path / "wiki" / "domains" / "search-engine" / "tasks"
        assert (se_tasks / "2026-05-01-action-01.md").exists()

        sm_tasks = tmp_path / "wiki" / "domains" / "static-metadata" / "tasks"
        assert (sm_tasks / "2026-05-01-action-02.md").exists()

        sugg_ideas = tmp_path / "wiki" / "domains" / "suggester" / "ideas"
        assert (sugg_ideas / "2026-05-01-extracted-01.md").exists()

        se_decisions = (
            tmp_path / "wiki" / "domains" / "search-engine" / "decisions.md"
        )
        assert se_decisions.exists()
        dec_content = se_decisions.read_text(encoding="utf-8")
        assert "Elasticsearch" in dec_content

        ext._TODAY = None

    def test_daily_log_source(self, tmp_path):
        ext = _import_extractor(tmp_path)
        ext._TODAY = "2026-05-01"

        daily_dir = tmp_path / "wiki" / "daily-logs"
        daily_dir.mkdir(parents=True)
        daily_file = daily_dir / "2026-05-01.md"
        daily_file.write_text(
            textwrap.dedent("""\
                ---
                date: 2026-05-01
                type: daily-log
                ---

                # Daily Log 2026-05-01

                ## Action Items

                - [ ] Проверить typeahead на проде

                ## Решения

                - Оставляем текущий каталог без изменений
            """),
            encoding="utf-8",
        )

        result = ext.extract_artifacts(daily_file)
        artifacts = result["artifacts"]
        assert len(artifacts) == 2  # 1 task + 1 decision

        # Check task domain
        tasks = [a for a in artifacts if a["type"] == "task"]
        assert tasks[0]["domain"] == "suggester"

        # Check decision domain
        decisions = [a for a in artifacts if a["type"] == "decision"]
        assert decisions[0]["domain"] == "static-metadata"

        # Verify source links contain daily-logs
        task_file = (
            tmp_path
            / "wiki"
            / "domains"
            / "suggester"
            / "tasks"
            / "2026-05-01-action-01.md"
        )
        content = task_file.read_text(encoding="utf-8")
        assert "daily-logs" in content

        ext._TODAY = None

    def test_nonexistent_file(self, tmp_path):
        ext = _import_extractor(tmp_path)
        result = ext.extract_artifacts(tmp_path / "nonexistent.md")
        assert result["artifacts"] == []

    def test_no_sections(self, tmp_path):
        ext = _import_extractor(tmp_path)
        ext._TODAY = "2026-05-01"

        meetings_dir = tmp_path / "wiki" / "meetings"
        meetings_dir.mkdir(parents=True)
        meeting_file = meetings_dir / "empty-meeting.md"
        meeting_file.write_text(
            textwrap.dedent("""\
                ---
                date: 2026-05-01
                ---

                # Meeting without structured sections

                Just some general discussion notes.
            """),
            encoding="utf-8",
        )

        result = ext.extract_artifacts(meeting_file)
        assert result["artifacts"] == []

        ext._TODAY = None

    def test_malformed_markdown(self, tmp_path):
        ext = _import_extractor(tmp_path)
        ext._TODAY = "2026-05-01"

        meetings_dir = tmp_path / "wiki" / "meetings"
        meetings_dir.mkdir(parents=True)
        meeting_file = meetings_dir / "malformed.md"
        meeting_file.write_text(
            textwrap.dedent("""\
                Some text without frontmatter

                ## Action Items

                Not a checkbox line
                - Regular bullet without checkbox
                - [ ] Valid task about поиск

                ## Решения

                ## Идеи

                - Valid idea about автокомплит
            """),
            encoding="utf-8",
        )

        result = ext.extract_artifacts(meeting_file)
        artifacts = result["artifacts"]

        # Should only get the valid checkbox task and valid idea
        tasks = [a for a in artifacts if a["type"] == "task"]
        assert len(tasks) == 1

        ideas = [a for a in artifacts if a["type"] == "idea"]
        assert len(ideas) == 1

        ext._TODAY = None

    def test_file_outside_vault(self, tmp_path):
        """Source file not under VAULT_PATH should still work."""
        ext = _import_extractor(tmp_path)
        ext._TODAY = "2026-05-01"

        # Create file outside vault
        outside = tmp_path / "outside"
        outside.mkdir()
        src = outside / "meeting.md"
        src.write_text(
            textwrap.dedent("""\
                ## Action Items

                - [ ] Task about поиск
            """),
            encoding="utf-8",
        )

        result = ext.extract_artifacts(src)
        assert len(result["artifacts"]) == 1

        ext._TODAY = None

    def test_sequential_numbering(self, tmp_path):
        """Multiple action items should get sequential numbers."""
        ext = _import_extractor(tmp_path)
        ext._TODAY = "2026-05-01"

        meetings_dir = tmp_path / "wiki" / "meetings"
        meetings_dir.mkdir(parents=True)
        meeting_file = meetings_dir / "multi.md"
        meeting_file.write_text(
            textwrap.dedent("""\
                ## Action Items

                - [ ] Первая задача
                - [ ] Вторая задача
                - [ ] Третья задача
            """),
            encoding="utf-8",
        )

        result = ext.extract_artifacts(meeting_file)
        tasks = [a for a in result["artifacts"] if a["type"] == "task"]
        assert len(tasks) == 3
        assert tasks[0]["filename"] == "2026-05-01-action-01.md"
        assert tasks[1]["filename"] == "2026-05-01-action-02.md"
        assert tasks[2]["filename"] == "2026-05-01-action-03.md"

        ext._TODAY = None


# ---------------------------------------------------------------------------
# _merged_keyword_map — config integration (BL-119)
# ---------------------------------------------------------------------------


class TestMergedKeywordMap:
    def test_merged_keyword_map_with_config(self, tmp_path):
        """Config keywords are merged with hardcoded _DOMAIN_KEYWORDS."""
        ext = _import_extractor(tmp_path)

        fake_config = {
            "domains": {
                "partner-search-engine": {
                    "display_name": "Partner Search",
                    "keywords": ["поставщик", "b2b"],
                },
            },
        }

        with patch("shared.domain_config.load", return_value=fake_config):
            result = ext._merged_keyword_map()

        # Hardcoded domains are present
        assert "search-engine" in result
        assert "suggester" in result
        assert "static-metadata" in result

        # Config domain is also present
        assert "partner-search-engine" in result
        assert "поставщик" in result["partner-search-engine"]
        assert "b2b" in result["partner-search-engine"]

    def test_merged_keyword_map_no_config(self, tmp_path):
        """When config loading fails, only hardcoded keywords are returned."""
        ext = _import_extractor(tmp_path)

        with patch(
            "shared.domain_config.load", side_effect=Exception("config unavailable"),
        ):
            result = ext._merged_keyword_map()

        # Hardcoded domains are present
        assert "search-engine" in result
        assert "suggester" in result
        assert "static-metadata" in result

        # No config-only domains
        assert "partner-search-engine" not in result

        # Verify hardcoded keywords survived
        assert "поиск" in result["search-engine"]
        assert "автокомплит" in result["suggester"]


# ---------------------------------------------------------------------------
# _detect_domain — config-based detection (BL-119)
# ---------------------------------------------------------------------------


class TestDetectDomainWithConfig:
    def test_detect_domain_partner_search(self, tmp_path):
        """Config keywords enable detection of config-only domains."""
        ext = _import_extractor(tmp_path)

        fake_config = {
            "domains": {
                "partner-search-engine": {
                    "display_name": "Partner Search",
                    "keywords": ["поставщик", "b2b"],
                },
            },
        }

        with patch("shared.domain_config.load", return_value=fake_config):
            result = ext._detect_domain("настроить B2B-интеграцию")

        assert result == "partner-search-engine"

    def test_detect_domain_general_fallback(self, tmp_path):
        """Text without any matching keywords falls back to 'general'."""
        ext = _import_extractor(tmp_path)

        # No config keywords either — use empty config
        fake_config = {"domains": {}}
        with patch("shared.domain_config.load", return_value=fake_config):
            result = ext._detect_domain("провести ретроспективу по спринту")

        assert result == "general"
