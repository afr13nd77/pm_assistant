# BL-191 — News Digest Converter — Tasks

**Дата:** 03.08.2026
**Статус:** done

---

## Задачи

```
T-01 [opus] — Парсер markdown → JSON + CLI subparser + тесты
  Traces to: US-01, AC-01..AC-05
  Files: knowledge-engine/app/news_digest_converter.py (new),
         knowledge-engine/app/cli.py (modify),
         knowledge-engine/tests/test_news_digest_converter.py (new)
  Task: Создать модуль parse_daily_news + convert_news_digest,
        добавить CLI subparser convert-news-digest, написать тесты
  Context: Markdown из wiki/reports/daily-news/, JSON в raw/inbound/news/
  Depends on: none
  Verify: pytest knowledge-engine/tests/test_news_digest_converter.py -x -v
  Live test: python -c "from app.news_digest_converter import parse_daily_news; ..."
             с реальным 2026-07-31-news.md (6 items)
  Status: [✓] done (03.08.2026) — 13 тестов пройдено

T-02 [team-lead] — Cron job + документация проекта
  Traces to: Out of scope (cron setup — отдельная задача)
  Files: docker-compose.yml, BACKLOG.md, CHANGELOG.md, index.md
  Task: Добавить ke-convert-news cron (07:55 Пн-Пт, перед moderate-news 08:00),
        обновить документацию
  Depends on: T-01
  Verify: docker-compose config
  Status: [✓] done (03.08.2026)
```
