# PM Assistant — Changelog

Журнал изменений по всем компонентам монорепо.
Компоненты: **pm-bot**, **knowledge-engine**, **idea-pipeline**, **web-ui**.

---

## 13.06.2026 — pm-bot 1.8.0, knowledge-engine 1.7.0

### BL-119: Единый источник domain-правил
- domain-config.yaml расширен: `tags`, `keywords`, `prompt_hint` для всех 5 доменов
- `build_keyword_map()`, `build_prompt_section()`, `get_valid_domains()` — новые функции в domain_config.py (pm-bot + KE)
- `validate_domain_entry()` — валидация keywords, prompt_hint (+ tags в pm-bot)
- `set_domain()` — merge с existing записью при обновлении (защита от затирания через Web UI)
- `_SEED_DOMAIN_DATA` — полные данные 5 доменов для seed_from_defaults()
- claude_client.py: `_get_valid_domains()` с fallback на `_FALLBACK_DOMAINS`, `_build_idea_prompt()` + `_inject_domains_section()` — динамический LLM-промпт из конфига (3 стратегии: placeholder → regex → append)
- artifact_extractor.py: `_merged_keyword_map()` — config extends hardcoded `_DOMAIN_KEYWORDS`
- ingest.py: `_merged_keyword_map()` — config extends hardcoded `KEYWORD_TO_DOMAIN`
- idea.txt: убраны хардкоженные домены из JSON-шаблона и правил
- partner-search-engine теперь доступен во всех 6 точках детекции
- 30+ новых unit-тестов, 1036 passed, 0 new failures

---

## 12.06.2026 — knowledge-engine 1.6.4, pm-bot 1.7.7, web-ui 1.15.6

### BL-123: Метрики системы (self-measurement)
- Pipeline metrics: `_calculate_pipeline_metrics()` в health_scorer.py — ingest_ratio, avg_lag_hours, raw_counts
- CLI `health --json` расширен: pipeline_metrics с трендами trend_7d / trend_30d
- overview.html: секция Pipeline в health breakdown-панели (ratio %, lag, raw counts, тренды ↑↓→)
- 13 unit-тестов для _calculate_pipeline_metrics()
- Текущие значения на live vault: ratio=90.1%, lag=512.1ч, raw=513, processed=462

### BL-122: Унификация статусов идей
- Status migrator: STATUS_MAP (8 legacy → 4 канонических), VALID_STATUSES frozenset
- CLI `migrate-statuses` (--dry-run поддержка), миграция 8 файлов vault (4 draft→Новая, 3 missing→Новая, 1 enriched→Новая)
- Linter: check_invalid_idea_statuses() — валидация статусов по словарю C-0003
- pm-bot: fallback status "inbox" → "Новая" в vault_api.py
- Watcher: _SKIP_ENRICH_STATUSES расширен, fallback "inbox" → "Новая"
- 35 unit-тестов (25 migrator + 10 linter)

### BL-118: Vault health audit (закрытие)
- Vault health audit закрыт (BL-118): score 83/100, grade healthy
- Health endpoint верифицирован: broken_links 0, orphan_pages 0, dead_ends 0, stale_drafts 0
- Ingest backlog: 51 файл (17 IDEA без wiki-копий + 34 Jira-задачи) — корректная работа scorer'а, не false positive
- Unsorted misc: 13 архивных файлов в raw/inbound/misc/ — контентная задача, не баг
- BL-118 закрыт в BACKLOG.md, сводка пересчитана (реализовано: 64→65)

## 12.06.2026 — knowledge-engine 1.6.1
- Vault health audit (BL-118): score 0 → 81, grade critical → healthy
- Linter: `check_orphan_pages` переписан — проверка daily-logs и meeting-notes по дате (YYYY-MM-DD и YYYY.MM.DD), meeting-notes матчатся и против wiki/meetings/ и wiki/daily-logs/
- Linter: `_build_file_index` расширен на raw/ для поддержки wikilinks на raw-файлы
- Linter: фильтр имён людей в wikilinks, пропуск frontmatter, резолв относительных путей
- Linter: `check_unsorted_misc` — штраф за unreferenced файлы вместо возраста >7 дней
- Writer: заполнение raw file wikilink в теле идеи (шаблон {{raw_ref}})
- Vault: исправлены broken wikilinks в synthesis reports и idea files
- Vault: добавлены перекрёстные связи в 12+23 dead-end артефактах
- Vault: удалены 68 мусорных тестовых артефактов из wiki/domains/general/

## 08.06.2026 — pm-bot 1.7.3
- Daily alert: пропуск проверки в субботу и воскресенье (weekend exclusion)
- Проверка `today.weekday() >= 5` в начале `run_daily_alert()` — логирует "skipping weekend" и завершается

## 07.06.2026 — pm-bot 1.7.2, knowledge-engine 1.5.1, web-ui 1.15.4
- Jira Sync Notify Toggle: настройка ON/OFF уведомлений после Jira sync через Web UI Settings
- Новая user-pref `jira_sync_notify` в vault API + двойная проверка (vault_api.py + fetcher.py)
- Рефакторинг settings.html: единая функция `buildPrefsPayload()` предотвращает потерю полей при сохранении
- Daily Alert: автоматическая проверка наличия Daily-протокола в 18:00 МСК
- Новый модуль `daily_alert.py`: проверка wiki/daily-logs/ на файлы YYYY.MM.DD-*-Daily-summary.md
- APScheduler job `daily_alert` с настройкой через env DAILY_ALERT_HOUR / DAILY_ALERT_MINUTE
- knowledge-engine: `_should_notify()` в fetcher.py — чтение user-prefs из shared vault volume

## 29.05.2026 — pm-bot 1.7.0, knowledge-engine 1.5.0
- Команда /progress: отправка ежедневного отчёта о ходе проекта в Telegram (файл-вложение .md + HTML-caption с блокерами/рисками)
- Поддержка даты: /progress DD.MM.YYYY или без аргумента (последний отчёт)
- Меню команд бота: 14 команд в Telegram UI через set_my_commands (post_init)

## 29.05.2026 — pm-bot 1.6.0, knowledge-engine 1.5.0
- Daily Jira Sync: извлечение Jira-ключей из daily-протоколов (Telegram + email)
- Авто-импорт: задачи, упомянутые в daily, но отсутствующие в vault, импортируются из Jira автоматически
- Перекрёстные ссылки: ключи в секции «Упомянутые задачи» заменяются на Obsidian wiki-links (`[[wiki/domains/{domain}/{type}/{KEY}|{KEY}]]`)
- Двухуровневое извлечение: LLM-секция + regex safety net (надёжно при Claude и Ollama Qwen 3.5)
- Новый модуль: knowledge-engine/app/jira_key_sync.py (extract, vault check, import, patch)
- Промпты: секция «Упомянутые задачи» добавлена в daily.txt и meeting_protocol.txt
- Оба пайплайна: handle_text/handle_voice (pm-bot) + fetch_new_meetings (knowledge-engine)

## 28.05.2026 — web-ui 1.15.6
- Board: классификация задач по полю jira_key вместо type (K-GEN-001 §1)
- Board: внутренние задачи отображают тип из frontmatter — BACKEND, FRONTEND, TESTING, RESEARCH, DESIGN (K-GEN-001 §4)
- Board: задачи в статусе done/cancelled перенесены из PROCESSING в DONE
- Board: fallback-тип переименован NOTE → TASK

## 28.05.2026 — web-ui 1.15.5
- Board: файлы IDEA-* отфильтрованы из доски — идеи отображаются только на ideas.html

## 28.05.2026 — web-ui 1.15.4
- Формат дат DD.MM.YYYY на всех оставшихся страницах: timeline, roadmap, dashboard, report
- fmtDate() добавлена локально в timeline.html, roadmap.html, dashboard.html; formatDate() переписана в report.html

## 27.05.2026 — web-ui 1.15.3
- Даты на карточках и в drawer приведены к формату DD.MM.YYYY (was YYYY-MM-DD)
- Глобальная функция fmtDate() в components.js, подключена в note-card, idea-card, task-drawer, idea-drawer

## 27.05.2026 — pm-bot 1.5.4
- Исправлено: parse_note() — дата извлекалась некорректно для файлов с форматом YYYYMMDD в имени (IDEA-001..IDEA-018 показывали мусор вместо даты)
- Цепочка приоритетов: date из frontmatter → YYYY-MM-DD из имени → YYYYMMDD из имени → created из frontmatter
- Затронуто 20 идей

## 27.05.2026 — pm-bot 1.5.3
- Исправлено: parse_note() не снимала кавычки с YAML-значений frontmatter — id отображался как "IDEA-0022" вместо IDEA-0022
- Затронуто 6 идей (IDEA-0021..IDEA-0026)

## 27.05.2026 — web-ui 1.15.2
- About: даты в CHANGES.md переведены из YYYY-MM-DD в DD.MM.YYYY в исходных файлах
- About: удалена runtime-конвертация дат в about.html, обновлён regex парсинга версий

## 25.05.2026 — pm-bot 1.5.2
- Исправлено: BUG-001 — `write_daily()` не добавляла запись в wiki/LOG.md после сохранения дейли
- Исправлено: `write_meeting()` — аналогичная проблема, запись в LOG.md отсутствовала
- Новые функции: `_build_daily_log_entry()`, `_build_meeting_log_entry()`, `_append_wiki_root_log()`
- Дата в лог-записи извлекается из имени файла (надёжный источник), не из frontmatter (может быть галлюцинацией LLM)
- Фильтр тегов: добавлен `daily-log` в исключения при парсинге доменов

## 25.05.2026 — knowledge-engine 1.4.2
- Исправлено: BUG-002 — `fetch_new_meetings()` не добавлял запись в wiki/LOG.md после обработки транскрибации из почты
- Новая функция: `_build_fetcher_log_entry()` — парсинг даты, доменов и summary из протокола
- Lazy import `_append_root_log` из ingest.py, non-critical side effect

## 23.05.2026 — pm-bot 1.5.1
- Исправлено: handlers.py — Telegram Markdown parse error при отправке jira-ответа (fallback на plain text)
- Исправлено: оба пути (text + voice) для jira reply

## 23.05.2026 — knowledge-engine 1.4.1
- Исправлено: vault_index.py — None в tags/keywords вызывал AttributeError при search (фильтрация None перед .lower())

## 23.05.2026 — web-ui 1.15.1
- Settings: исправлен TEST CONNECTION — silent early return при пустом URL, теперь показывает ошибку
- Settings: исправлено имя поля ollama_version (было version) в отображении статуса

## 22.05.2026 — pm-bot 1.5.0
- Гибридная LLM-архитектура: Claude API / Ollama / Hybrid mode
- llm_client.py: фабрика клиентов, маршрутизация по операциям, fallback Ollama → Claude
- claude_client.py: интеграция с llm_client (idea, meeting, jira_ticket, daily)
- reporter.py: интеграция с llm_client (weekly_report)
- vault_api.py: расширение UserPrefs (llm_provider, ollama_url, ollama_model), endpoint POST /test-ollama

## 22.05.2026 — knowledge-engine 1.4.0
- Гибридная LLM-архитектура: Claude API / Ollama / Hybrid mode
- llm_client.py: фабрика клиентов, маршрутизация, fallback Ollama → Claude
- claude_client.py: интеграция с llm_client (enrich, synthesize, meeting_protocol)

## 22.05.2026 — web-ui 1.15.0
- Settings: секция LLM Provider — переключение CLAUDE API / OLLAMA / HYBRID
- Settings: поля Ollama URL, Ollama Model, кнопка TEST CONNECTION
- Settings: статус подключения (зелёный/красный), информационная панель Hybrid-маршрутизации
- api.js: метод testOllama()

## 15.05.2026 — web-ui 1.13.0
- Jira Sync UI: sync status card на dashboard (domain-card стиль, 5 метрик, overdue alert >3ч)
- Jira Sync UI: кнопка SYNC NOW на settings с loading state и результатом
- Rename: domains.html → dashboard.html
- API: POST /api/v1/jira/sync, GET /api/v1/jira/sync-status

## 15.05.2026 — web-ui 1.12.0
- Jira Sync UI: 6 metric-box карточек синхронизации на domains.html
- Jira Sync UI: SYNC NOW кнопка в секции JIRA_SYNC на settings.html
- API: два новых endpoint в vault_api.py (jira/sync, jira/sync-status)
- api.js: методы jiraSync(), jiraSyncStatus()

## 14.05.2026 — web-ui 1.11.0
- Исправлено: BUG-009 — Overview не применяет light-тему
- Исправлено: BUG-010 — Карточки без стилизации в light-теме

## 14.05.2026 — web-ui 1.10.0
- Dashboard: метрики (metrics-grid) перемещены над карточками доменов
- Dashboard: seed-banner перемещён вниз под карточки доменов
- Dashboard: формат даты last_activity приведён к DD.MM.YYYY
- Sidebar: новый порядок меню, переименование, Material Icons, Overview скрыт

## 14.05.2026 — web-ui 1.9.3
- Прогресс-бары: DS-палитра (ink-700 / amber-500 / green-500)

## 14.05.2026 — web-ui 1.9.2
- Ideas: сортировка колонки «Новая» по % проработки (от максимума к минимуму)

## 14.05.2026 — web-ui 1.9.1
- Metric cards: акцентная полоса сверху карточки (::before с цветом по типу метрики)
- Прогресс-бары: приведены к DS §10 (4px track, 2px radius, без рамки)

## 14.05.2026 — web-ui 1.9.0
- Sidebar: рестайлинг по DS §09 (16px лого, 14px навигация, 8px radius, active с 3px left border)
- Metric cards: рестайлинг по DS §10 (16px radius, 20px padding, 30px value, pill delta badges)
- Timeline: рестайлинг по DS §17 (16px radius карточки, тёплая палитра точек, 2px border dot)

## 14.05.2026 — web-ui 1.8.0
- Column headers: приведены к DS §21 на всех страницах (board, ideas, roadmap)
- Capture Terminal: рестайлинг по DS §19 (16px radius, surface header, cream bubbles, DS tabs)
- Task/Idea Drawer: рестайлинг по DS §20 + §22 (16px radius, секционное тело, meta grid, markdown типографика)
- Карточки: рестайлинг по DS §21 (clip-path:none, border-radius:12px, вертикальный акцент, cursor:grab)
- Green WCAG AA: #7A8B6A → #5F7A4A (контраст 3.5:1 → 5.3:1)

## 14.05.2026 — web-ui 1.7.1
- Исправлено: BUG-009 — Overview не применяет light-тему (inline styles override через .theme-light specificity)
- Исправлено: BUG-010 — Карточки без стилизации в light-теме (перенос structural styles .card-clip в style.css)
- 7 улучшений контрастности: тени карточек, card-accent 3px, swim lanes, drop-shadow, hover-состояния

## 14.05.2026 — web-ui 1.7.0
- Светлая тема LIGHT: cream/warm палитра, CSS-переменные, style-light.css
- Dual-theme: переключение MATRIX ↔ LIGHT через settings.html

## 13.05.2026 — pm-bot 1.4.1
- Исправлено: capture endpoint — import _fallback_idea_data + dict→JSON serialization

## 13.05.2026 — knowledge-engine 1.3.1
- Исправлено: BUG-008 — raw transcript не сохранялся при успешной обработке

## 13.05.2026 — web-ui 1.6.0
- Overview dashboard: system status, idea funnel, today's queue, activity feed, quick capture
- Overview redesign: панели, KPI-метрики, donut chart

## 12.05.2026 — pm-bot 1.4.0
- Vault API: in-memory TTL cache (30s) с invalidation и warm-on-startup
- Performance: /system/status 4882ms → 4ms, /domains 4891ms → 7ms
- User preferences API (GET/PUT /api/v1/user-prefs)

## 12.05.2026 — knowledge-engine 1.3.0
- Meeting fetcher: IMAP клиент, классификация транскриптов, автообработка
- Domain manager: scaffold, index, activity log

## 12.05.2026 — web-ui 1.5.0
- Drag-n-drop для идей между колонками
- Правила перехода: R1 (readiness 100% для «Готова»), R2 (warning < 44% для «Проверка гипотезы»)
- Toast-уведомления и warning modal

## 11.05.2026 — pm-bot 1.3.0
- Enrichment reminders: daily cron, SQLite cooldown 24ч, Telegram-уведомления
- Scheduler: APScheduler для weekly report и enrichment reminders

## 11.05.2026 — knowledge-engine 1.2.0
- Jira create: создание тикетов из vault
- Jira import: импорт единичного тикета по ключу

## 11.05.2026 — web-ui 1.4.0
- Capture drawer: 4 типа (idea, task, meeting, jira_import)
- Readiness % в карточках идей
- Domain filter tabs

## 10.05.2026 — pm-bot 1.2.0
- Speech-to-Text: faster-whisper, lazy import, env STT_ENABLED
- Pipeline client: HTTP-клиент к idea-pipeline API

## 10.05.2026 — web-ui 1.3.0
- Канбан идей: 4 колонки по статусам
- Idea drawer с markdown-рендерингом
- Auto-refresh (30s) / manual mode

## 09.05.2026 — pm-bot 1.1.0
- Vault API (FastAPI): REST endpoints для web UI
- Web UI static file server (порт 8080)

## 09.05.2026 — knowledge-engine 1.1.0
- Jira sync: регулярная синхронизация (cron 3ч), diff state, domain detection
- Vault index: сканирование, in-memory индекс, keyword matching

## 09.05.2026 — web-ui 1.2.0
- Roadmap с эпиками и прогрессом
- Timeline по фичам
- Report viewer (markdown → HTML)

## 08.05.2026 — idea-pipeline 1.1.0
- Inline prompt: настраиваемые промпты через pipeline.yaml
- API key аутентификация

## 08.05.2026 — web-ui 1.1.0
- Канбан-доска задач (board.html)
- Settings страница (тема, refresh mode)
- Domains страница

## 07.05.2026 — pm-bot 1.0.0
- Telegram-бот: /idea, /jira, /daily, /start
- Claude API интеграция
- Obsidian writer
- Transcript watcher (watchdog)

## 07.05.2026 — knowledge-engine 1.0.0
- Enricher: обогащение идей связями из vault
- Synthesizer: кластеризация + сводка
- Watcher: auto-enrichment на Inbox/
- Linter: линтер vault-файлов

## 07.05.2026 — idea-pipeline 1.0.0
- Orchestrator: Analyst → PM → Decomposer
- FastAPI endpoints (5 endpoints)
- Configurable models per agent
- Vault writer с frontmatter

## 07.05.2026 — web-ui 1.0.0
- Первый релиз web-дашборда
- Sidebar навигация
- Базовая matrix-тема
