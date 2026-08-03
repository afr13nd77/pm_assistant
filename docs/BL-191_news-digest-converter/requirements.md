# BL-191 — News Digest Converter

## Phase 1 — Requirements

**Дата:** 03.08.2026
**Автор:** Team Lead
**Статус:** approved

---

## 1.1 Overview

Новости собираются ежедневно из Claude Desktop cowork в markdown (`wiki/reports/daily-news/YYYY-MM-DD-news.md`). Signal Moderator (BL-189) ожидает JSON-дайджест в `raw/inbound/news/`. Конвертер парсит markdown и создаёт JSON — мост между сбором и анализом.

## 1.2 User Stories

```
US-01: Как владелец системы, я хочу чтобы daily-news markdown
       автоматически конвертировался в JSON-дайджест,
       чтобы moderate-news мог обрабатывать собранные новости.
```

## 1.3 User Flow

```
FLOW-01: Конвертация
1. CLI: convert-news-digest [--date YYYY-MM-DD] [--vault PATH]
2. Если --date не указан → вчерашняя дата
3. Найти wiki/reports/daily-news/{date}-news.md
   → NOT FOUND: stderr "News file not found: {path}", exit 1
4. Парсить markdown:
   a. Frontmatter → date
   b. Секции ## → category
   c. Для каждой новости:
      - **[title](url)** — source → title, source_url, source
      - Текст на следующей строке → summary
   d. Пропустить _курсивные_ блоки (нет новостей)
5. Если items == 0 → лог "no items found", exit 0 (не создавать JSON)
6. Если raw/inbound/news/{date}-digest.json уже есть → лог "already exists, skip", exit 0
7. Записать JSON в raw/inbound/news/{date}-digest.json
8. Лог "Converted: {count} items → {path}"
```

## 1.4 Acceptance Criteria

```
AC-01 (US-01):
  GIVEN: daily-news markdown с 2+ новостями в секциях Конкуренты и AI/LLM
  WHEN: convert-news-digest --date YYYY-MM-DD
  THEN: создаётся JSON в raw/inbound/news/{date}-digest.json
        AND каждый item содержит title, summary, source, source_url
        AND JSON.date == дата из frontmatter
        AND JSON.source == "daily-news"

AC-02 (US-01):
  GIVEN: daily-news markdown без новостей (только _курсивные_ блоки)
  WHEN: convert-news-digest запускается
  THEN: JSON не создаётся
        AND лог "no items found"
        AND exit code 0

AC-03 (US-01):
  GIVEN: JSON-дайджест для этой даты уже существует
  WHEN: convert-news-digest запускается
  THEN: существующий файл не перезаписывается
        AND лог "already exists"
        AND exit code 0

AC-04 (US-01):
  GIVEN: --date 2026-07-31 указан явно
  WHEN: convert-news-digest запускается
  THEN: парсит именно wiki/reports/daily-news/2026-07-31-news.md

AC-05 (US-01):
  GIVEN: файл daily-news для указанной даты не существует
  WHEN: convert-news-digest запускается
  THEN: stderr "News file not found"
        AND exit code 1
```

## 1.5 Out of Scope

- LLM-обработка (чистый парсинг regex/string)
- Изменение формата daily-news markdown
- Обратная конвертация JSON → markdown
- Cron setup (отдельная задача)

## 1.6 Dependencies

| Зависимость | Тип | Статус |
|---|---|---|
| BL-189 (News Moderator) | JSON формат | ✅ |
| Claude Desktop cowork | Markdown source | ✅ |

## Markdown формат (reference)

```markdown
---
title: Ежедневная новостная лента — 2026-07-31
date: 2026-07-31
type: daily-news
---

## Конкуренты

- **[Title here](https://example.com/url)** — source.com
  Summary text on next line(s) until next item or section.

_По остальным ... новостей не найдено._

## AI / LLM

- **[Another title](https://example.com)** — source2.com
  Another summary.
```

## JSON формат (output)

```json
{
  "date": "2026-07-31",
  "source": "daily-news",
  "items": [
    {
      "title": "Title here",
      "summary": "Summary text on next line(s)...",
      "source": "source.com",
      "source_url": "https://example.com/url"
    }
  ]
}
```
