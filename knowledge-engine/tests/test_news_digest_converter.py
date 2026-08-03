"""Tests for news_digest_converter (BL-191)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.news_digest_converter import convert_news_digest, parse_daily_news

MARKDOWN_WITH_ITEMS = '''---
title: Ежедневная новостная лента — 2026-07-31
date: 2026-07-31
type: daily-news
domain: general
tags: [#daily-news]
source: auto-generated
---

# Новостная лента за 2026-07-31

## Конкуренты

- **[Expedia acquires Layla](https://expediagroup.com/news)** — expediagroup.com
  Expedia Group купила Layla — стартап AI-планирования поездок.

- **[Agoda concert travel](https://finance.yahoo.com/agoda)** — finance.yahoo.com
  Agoda сообщила о росте поиска жилья к городам с концертами.

_По остальным игрокам новостей не найдено._

## AI / LLM

- **[Kayak AI Tools](https://stocktitan.net/kayak)** — stocktitan.net
  KAYAK for Business запустила три AI-инструмента.
'''

MARKDOWN_NO_ITEMS = '''---
title: Ежедневная новостная лента — 2026-08-01
date: 2026-08-01
type: daily-news
---

# Новостная лента за 2026-08-01

## Конкуренты

_По всем игрокам новостей не найдено._

## AI / LLM

_Значимых новостей не найдено._
'''

MARKDOWN_MULTILINE_SUMMARY = '''---
title: Test multiline
date: 2026-07-30
type: daily-news
---

# Новостная лента за 2026-07-30

## Конкуренты

- **[Big News Title](https://example.com/big)** — example.com
  Первая строка длинного описания новости.
  Вторая строка описания — более подробные детали.
  Третья строка — заключительная фраза.
'''


def _write_md(tmp_path: Path, filename: str, content: str) -> Path:
    """Helper to write markdown content to a file."""
    p = tmp_path / filename
    p.write_text(content, encoding="utf-8")
    return p


class TestParseDailyNews:
    def test_parses_items_from_markdown(self, tmp_path: Path) -> None:
        md_path = _write_md(tmp_path, "2026-07-31-news.md", MARKDOWN_WITH_ITEMS)
        result = parse_daily_news(md_path)
        assert result is not None
        assert len(result["items"]) == 3

    def test_extracts_correct_fields(self, tmp_path: Path) -> None:
        md_path = _write_md(tmp_path, "2026-07-31-news.md", MARKDOWN_WITH_ITEMS)
        result = parse_daily_news(md_path)
        assert result is not None
        first = result["items"][0]
        assert first["title"] == "Expedia acquires Layla"
        assert first["source_url"] == "https://expediagroup.com/news"
        assert first["source"] == "expediagroup.com"
        assert "Layla" in first["summary"]

    def test_extracts_date_from_frontmatter(self, tmp_path: Path) -> None:
        md_path = _write_md(tmp_path, "2026-07-31-news.md", MARKDOWN_WITH_ITEMS)
        result = parse_daily_news(md_path)
        assert result is not None
        assert result["date"] == "2026-07-31"

    def test_returns_none_for_no_items(self, tmp_path: Path) -> None:
        md_path = _write_md(tmp_path, "2026-08-01-news.md", MARKDOWN_NO_ITEMS)
        result = parse_daily_news(md_path)
        assert result is None

    def test_skips_italic_blocks(self, tmp_path: Path) -> None:
        md_path = _write_md(tmp_path, "2026-07-31-news.md", MARKDOWN_WITH_ITEMS)
        result = parse_daily_news(md_path)
        assert result is not None
        # Italic lines should not appear as items
        for item in result["items"]:
            assert not item["title"].startswith("_")
            assert "_По остальным" not in item["summary"]

    def test_multiline_summary(self, tmp_path: Path) -> None:
        md_path = _write_md(tmp_path, "2026-07-30-news.md", MARKDOWN_MULTILINE_SUMMARY)
        result = parse_daily_news(md_path)
        assert result is not None
        assert len(result["items"]) == 1
        summary = result["items"][0]["summary"]
        assert "Первая строка" in summary
        assert "Вторая строка" in summary
        assert "Третья строка" in summary

    def test_source_field_is_daily_news(self, tmp_path: Path) -> None:
        md_path = _write_md(tmp_path, "2026-07-31-news.md", MARKDOWN_WITH_ITEMS)
        result = parse_daily_news(md_path)
        assert result is not None
        assert result["source"] == "daily-news"


class TestConvertNewsDigest:
    def _setup_vault(self, tmp_path: Path, date_str: str, content: str) -> Path:
        """Set up vault structure with daily-news file."""
        news_dir = tmp_path / "wiki" / "reports" / "daily-news"
        news_dir.mkdir(parents=True)
        (news_dir / f"{date_str}-news.md").write_text(content, encoding="utf-8")
        return tmp_path

    def test_creates_json_file(self, tmp_path: Path) -> None:
        vault = self._setup_vault(tmp_path, "2026-07-31", MARKDOWN_WITH_ITEMS)
        result = convert_news_digest(str(vault), "2026-07-31")
        assert result is not None
        assert result.exists()
        assert result.name == "2026-07-31-digest.json"

        data = json.loads(result.read_text(encoding="utf-8"))
        assert "items" in data
        assert len(data["items"]) == 3

    def test_json_format_matches_moderate_news(self, tmp_path: Path) -> None:
        vault = self._setup_vault(tmp_path, "2026-07-31", MARKDOWN_WITH_ITEMS)
        result = convert_news_digest(str(vault), "2026-07-31")
        assert result is not None

        data = json.loads(result.read_text(encoding="utf-8"))
        assert "date" in data
        assert "source" in data
        assert "items" in data
        for item in data["items"]:
            assert "title" in item
            assert "summary" in item
            assert "source" in item
            assert "source_url" in item

    def test_skips_if_already_exists(self, tmp_path: Path) -> None:
        vault = self._setup_vault(tmp_path, "2026-07-31", MARKDOWN_WITH_ITEMS)
        # Create output file first
        output_dir = vault / "raw" / "inbound" / "news"
        output_dir.mkdir(parents=True)
        output_file = output_dir / "2026-07-31-digest.json"
        output_file.write_text("{}", encoding="utf-8")
        original_mtime = output_file.stat().st_mtime

        result = convert_news_digest(str(vault), "2026-07-31")
        assert result is None
        # File should not be overwritten
        assert output_file.stat().st_mtime == original_mtime

    def test_no_items_no_json(self, tmp_path: Path) -> None:
        vault = self._setup_vault(tmp_path, "2026-08-01", MARKDOWN_NO_ITEMS)
        result = convert_news_digest(str(vault), "2026-08-01")
        assert result is None
        output_path = vault / "raw" / "inbound" / "news" / "2026-08-01-digest.json"
        assert not output_path.exists()

    def test_file_not_found_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            convert_news_digest(str(tmp_path), "2099-01-01")

    def test_default_date_is_yesterday(self, tmp_path: Path) -> None:
        from datetime import date, timedelta
        yesterday = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
        vault = self._setup_vault(tmp_path, yesterday, MARKDOWN_WITH_ITEMS)

        result = convert_news_digest(str(vault))
        assert result is not None
        assert yesterday in result.name
