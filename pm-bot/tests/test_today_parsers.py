"""Tests for app.today_parsers — find_latest_file, parse_digest, parse_todos, parse_news, format_todo_block."""

from datetime import date
from pathlib import Path

from app.today_parsers import (
    _extract_section,
    _extract_wikilinks,
    _label_to_key,
    _parse_section,
    find_latest_file,
    format_todo_block,
    parse_digest,
    parse_news,
    parse_todos,
)

# ===================================================================
# _extract_wikilinks
# ===================================================================


class TestExtractWikilinks:
    def test_single_link(self):
        assert _extract_wikilinks("see [[my-note]]") == ["my-note"]

    def test_multiple_links(self):
        text = "[[a]] and [[b-c]] done"
        assert _extract_wikilinks(text) == ["a", "b-c"]

    def test_no_links(self):
        assert _extract_wikilinks("plain text") == []

    def test_empty_string(self):
        assert _extract_wikilinks("") == []


# ===================================================================
# _label_to_key
# ===================================================================


class TestLabelToKey:
    def test_simple_label(self):
        assert _label_to_key("Производство") == "производство"

    def test_label_with_и(self):
        assert _label_to_key("Идеи и бэклог") == "идеи_бэклог"

    def test_spaces(self):
        assert _label_to_key("Мои TODO") == "мои_todo"


# ===================================================================
# find_latest_file
# ===================================================================


class TestFindLatestFile:
    def test_finds_todays_file(self, tmp_path: Path):
        today = date(2026, 7, 22)
        target = tmp_path / "2026-07-22-morning-digest.md"
        target.write_text("hello", encoding="utf-8")

        path, is_today = find_latest_file(tmp_path, "morning-digest", today)
        assert path == target
        assert is_today is True

    def test_falls_back_to_latest(self, tmp_path: Path):
        today = date(2026, 7, 22)
        old1 = tmp_path / "2026-07-20-morning-digest.md"
        old2 = tmp_path / "2026-07-21-morning-digest.md"
        old1.write_text("old1", encoding="utf-8")
        old2.write_text("old2", encoding="utf-8")

        path, is_today = find_latest_file(tmp_path, "morning-digest", today)
        assert path == old2
        assert is_today is False

    def test_returns_none_when_empty(self, tmp_path: Path):
        today = date(2026, 7, 22)
        path, is_today = find_latest_file(tmp_path, "morning-digest", today)
        assert path is None
        assert is_today is False

    def test_returns_none_when_directory_missing(self, tmp_path: Path):
        today = date(2026, 7, 22)
        missing = tmp_path / "nonexistent"
        path, is_today = find_latest_file(missing, "morning-digest", today)
        assert path is None
        assert is_today is False

    def test_prefers_today_over_older(self, tmp_path: Path):
        today = date(2026, 7, 22)
        older = tmp_path / "2026-07-21-morning-digest.md"
        todays = tmp_path / "2026-07-22-morning-digest.md"
        older.write_text("old", encoding="utf-8")
        todays.write_text("new", encoding="utf-8")

        path, is_today = find_latest_file(tmp_path, "morning-digest", today)
        assert path == todays
        assert is_today is True

    def test_ignores_non_matching_prefix(self, tmp_path: Path):
        today = date(2026, 7, 22)
        unrelated = tmp_path / "2026-07-22-news-digest.md"
        unrelated.write_text("news", encoding="utf-8")

        path, is_today = find_latest_file(tmp_path, "morning-digest", today)
        assert path is None
        assert is_today is False


# ===================================================================
# parse_digest
# ===================================================================


SAMPLE_DIGEST = """\
# Утренний дайджест 2026-07-22

### Фокус дня
Запуск keyword-search в production
Финальное тестирование поиска по ключевым словам [[keyword-search-prd]]

### Производство
- [[keyword-search-epic]] — MVP deployed, проходит smoke-тесты
- [[hotel-gallery-v2]] — code-review завершён

### Идеи и бэклог
- 3 идеи готовы к запуску (readiness 100%)
- 2 идеи в проверке гипотезы

### Мои TODO
- Открытых: 3, просроченных: 1
- [[TODO-014]] — ответить команде поставщиков
"""


class TestParseDigest:
    def test_empty_string(self):
        result = parse_digest("")
        assert result["focus"] is None
        assert result["sections"] == []
        assert result["full_markdown"] is None

    def test_whitespace_only(self):
        result = parse_digest("   \n\n  ")
        assert result["focus"] is None
        assert result["sections"] == []
        assert result["full_markdown"] is None

    def test_no_sections(self):
        result = parse_digest("Just some text without sections")
        assert result["focus"] is None
        assert result["sections"] == []
        assert result["full_markdown"] == "Just some text without sections"

    def test_full_digest(self):
        result = parse_digest(SAMPLE_DIGEST)

        # Focus
        assert result["focus"] is not None
        assert result["focus"]["title"] == "Запуск keyword-search в production"
        assert "Финальное тестирование" in result["focus"]["description"]
        assert "keyword-search-prd" in result["focus"]["wikilinks"]

        # Sections count
        assert len(result["sections"]) == 3

        # Section: Производство
        prod = result["sections"][0]
        assert prod["label"] == "Производство"
        assert prod["key"] == "производство"
        assert prod["count"] == 2
        assert len(prod["items"]) == 2
        assert "keyword-search-epic" in prod["items"][0]["wikilinks"]
        assert "hotel-gallery-v2" in prod["items"][1]["wikilinks"]

        # Section: Идеи и бэклог
        ideas = result["sections"][1]
        assert ideas["label"] == "Идеи и бэклог"
        assert ideas["key"] == "идеи_бэклог"
        assert ideas["count"] == 2

        # Section: Мои TODO
        todos = result["sections"][2]
        assert todos["label"] == "Мои TODO"
        assert todos["key"] == "мои_todo"
        assert todos["count"] == 2
        assert "TODO-014" in todos["items"][1]["wikilinks"]

        # full_markdown
        assert result["full_markdown"] == SAMPLE_DIGEST

    def test_focus_only(self):
        text = "### Фокус дня\nТест фокуса\n"
        result = parse_digest(text)
        assert result["focus"] is not None
        assert result["focus"]["title"] == "Тест фокуса"
        assert result["focus"]["description"] == ""
        assert result["sections"] == []

    def test_sections_without_focus(self):
        text = "### Производство\n- item A\n- item B\n"
        result = parse_digest(text)
        assert result["focus"] is None
        assert len(result["sections"]) == 1
        assert result["sections"][0]["count"] == 2

    def test_item_with_details(self):
        text = "### Блок\n- Заголовок\n  Детали строка 1\n  Детали строка 2\n"
        result = parse_digest(text)
        item = result["sections"][0]["items"][0]
        assert item["title"] == "Заголовок"
        assert "Детали строка 1" in item["details"]
        assert "Детали строка 2" in item["details"]

    def test_wikilinks_in_items(self):
        text = "### Секция\n- [[link-a]] и [[link-b]] — описание\n"
        result = parse_digest(text)
        item = result["sections"][0]["items"][0]
        assert item["wikilinks"] == ["link-a", "link-b"]

    def test_focus_with_multiline_description(self):
        text = (
            "### Фокус дня\n"
            "Главная задача\n"
            "Подробности первые\n"
            "Подробности вторые\n"
        )
        result = parse_digest(text)
        assert result["focus"]["title"] == "Главная задача"
        assert "Подробности первые" in result["focus"]["description"]
        assert "Подробности вторые" in result["focus"]["description"]

    def test_focus_wikilinks(self):
        text = "### Фокус дня\n[[prd-123]] — запуск\nДоп. детали [[epic-5]]\n"
        result = parse_digest(text)
        assert set(result["focus"]["wikilinks"]) == {"prd-123", "epic-5"}

    def test_sections_count_equals_items_len(self):
        """count field in each section must equal len(items)."""
        result = parse_digest(SAMPLE_DIGEST)
        for section in result["sections"]:
            assert section["count"] == len(section["items"]), (
                f"Section '{section['label']}': count={section['count']} "
                f"but len(items)={len(section['items'])}"
            )

    def test_none_input(self):
        result = parse_digest(None)
        assert result["focus"] is None
        assert result["sections"] == []
        assert result["full_markdown"] is None


# ===================================================================
# _extract_section
# ===================================================================


class TestExtractSection:
    def test_extracts_section_before_next_heading(self):
        body = "\n## Alpha\nContent A\n\n## Beta\nContent B\n"
        assert _extract_section(body, "Alpha") == "Content A"

    def test_extracts_section_at_end(self):
        body = "\n## Only\nContent here\n"
        assert _extract_section(body, "Only") == "Content here"

    def test_returns_empty_for_missing_section(self):
        body = "\n## Existing\nSome text\n"
        assert _extract_section(body, "Missing") == ""

    def test_extracts_multiline_content(self):
        body = "\n## Multi\nLine 1\nLine 2\nLine 3\n\n## Next\nOther\n"
        result = _extract_section(body, "Multi")
        assert "Line 1" in result
        assert "Line 2" in result
        assert "Line 3" in result
        assert "Other" not in result

    def test_heading_with_special_chars(self):
        body = "\n## AI / LLM\nAI content\n"
        assert _extract_section(body, "AI / LLM") == "AI content"


# ===================================================================
# _parse_section — table support
# ===================================================================


class TestParseSectionTable:
    def test_parse_section_table(self):
        """Section with a markdown table parses 3 data rows."""
        body = (
            "| Домен | Эпик | Статус |\n"
            "|-------|------|--------|\n"
            "| static-metadata | Увеличение информации в Dictionary | in-progress |\n"
            "| static-metadata | Перерасчёт лейблов | in-progress |\n"
            "| booking | Новый flow бронирования | done |\n"
        )
        result = _parse_section("Производство (10 эпиков)", body)
        assert result["label"] == "Производство (10 эпиков)"
        assert result["count"] == 3
        assert len(result["items"]) == 3

        # First row
        assert result["items"][0]["title"] == "Увеличение информации в Dictionary"
        assert "static-metadata" in result["items"][0]["details"]
        assert "in-progress" in result["items"][0]["details"]

        # Third row
        assert result["items"][2]["title"] == "Новый flow бронирования"
        assert "booking" in result["items"][2]["details"]
        assert "done" in result["items"][2]["details"]

    def test_parse_section_bullets_priority(self):
        """When section has bullets, they are used even if table-like lines exist."""
        body = (
            "- Первый элемент\n"
            "- Второй элемент\n"
        )
        result = _parse_section("Тестовая секция", body)
        assert result["count"] == 2
        assert result["items"][0]["title"] == "Первый элемент"
        assert result["items"][1]["title"] == "Второй элемент"

    def test_parse_section_table_with_wikilinks(self):
        """Wikilinks inside table cells are extracted."""
        body = (
            "| Домен | Эпик | Статус |\n"
            "|-------|------|--------|\n"
            "| static-metadata | [[TMPL-15013]] Увеличение информации в Dictionary | in-progress |\n"
            "| booking | [[TMPL-16000]] Новый flow | done |\n"
        )
        result = _parse_section("Производство (2 эпика)", body)
        assert result["count"] == 2
        assert result["items"][0]["wikilinks"] == ["TMPL-15013"]
        assert result["items"][0]["title"] == "[[TMPL-15013]] Увеличение информации в Dictionary"
        assert result["items"][1]["wikilinks"] == ["TMPL-16000"]
        assert "static-metadata" in result["items"][0]["details"]
        assert "in-progress" in result["items"][0]["details"]


# ===================================================================
# parse_news
# ===================================================================


SAMPLE_NEWS = """\
---
title: "Daily news 2026-07-21"
date: 2026-07-21
type: daily-news
domain: general
tags: [daily-news, competitor-analysis, ai-llm]
source: auto-generated
---

## Конкуренты

- **[Booking.com запускает AI-консьержа](https://example.com/1)** — travelandtourworld.com
  Booking интегрирует AI-ассистента в раздел бизнес-бронирований.

- **[Expedia обновляет программу лояльности](https://example.com/2)** — skift.com
  Expedia Group анонсировала изменения в программе.

## AI / LLM

- **[Claude 4 Opus для enterprise](https://example.com/3)** — techcrunch.com
  Anthropic открыла доступ к Claude 4 Opus для корпоративных клиентов.
"""


class TestParseNews:
    def test_empty_string(self):
        result = parse_news("")
        assert result == {"categories": {"competitors": [], "ai_llm": []}}

    def test_no_frontmatter(self):
        result = parse_news("Just plain text, no frontmatter")
        assert result == {"categories": {"competitors": [], "ai_llm": []}}

    def test_wrong_type(self):
        text = "---\ntype: morning-digest\n---\n## Конкуренты\n- item\n"
        result = parse_news(text)
        assert result == {"categories": {"competitors": [], "ai_llm": []}}

    def test_missing_type(self):
        text = "---\ntitle: test\n---\n## Конкуренты\n- item\n"
        result = parse_news(text)
        assert result == {"categories": {"competitors": [], "ai_llm": []}}

    def test_full_news(self):
        result = parse_news(SAMPLE_NEWS)

        competitors = result["categories"]["competitors"]
        ai_llm = result["categories"]["ai_llm"]

        assert len(competitors) == 2
        assert len(ai_llm) == 1

        # First competitor
        assert competitors[0]["title"] == "Booking.com запускает AI-консьержа"
        assert competitors[0]["url"] == "https://example.com/1"
        assert competitors[0]["source"] == "travelandtourworld.com"
        assert "AI-ассистента" in competitors[0]["summary"]

        # Second competitor
        assert competitors[1]["title"] == "Expedia обновляет программу лояльности"
        assert competitors[1]["url"] == "https://example.com/2"
        assert competitors[1]["source"] == "skift.com"

        # AI/LLM item
        assert ai_llm[0]["title"] == "Claude 4 Opus для enterprise"
        assert ai_llm[0]["url"] == "https://example.com/3"
        assert ai_llm[0]["source"] == "techcrunch.com"
        assert "Anthropic" in ai_llm[0]["summary"]

    def test_only_competitors_section(self):
        text = (
            "---\ntype: daily-news\n---\n\n"
            "## Конкуренты\n\n"
            "- **[Title](https://example.com)** — src.com\n"
            "  Summary text.\n"
        )
        result = parse_news(text)
        assert len(result["categories"]["competitors"]) == 1
        assert len(result["categories"]["ai_llm"]) == 0

    def test_only_ai_llm_section(self):
        text = (
            "---\ntype: daily-news\n---\n\n"
            "## AI / LLM\n\n"
            "- **[AI Title](https://ai.com)** — ai-source.com\n"
            "  AI summary.\n"
        )
        result = parse_news(text)
        assert len(result["categories"]["competitors"]) == 0
        assert len(result["categories"]["ai_llm"]) == 1
        assert result["categories"]["ai_llm"][0]["title"] == "AI Title"

    def test_no_sections_in_valid_news(self):
        text = "---\ntype: daily-news\n---\nSome text without sections.\n"
        result = parse_news(text)
        assert result == {"categories": {"competitors": [], "ai_llm": []}}

    def test_summary_stripped(self):
        text = (
            "---\ntype: daily-news\n---\n\n"
            "## Конкуренты\n\n"
            "- **[Title](https://example.com)** — src.com\n"
            "  Summary with trailing spaces   \n"
        )
        result = parse_news(text)
        assert result["categories"]["competitors"][0]["summary"] == "Summary with trailing spaces"

    def test_em_dash_separator(self):
        """Test that em-dash works as source separator."""
        text = (
            "---\ntype: daily-news\n---\n\n"
            "## Конкуренты\n\n"
            "- **[Title](https://example.com)** — src.com\n"
            "  Summary.\n"
        )
        result = parse_news(text)
        assert len(result["categories"]["competitors"]) == 1
        assert result["categories"]["competitors"][0]["source"] == "src.com"

    def test_news_item_fields(self):
        """Every news item must have title, url, source, summary."""
        result = parse_news(SAMPLE_NEWS)
        required_keys = {"title", "url", "source", "summary"}
        for cat_name, items in result["categories"].items():
            for item in items:
                assert required_keys.issubset(item.keys()), (
                    f"Item in '{cat_name}' missing keys: "
                    f"{required_keys - item.keys()}"
                )

    def test_en_dash_separator(self):
        """Test that en-dash works as source separator."""
        text = (
            "---\ntype: daily-news\n---\n\n"
            "## AI / LLM\n\n"
            "- **[Title](https://example.com)** – src.com\n"
            "  Summary.\n"
        )
        result = parse_news(text)
        assert len(result["categories"]["ai_llm"]) == 1


# ===================================================================
# parse_todos
# ===================================================================


TODO_TEXT = """\
---
type: personal-todo
owner: '@igor'
---

## Открытые задачи

### [TODO-014] Level.Travel vs HotelBook
**Статус:** in-progress
**Создано:** 20.07.2026
**Срок:** до 24.07.2026
**Контекст:** Блок 2

### [TODO-016] Зафиксировать DoD
**Статус:** todo
**Создано:** 21.07.2026

### [TODO-018] Уточнить Content Amenities
**Статус:** todo
**Создано:** 21.07.2026
**Срок:** 28.07

## Закрытые задачи
"""


class TestParseTodos:
    def test_open_todos(self):
        """3 open TODO items with valid frontmatter produce 3 elements."""
        result = parse_todos(TODO_TEXT)
        assert len(result) == 3

    def test_sorting_due_date_first(self):
        """TODOs with due_date come before those without."""
        result = parse_todos(TODO_TEXT)
        # TODO-014 has due 2026-07-24, TODO-018 has due {year}-07-28,
        # TODO-016 has no due_date — must come last.
        assert result[-1]["id"] == "TODO-016"
        assert result[-1]["due_date"] is None
        # First two have due dates
        assert result[0]["due_date"] is not None
        assert result[1]["due_date"] is not None
        # First due_date <= second due_date
        assert result[0]["due_date"] <= result[1]["due_date"]

    def test_is_urgent(self, monkeypatch):
        """TODO with due_date <= 3 days from 'today' is marked urgent."""
        # Freeze today to 2026-07-22 so TODO-014 (due 24.07.2026) is within 3 days.
        fake_today = date(2026, 7, 22)
        monkeypatch.setattr("app.today_parsers.date", _FakeDate(fake_today))

        result = parse_todos(TODO_TEXT)
        todo_014 = next(t for t in result if t["id"] == "TODO-014")
        assert todo_014["is_urgent"] is True

    def test_due_date_full_format(self):
        """'24.07.2026' is parsed to '2026-07-24'."""
        result = parse_todos(TODO_TEXT)
        todo_014 = next(t for t in result if t["id"] == "TODO-014")
        assert todo_014["due_date"] == "2026-07-24"

    def test_due_date_short_format(self):
        """'28.07' (short format) is parsed to '{current_year}-07-28'."""
        result = parse_todos(TODO_TEXT)
        todo_018 = next(t for t in result if t["id"] == "TODO-018")
        current_year = str(date.today().year)
        assert todo_018["due_date"] == f"{current_year}-07-28"

    def test_invalid_frontmatter(self):
        """type != personal-todo returns empty list."""
        text = "---\ntype: meeting-notes\n---\n### [TODO-001] Test\n**Статус:** todo\n"
        result = parse_todos(text)
        assert result == []

    def test_no_frontmatter(self):
        """Text without --- delimiters returns empty list."""
        text = "### [TODO-001] Test\n**Статус:** todo\n"
        result = parse_todos(text)
        assert result == []

    def test_empty_input(self):
        result = parse_todos("")
        assert result == []

    def test_none_input(self):
        result = parse_todos(None)
        assert result == []

    def test_todo_fields_present(self):
        """Each parsed TODO must have all expected keys."""
        result = parse_todos(TODO_TEXT)
        expected_keys = {
            "id", "title", "status", "created", "due_date",
            "due_date_raw", "closed", "context", "jira", "result",
            "questions", "wikilinks", "is_urgent",
        }
        for item in result:
            assert expected_keys.issubset(item.keys()), (
                f"TODO {item.get('id')} missing keys: {expected_keys - item.keys()}"
            )

    def test_created_date_parsed(self):
        """Created date '20.07.2026' is parsed to ISO '2026-07-20'."""
        result = parse_todos(TODO_TEXT)
        todo_014 = next(t for t in result if t["id"] == "TODO-014")
        assert todo_014["created"] == "2026-07-20"

    def test_context_extracted(self):
        """Context field is extracted from TODO block."""
        result = parse_todos(TODO_TEXT)
        todo_014 = next(t for t in result if t["id"] == "TODO-014")
        assert todo_014["context"] == "Блок 2"

    def test_status_extracted(self):
        """Status field is extracted."""
        result = parse_todos(TODO_TEXT)
        todo_014 = next(t for t in result if t["id"] == "TODO-014")
        assert todo_014["status"] == "in-progress"
        todo_016 = next(t for t in result if t["id"] == "TODO-016")
        assert todo_016["status"] == "todo"

    def test_parse_todos_questions(self):
        """TODO with **Нужно ответить:** bullets extracts questions list."""
        text = (
            "---\ntype: personal-todo\n---\n\n"
            "### [TODO-030] Проработать подключение поставщиков\n"
            "**Статус:** todo\n"
            "**Создано:** 20.07.2026\n"
            "**Срок:** эта неделя (до 24.07)\n"
            "**Контекст:** По методологии K-SM-035\n"
            "**Нужно ответить:**\n"
            "- Кого подключать в 1-ю очередь — HotelBook или Level.Travel?\n"
            "- Догнать Блок 2 (live-цены) сравнения по K-SM-035.\n"
            "- Прояснить коммерческие условия и SLA доступа HotelBook.\n"
        )
        result = parse_todos(text)
        assert len(result) == 1
        todo = result[0]
        assert todo["questions"] == [
            "Кого подключать в 1-ю очередь — HotelBook или Level.Travel?",
            "Догнать Блок 2 (live-цены) сравнения по K-SM-035.",
            "Прояснить коммерческие условия и SLA доступа HotelBook.",
        ]

    def test_parse_todos_multiline_context(self):
        """TODO with multiline **Контекст:** extracts full text."""
        text = (
            "---\ntype: personal-todo\n---\n\n"
            "### [TODO-031] Задача с длинным контекстом\n"
            "**Статус:** todo\n"
            "**Создано:** 21.07.2026\n"
            "**Контекст:** По методологии K-SM-035 уже есть сравнение.\n"
            "Нужно учитывать результаты прошлого анализа.\n"
            "Также важен SLA.\n"
            "**Срок:** до 28.07\n"
        )
        result = parse_todos(text)
        assert len(result) == 1
        ctx = result[0]["context"]
        assert "По методологии K-SM-035 уже есть сравнение." in ctx
        assert "Нужно учитывать результаты прошлого анализа." in ctx
        assert "Также важен SLA." in ctx
        # Must not leak into the next field
        assert "Срок" not in ctx

    def test_parse_todos_no_questions(self):
        """TODO without **Нужно ответить:** returns questions = []."""
        result = parse_todos(TODO_TEXT)
        for todo in result:
            assert todo["questions"] == [], (
                f"TODO {todo['id']} should have empty questions list"
            )


class _FakeDate:
    """Wrapper that patches date.today() but preserves date.fromisoformat()."""

    def __init__(self, fake_today: date):
        self._fake_today = fake_today

    def today(self) -> date:
        return self._fake_today

    def fromisoformat(self, s: str) -> date:
        return date.fromisoformat(s)

    def __call__(self, *args, **kwargs):
        return date(*args, **kwargs)

    def __instancecheck__(self, inst):
        return isinstance(inst, date)


# ===================================================================
# format_todo_block
# ===================================================================


class TestFormatTodoBlock:
    def test_format_basic(self):
        """Basic block has title, status, created."""
        block = format_todo_block(
            todo_id="TODO-020",
            title="Написать тесты",
            status="todo",
            created="22.07.2026",
            due_date=None,
            context=None,
            result=None,
        )
        assert "### [TODO-020] Написать тесты" in block
        assert "**Статус:** todo" in block
        assert "**Создано:** 22.07.2026" in block
        assert "**Срок:**" not in block

    def test_format_with_due_date(self):
        """Block with due_date contains **Срок:**."""
        block = format_todo_block(
            todo_id="TODO-021",
            title="Дедлайн задача",
            status="in-progress",
            created="22.07.2026",
            due_date="до 25.07.2026",
            context="Блок 3",
            result=None,
        )
        assert "**Срок:** до 25.07.2026" in block
        assert "**Контекст:** Блок 3" in block

    def test_format_with_result(self):
        """Block with result contains **Результат:**."""
        block = format_todo_block(
            todo_id="TODO-022",
            title="Задача с результатом",
            status="done",
            created="20.07.2026",
            due_date=None,
            context=None,
            result="Выполнено успешно",
        )
        assert "**Результат:** Выполнено успешно" in block

    def test_format_all_fields(self):
        """Block with all optional fields present."""
        block = format_todo_block(
            todo_id="TODO-023",
            title="Полная задача",
            status="in-progress",
            created="21.07.2026",
            due_date="до 28.07.2026",
            context="Блок 5",
            result="Промежуточный результат",
        )
        assert "### [TODO-023] Полная задача" in block
        assert "**Статус:** in-progress" in block
        assert "**Создано:** 21.07.2026" in block
        assert "**Срок:** до 28.07.2026" in block
        assert "**Контекст:** Блок 5" in block
        assert "**Результат:** Промежуточный результат" in block

    def test_format_with_questions(self):
        """Block with questions contains **Нужно ответить:** and bullets."""
        block = format_todo_block(
            todo_id="TODO-024",
            title="Задача с вопросами",
            status="todo",
            created="22.07.2026",
            due_date=None,
            context="Контекст задачи",
            result=None,
            questions=["Первый вопрос?", "Второй вопрос?"],
        )
        assert "**Нужно ответить:**" in block
        assert "- Первый вопрос?" in block
        assert "- Второй вопрос?" in block

    def test_format_without_questions(self):
        """Block without questions has no **Нужно ответить:**."""
        block = format_todo_block(
            todo_id="TODO-025",
            title="Без вопросов",
            status="todo",
            created="22.07.2026",
            due_date=None,
            context=None,
            result=None,
        )
        assert "**Нужно ответить:**" not in block
