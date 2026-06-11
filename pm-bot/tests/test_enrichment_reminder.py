"""Tests for app.enrichment_reminder module."""

import pytest

from app.enrichment_reminder import (
    _pluralize_field,
    _get_empty_sections,
    _build_reminder_message,
)


# ---------------------------------------------------------------------------
# Helpers for building realistic markdown bodies
# ---------------------------------------------------------------------------

_ALL_SECTIONS_EMPTY = """\
## Описание идеи

### 1. Проблема / Боль
<!-- hint: опишите проблему -->

### 2. Решение
<!-- hint: опишите решение -->

### 3. Ценность (USP)
<!-- hint: уникальное торговое предложение -->

### 4. Метрика
<!-- hint: ключевая метрика -->

### 5. Сегмент (Кто)
<!-- hint: целевой сегмент -->

### 6. Job Story
<!-- hint: job story -->

### 7. In scope
<!-- hint: что входит -->

### 8. Out of scope
<!-- hint: что не входит -->

### 9. Ограничения
<!-- hint: известные ограничения -->
"""

_BLOCK1_FILLED = """\
## Описание идеи

### 1. Проблема / Боль
<!-- hint: опишите проблему -->
Пользователи теряют бронирования при смене часового пояса.

### 2. Решение
<!-- hint: опишите решение -->
Добавить автоматическую конвертацию времени на основе геолокации.

### 3. Ценность (USP)
<!-- hint: уникальное торговое предложение -->
Единственный OTA, корректно обрабатывающий timezone edge-cases.

### 4. Метрика
<!-- hint: ключевая метрика -->
Снижение обращений в поддержку по timezone на 40%.

### 5. Сегмент (Кто)
<!-- hint: целевой сегмент -->

### 6. Job Story
<!-- hint: job story -->

### 7. In scope
<!-- hint: что входит -->

### 8. Out of scope
<!-- hint: что не входит -->

### 9. Ограничения
<!-- hint: известные ограничения -->
"""

_ALL_SECTIONS_FILLED = """\
## Описание идеи

### 1. Проблема / Боль
<!-- hint: опишите проблему -->
Пользователи теряют бронирования при смене часового пояса.

### 2. Решение
<!-- hint: опишите решение -->
Добавить автоматическую конвертацию времени.

### 3. Ценность (USP)
<!-- hint: уникальное торговое предложение -->
Единственный OTA с timezone-обработкой.

### 4. Метрика
<!-- hint: ключевая метрика -->
Снижение обращений на 40%.

### 5. Сегмент (Кто)
<!-- hint: целевой сегмент -->
Международные путешественники.

### 6. Job Story
<!-- hint: job story -->
Когда я бронирую отель в другом часовом поясе, я хочу видеть время в моём поясе.

### 7. In scope
<!-- hint: что входит -->
Отели, авиабилеты.

### 8. Out of scope
<!-- hint: что не входит -->
Аренда авто, трансферы.

### 9. Ограничения
<!-- hint: известные ограничения -->
Не поддерживаем зоны с полуторачасовым сдвигом.
"""


# ---------------------------------------------------------------------------
# _pluralize_field
# ---------------------------------------------------------------------------

class TestPluralizeField:
    def test_1_pole(self):
        assert _pluralize_field(1) == "поле"

    def test_2_polya(self):
        assert _pluralize_field(2) == "поля"

    def test_5_polej(self):
        assert _pluralize_field(5) == "полей"

    def test_11_polej(self):
        assert _pluralize_field(11) == "полей"

    def test_21_pole(self):
        assert _pluralize_field(21) == "поле"

    def test_0_polej(self):
        assert _pluralize_field(0) == "полей"

    def test_14_polej(self):
        assert _pluralize_field(14) == "полей"

    def test_22_polya(self):
        assert _pluralize_field(22) == "поля"


# ---------------------------------------------------------------------------
# _get_empty_sections
# ---------------------------------------------------------------------------

class TestGetEmptySections:
    def test_all_empty(self):
        result = _get_empty_sections(_ALL_SECTIONS_EMPTY)
        assert len(result) == 9
        assert "Проблема / Боль" in result
        assert "Ограничения" in result

    def test_block1_filled(self):
        result = _get_empty_sections(_BLOCK1_FILLED)
        assert len(result) == 5
        # Filled sections must NOT appear
        assert "Проблема / Боль" not in result
        assert "Решение" not in result
        assert "Ценность (USP)" not in result
        assert "Метрика" not in result
        # Empty sections must appear
        assert "Сегмент (Кто)" in result
        assert "Job Story" in result
        assert "In scope" in result
        assert "Out of scope" in result
        assert "Ограничения" in result

    def test_all_filled(self):
        result = _get_empty_sections(_ALL_SECTIONS_FILLED)
        assert result == []

    def test_empty_body(self):
        result = _get_empty_sections("")
        assert len(result) == 9

    def test_body_with_only_comments(self):
        """Sections that contain only HTML comments count as empty."""
        body = """\
### 1. Проблема / Боль
<!-- this is just a comment -->

### 2. Решение
Real content here.
"""
        result = _get_empty_sections(body)
        assert "Проблема / Боль" in result
        assert "Решение" not in result


# ---------------------------------------------------------------------------
# _build_reminder_message
# ---------------------------------------------------------------------------

class TestBuildReminderMessage:
    def test_contains_all_fields(self):
        idea = {
            "id": "IDEA-0020",
            "title": "Timezone fix",
            "readiness": 44,
            "empty_sections": ["Сегмент (Кто)", "Job Story", "In scope"],
        }
        msg = _build_reminder_message(idea, "https://pm.example.com")
        assert "IDEA-0020" in msg
        assert "Timezone fix" in msg
        assert "44%" in msg
        assert "Сегмент (Кто)" in msg
        assert "Job Story" in msg
        assert "In scope" in msg
        assert "3" in msg  # count of sections
        assert "поля" in msg  # pluralization for 3

    def test_link_url(self):
        idea = {
            "id": "IDEA-0020",
            "title": "Test",
            "readiness": 33,
            "empty_sections": ["Метрика"],
        }
        msg = _build_reminder_message(idea, "https://pm.example.com")
        assert "https://pm.example.com/ideas.html?highlight=IDEA-0020" in msg

    def test_single_section(self):
        idea = {
            "id": "IDEA-0001",
            "title": "Solo section",
            "readiness": 88,
            "empty_sections": ["Ограничения"],
        }
        msg = _build_reminder_message(idea, "http://localhost:8080")
        assert "1" in msg
        assert "поле" in msg  # singular for 1
        assert "Ограничения" in msg

    def test_message_has_emoji(self):
        idea = {
            "id": "IDEA-0005",
            "title": "Emoji check",
            "readiness": 50,
            "empty_sections": ["Решение"],
        }
        msg = _build_reminder_message(idea, "http://localhost:8080")
        # Clipboard emoji at start and link emoji before URL
        assert "\U0001f4cb" in msg
        assert "\U0001f517" in msg
