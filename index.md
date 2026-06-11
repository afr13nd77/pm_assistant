# PM Assistant — Project Index

## Монорепо структура

```
pm_assistant/
├── .env                            # общие секреты (не коммитить)
├── .env.example                    # шаблон переменных
├── docker-compose.yml              # оркестрация: pm-bot (shm_size 512m) + knowledge-engine + ke-cron + idea-pipeline
├── CHANGELOG.md                    # журнал изменений по всем компонентам (от новых к старым)
├── BACKLOG.md                      # бэклог: реализованные фичи (54), баги (18), идеи (27)
│
├── docs/                           # спеки и дизайн-документы (корень монорепо)
│   ├── jira-polling/               # requirements.md, design.md, tasks.md
│   ├── jira-import/                # requirements.md
│   ├── knowledge-engine/           # requirements.md, design.md, tasks.md
│   ├── idea-pipeline/              # requirements.md, design.md, tasks.md
│   ├── voice-messages/             # requirements.md, design.md, tasks.md
│   ├── meeting-fetcher/            # requirements.md, design.md, tasks.md
│   ├── pm-web-ui/                  # SPEC, screens, tasks
│   ├── task-lifecycle/             # requirements.md
│   ├── pipeline-inline-prompt/     # requirements.md, tasks.md
│   ├── refresh-mode/               # requirements.md, design.md, tasks.md
│   ├── ollama-hybrid/              # requirements.md, design.md, tasks.md
│   └── architecture/adr/           # 4 ADR (решения по архитектуре)
│
├── pm-bot/                         # Telegram-бот (capture)
│   ├── Dockerfile                  # образ Python 3.12-slim + knowledge-engine
│   ├── requirements.txt            # 4 зависимости
│   ├── CLAUDE.md                   # инструкции для Claude Code
│   ├── CONTEXT.md                  # история проектных решений
│   └── app/                        # исходный код
│       ├── __init__.py
│       ├── main.py                 # точка входа: запуск бота + watcher
│       ├── handlers.py             # Telegram: /start, /idea, /jira, /daily, /synthesize, /jira_sync, /jira_import, /jira_create, /pipeline, /domain, /lint, /status, /test_enrichment, текст, голос
│       ├── claude_client.py        # Claude/Ollama: process_idea (→dict/JSON), process_meeting, process_jira_ticket, process_daily (через llm_client)
│       ├── llm_client.py           # фабрика LLM-клиентов: Claude API / Ollama / Hybrid, fallback
│       ├── obsidian_writer.py      # запись .md: write_idea (template-based), write_meeting, write_jira_draft, write_daily, write_report
│       ├── pipeline_client.py      # HTTP-клиент к idea-pipeline API
│       ├── reporter.py             # генерация еженедельных отчётов через Claude
│       ├── scheduler.py            # APScheduler: weekly_report (Mon 09:00), enrichment_reminder (daily, configurable), daily_alert (пн-пт 18:00)
│       ├── stt.py                  # Speech-to-Text (faster-whisper, lazy import, env STT_ENABLED)
│       ├── transcript_watcher.py   # watchdog: транскрипты .txt → Meetings/
│       ├── vault_api.py            # FastAPI REST сервер: vault API + user-prefs API + capture + test-ollama + in-memory TTL cache
│       ├── vault_paths.py          # централизованная логика путей vault (+ user_prefs_path)
│       ├── domain_config.py        # загрузка/сохранение domain-config.yaml
│       ├── file_writer.py          # atomic file write
│       ├── enrichment_reminder.py  # ЖЦ идей: скан по доменам, readiness %, Telegram-напоминания
│       ├── enrichment_db.py        # SQLite: дедупликация напоминаний (cooldown 24ч, cleanup 90д)
│       ├── daily_alert.py          # Alert при отсутствии Daily-протокола (cron 18:00 МСК, пн-пт, weekend skip)
│       └── prompts/                # 5 промптов (idea, meeting, jira_ticket, daily, weekly_report)
│   └── web/                        # SPA веб-дашборд (Vue 3 + vanilla JS)
│       ├── index.html              # redirect → overview.html
│       ├── overview.html           # дашборд: system status, idea funnel, today's queue, activity feed, quick capture
│       ├── board.html              # канбан-доска (auto-refresh 30s / manual + refresh icon)
│       ├── ideas.html              # канбан идей по статусам + capture drawer (4 типа) + readiness %
│       ├── dashboard.html           # домены, статистика артефактов, Jira sync status
│       ├── roadmap.html            # roadmap с эпиками (auto-refresh 60s / manual + refresh icon)
│       ├── timeline.html           # таймлайн фич
│       ├── report.html             # просмотр отчётов (marked.js для MD)
│       ├── settings.html           # настройки (theme, refresh mode, prompts, Jira sync)
│       ├── api.js                  # fetch-клиент к vault_api (cancellation, caching, user-prefs)
│       ├── components.js           # shared Vue 3 компоненты (sidebar, cards, drawer)
│       ├── style.css               # базовая тема (flat)
│       ├── style-matrix.css        # matrix тема (glow, neon)
│       ├── style-light.css         # light тема (cream, warm)
│       └── tests/                  # Node.js unit-тесты для страниц
│           ├── test-report-node.js
│           ├── test-components-node.js
│           ├── test-api-node.js
│           └── test-roadmap-node.js
│
├── knowledge-engine/               # сервис обогащения и синтеза
│   ├── Dockerfile                  # образ Python 3.12-slim
│   ├── requirements.txt            # 5 зависимостей
│   └── app/                        # исходный код
│       ├── __init__.py
│       ├── __main__.py             # точка входа: python -m app
│       ├── cli.py                  # CLI: jira-sync, jira-import, jira-create, jira-projects, jira-epics, jira-issue-types, enrich, synthesize, watch, index, lint, status
│       ├── enricher.py             # обогащение идеи связями из vault
│       ├── synthesizer.py          # синтез: кластеризация + сводка
│       ├── vault_index.py          # сканирование vault, in-memory индекс
│       ├── vault_paths.py          # централизованная логика путей vault
│       ├── domain_manager.py       # управление доменами: scaffold, index, log
│       ├── matcher.py              # keyword + tag matching
│       ├── claude_client.py        # Claude API для enrichment/synthesis
│       ├── llm_client.py           # фабрика LLM-клиентов: Claude API / Ollama / Hybrid, fallback
│       ├── frontmatter_utils.py    # чтение/запись YAML frontmatter
│       ├── file_writer.py          # atomic write (tmp + os.replace)
│       ├── notifier.py             # Telegram уведомления через Bot API
│       ├── watcher.py              # watchdog: Inbox/ → auto-enrichment
│       ├── artifact_extractor.py   # извлечение артефактов
│       ├── linter.py               # линтер vault-файлов
│       ├── process_one.py          # обработка одного файла
│       ├── domain_config.py        # загрузка/сохранение domain-config.yaml
│       ├── jira_fetcher/           # модуль синхронизации с Jira
│       │   ├── __init__.py
│       │   ├── client.py           # Jira REST API v2 client (Bearer PAT auth): get_projects, get_project_issue_types, get_project_epics, create_issue, search
│       │   ├── state.py            # .jira-sync-state.json — отслеживание состояния
│       │   ├── mapper.py           # Jira issue → Markdown с frontmatter + domain detection
│       │   └── fetcher.py          # оркестратор: fetch → diff → write → log → notify
│       ├── meeting_fetcher/        # модуль импорта транскриптов из email
│       │   ├── __init__.py
│       │   ├── imap_client.py      # IMAP клиент для почты
│       │   ├── classifier.py       # классификация транскриптов
│       │   ├── fetcher.py          # оркестратор: fetch → save raw → Claude → classify → write wiki → enrich → notify
│       │   └── state.py            # состояние последнего fetch
│       └── prompts/                # 3 промпта (enrich, synthesize, meeting_protocol)
│
└── idea-pipeline/                  # сервис проработки идей (orchestrator)
    ├── Dockerfile                  # образ Python 3.12-slim + knowledge-engine
    ├── requirements.txt            # 7 зависимостей
    ├── pipeline.yaml               # конфигурация агентов (модели, таймауты)
    └── app/                        # исходный код (11 файлов)
        ├── __init__.py
        ├── __main__.py             # точка входа: serve, run, status
        ├── api.py                  # FastAPI endpoints (5 endpoints)
        ├── orchestrator.py         # pipeline orchestration: Analyst → PM → Decomposer
        ├── claude_client.py        # Claude API с configurable model per agent
        ├── config.py               # загрузка pipeline.yaml + env overrides
        ├── state.py                # PipelineRun, PipelineStore (in-memory + _state.json)
        ├── vault_writer.py         # запись артефактов в vault с frontmatter
        ├── models.py               # Pydantic models для API
        ├── auth.py                 # API key middleware
        ├── agents/
        │   ├── base.py             # BaseAgent
        │   ├── analyst.py          # AnalystAgent (идея + vault context → analysis)
        │   ├── pm_agent.py         # PMAgent (analysis → PRD)
        │   └── decomposer.py       # DecomposerAgent (PRD → Epic + Tasks JSON)
        └── prompts/
            ├── analyst.txt
            ├── pm.txt
            └── decomposer.txt
```

## Версии компонентов

| Компонент | Версия | Последнее изменение | Описание |
|---|---|---|---|
| **pm-bot** | 1.7.4 | 2026-06-11 | Telegram-бот + Web UI + Vault API. Гибридная LLM-архитектура. Daily Jira Sync. /progress. Меню команд. Jira sync notify toggle. Daily alert (пн-пт). Health popup layout fix (BUG-016) |
| **knowledge-engine** | 1.5.2 | 2026-06-11 | Enrichment, synthesis, Jira sync, meeting fetch, daily Jira key sync. Гибридная LLM-архитектура. Health false positives fix: _is_ignorable_link, jira_key exclusion (BUG-017) |
| **idea-pipeline** | 1.1.0 | 2026-05-08 | Orchestrator: Analyst → PM → Decomposer |
| **web-ui** | 1.15.5 | 2026-06-11 | Dual-theme SPA дашборд. Health popup light-тема: .theme-light CSS specificity, theme-aware JS colors (BUG-016) |

Схема: semver `MAJOR.MINOR.PATCH`. MAJOR — ломающие изменения API/контрактов. MINOR — новый функционал. PATCH — багофиксы.

## Стек и зависимости

| Зависимость | Версия | Сервис |
|---|---|---|
| Python | 3.12 | все |
| python-telegram-bot | 21.5 | pm-bot |
| anthropic | >=0.40.0 (pm-bot), >=0.97.0 (KE) | pm-bot, knowledge-engine |
| watchdog | 4.0.1 (pm-bot), 6.0.0 (KE) | pm-bot, knowledge-engine |
| python-dotenv | 1.0.1 (pm-bot), 1.2.2 (KE) | pm-bot, knowledge-engine |
| python-frontmatter | >=1.1.0 | knowledge-engine, idea-pipeline |
| requests | >=2.31.0 | knowledge-engine |
| FastAPI | >=0.111.0 (pm-bot), >=0.115.0 (pipeline) | pm-bot, idea-pipeline |
| uvicorn | >=0.30.0 (pm-bot), >=0.32.0 (pipeline) | pm-bot, idea-pipeline |
| python-slugify | >=8.0.0 | idea-pipeline |
| Claude модель | claude-sonnet-4-6 | pm-bot, knowledge-engine, idea-pipeline |
| marked.js | 15.x (CDN) | pm-bot (web) |
| Vue.js | 3.x (CDN) | pm-bot (web) |
| faster-whisper | >=1.0.0 | pm-bot |
| apscheduler | >=3.10.4 | pm-bot |
| Docker Compose | v3.9 | инфраструктура |

## Потоки данных

1. **Идеи**: Telegram/Web capture → handlers → claude_client.process_idea (→JSON dict) → obsidian_writer.write_idea (template-based: templates/idea.md → fill frontmatter + Block 1) → `raw/inbound/ideas/IDEA-NNNN-*.md` + `wiki/domains/<domain>/ideas/` → knowledge-engine enrich
2. **Транскрипты**: `.txt` → transcript_watcher → claude_client.process_meeting → obsidian_writer.write_meeting → `/vault/Meetings/*.md`
3. **Jira-тикеты**: Telegram `/jira` → handlers.handle_text → claude_client.process_jira_ticket → obsidian_writer.write_jira_draft → `/vault/Tasks/Drafts/*.md`
4. **Синтез**: Telegram `/synthesize` или cron → knowledge-engine synthesize → `/vault/Projects/synthesis-*.md`
5. **Auto-enrichment**: watchdog на Inbox/ → knowledge-engine enrich (для файлов созданных вне бота)
6. **Idea Pipeline**: Telegram `/pipeline` или API → idea-pipeline orchestrator → Analyst → PM → Decomposer → `/vault/Pipeline/<date>-<slug>/` (analysis.md, PRD.md, epic.md, tasks/*.md)
7. **Jira Sync** (cron каждые 3ч или /jira_sync): knowledge-engine jira-sync → fetch JQL → diff state → write `wiki/domains/<domain>/tasks/<key>.md` + `raw/inbound/tasks/<key>.md` → append domain log.md → update `.jira-sync-state.json` → Telegram notify
8. **Jira Import** (ручной /jira_import <KEY>): knowledge-engine jira-import → fetch single issue → write to wiki/ + raw/ → update state
9. **Enrichment Reminders** (daily cron или /test_enrichment): enrichment_reminder.py → scan wiki/domains/*/ideas/*.md → filter by active status + readiness < 100% → check SQLite cooldown → send Telegram reminder с незаполненными секциями + ссылка на ideas.html

## Docker-топология

| Контейнер | Роль | Команда |
|---|---|---|
| pm-bot | Telegram polling + capture + vault API (8000) + web UI (8080) | python -m http.server 8080 --directory /web & python -m app.main |
| knowledge-engine | Watchdog на Inbox/ для auto-enrichment | python -m app watch |
| idea-pipeline | Orchestrator: Analyst → PM → Decomposer | python -m idea_pipeline serve |
| ke-cron | Синтез (09:00) + Jira sync (каждые 3ч) | crond |

## Web UI

Статические HTML-страницы (`pm-bot/web/`) раздаются через `python -m http.server` на порту 8080.
Данные получают из vault_api (FastAPI, порт 8000) через `api.js`.

| Страница | Назначение |
|---|---|
| index.html | Redirect → overview.html |
| overview.html | Дашборд: system status, idea funnel, today's queue, activity feed, quick capture |
| ideas.html | Канбан идей: 4 колонки по статусам, фильтр по доменам, capture drawer, readiness % |
| board.html | Канбан-доска задач |
| dashboard.html | Домены, статистика артефактов, Jira sync status (overdue alert) |
| roadmap.html | Roadmap с эпиками и прогрессом |
| timeline.html | Таймлайн по фичам |
| report.html | Просмотр еженедельных отчётов (Markdown → HTML через marked.js) |
| settings.html | Настройки: тема, refresh mode, LLM Provider (Claude/Ollama/Hybrid + Test Connection), prompts, Jira sync |
| about.html | О сервисе: версии компонентов, история изменений (CHANGES.md → marked.js) |

**Тема**: dual-theme — MATRIX (dark, glow/neon) и LIGHT (cream, warm). Переключается в settings.html, хранится серверно.

**Refresh mode**: auto (board 30s, roadmap 60s) или manual. Настраивается в settings.html, хранится серверно (`vault/.pm-user-prefs.json`). API: `GET/PUT /api/v1/user-prefs`.

**Тесты**: `node pm-bot/web/tests/test-report-node.js` (124 теста)

## Команды

| Действие | Команда | Откуда |
|---|---|---|
| Запуск всего | `docker compose up --build` | pm_assistant/ |
| Запуск фоном | `docker compose up -d` | pm_assistant/ |
| Логи | `docker compose logs -f pm-bot` | pm_assistant/ |
| Логи KE | `docker compose logs -f knowledge-engine` | pm_assistant/ |
| Пересборка | `docker compose down && docker compose build --no-cache && docker compose up -d` | pm_assistant/ |
| Локальный запуск pm-bot | `python -m app.main` | pm-bot/ |
| CLI enrich | `python -m app enrich <path>` | knowledge-engine/ |
| CLI synthesize | `python -m app synthesize` | knowledge-engine/ |
| CLI vault index | `python -m app index` | knowledge-engine/ |
| CLI jira-sync | `python -m app jira-sync --notify` | knowledge-engine/ |
| CLI jira-sync (dry) | `python -m app jira-sync --dry-run` | knowledge-engine/ |
| CLI jira-import | `python -m app jira-import <ISSUE-KEY>` | knowledge-engine/ |
| Запуск pipeline сервера | `python -m idea_pipeline serve` | idea-pipeline/ |
| CLI запуск pipeline | `python -m idea_pipeline run --text "..."` | idea-pipeline/ |
| CLI статус pipeline | `python -m idea_pipeline status <id>` | idea-pipeline/ |

## Переменные окружения (.env на уровне pm_assistant/)

| Переменная | Обязательная | Сервис | Описание |
|---|---|---|---|
| BOT_TOKEN | да | pm-bot | Токен Telegram-бота |
| CLAUDE_API_KEY | да | pm-bot, knowledge-engine, idea-pipeline | Ключ Claude API |
| VAULT_PATH | да | pm-bot, knowledge-engine, idea-pipeline | Путь к Obsidian vault |
| TRANSCRIPTS_INBOX | да | pm-bot | Папка входящих транскриптов |
| ALLOWED_CHAT_ID | да* | pm-bot | Chat ID владельца (* пустой = режим первого запуска) |
| KE_SYNTHESIS_CRON | нет | ke-cron | Расписание cron (default: 0 9 * * *) |
| KE_MIN_IDEAS_FOR_SYNTHESIS | нет | ke-cron | Минимум идей для синтеза (default: 1) |
| PIPELINE_API_URL | да | pm-bot | URL idea-pipeline API (http://idea-pipeline:8100) |
| PIPELINE_API_KEY | нет | idea-pipeline, pm-bot | API key для аутентификации |
| PIPELINE_HOST | нет | idea-pipeline | Bind host (default: 0.0.0.0) |
| PIPELINE_PORT | нет | idea-pipeline | Bind port (default: 8100) |
| PIPELINE_ANALYST_MODEL | нет | idea-pipeline | Override модели для Analyst |
| PIPELINE_PM_MODEL | нет | idea-pipeline | Override модели для PM |
| PIPELINE_DECOMPOSER_MODEL | нет | idea-pipeline | Override модели для Decomposer |
| JIRA_URL | да | knowledge-engine | URL Jira-сервера (https://jira.webpower.ru/) |
| JIRA_TOKEN | да | knowledge-engine | Personal Access Token (Bearer auth) |
| JIRA_SYNC_CRON | нет | ke-cron | Расписание синка (default: 0 */3 * * *) |
| JIRA_LABEL_DOMAIN_MAP | нет | knowledge-engine | JSON override для label→domain маппинга |
| STT_ENABLED | нет | pm-bot | Включить STT/Whisper (default: 1, set 0 to disable) |
| ENRICHMENT_REMINDER_HOUR | нет | pm-bot | Час ежедневной проверки enrichment (default: 10) |
| ENRICHMENT_REMINDER_MINUTE | нет | pm-bot | Минута проверки enrichment (default: 0) |
| ENRICHMENT_COOLDOWN_HOURS | нет | pm-bot | Минимум часов между напоминаниями (default: 24) |
| ENRICHMENT_HOST_URL | нет | pm-bot | Базовый URL для ссылок в напоминаниях (default: http://localhost:8080) |
| OLLAMA_URL | нет | pm-bot, knowledge-engine | URL Ollama-сервера (настраивается через Web UI) |
| OLLAMA_MODEL | нет | pm-bot, knowledge-engine | Модель Ollama (default: qwen3.5:latest, настраивается через Web UI) |
| DAILY_ALERT_HOUR | нет | pm-bot | Час ежедневной проверки наличия Daily-протокола (default: 18) |
| DAILY_ALERT_MINUTE | нет | pm-bot | Минута проверки наличия Daily-протокола (default: 0) |

## Performance (vault_api.py)

**In-memory TTL cache** (`_VaultCache`, TTL 30s):
- Кэшируются все тяжёлые endpoints: `/domains`, `/ideas`, `/tasks`, `/epics`, `/meetings`, `/system/status`, `/overview/queue`
- Task indices (`_build_task_indices`) — единый проход по 168 task-файлам вместо двух
- Invalidation при любой write-операции (capture, import, update status, config change)
- Warm cache при старте сервера (`@app.on_event("startup")`) — первый запрос пользователя уже из кэша
- Hot-path логи (`parse_note`, `parse_epic_note`, `_extract_section`, `_calculate_readiness`, `_scan_domain_folders`, per-domain loops) понижены до DEBUG для снижения I/O в Docker
- `/system/status`: заменён `os.walk` всего vault (тысячи stat) на проверку 3 директорий
- `/domains`: заменён per-file `stat()` на per-folder `stat()`

**Замеренный эффект** (Docker on Windows, volume mount):
| Endpoint | До | После (cached) |
|---|---|---|
| /system/status | 4882ms | 4ms |
| /overview/queue | 912ms | 4ms |
| /domains | 4891ms | 7ms |
| /ideas | 570ms | 10ms |
| /tasks | 1364ms | 34ms |
| /epics | 1370ms | 7ms |

## Документация (docs/)

| Папка | Статус | Описание |
|---|---|---|
| architecture/adr/ | — | 4 ADR: CLI-over-HTTP, keyword-matching, vault-as-DB, monorepo |
| bugs/ | — | BUG-001..008 (fixed), BUG-009..010 (theme fixes), BUG-011 (jira-sync closed handler, fixed), BUG-012 (daily-log naming, fixed), BUG-013 (vault_index.py None in tags/keywords — fix: filter None before .lower(), fixed), BUG-014 (settings.html testOllamaConnection silent early return — fix: show error + log, fixed), BUG-015 (handlers.py Telegram Markdown parse error on jira reply — fix: try/except fallback to plain text, fixed). Capture fix: vault_api.py — import _fallback_idea_data + dict→JSON serialization |
| claude-code-cli-migration/ | ANALYSIS | Анализ миграции pm_assistant на Claude Code CLI / Claude Agent SDK (analysis, ollama-qwen3-analysis) |
| context_compaction/ | DRAFT | LLM-оптимизированный контекстный слой модели знаний — PRD Layer 1' (PRD, design, SWOT, test results) |
| daily-alert/ | APPROVED, IMPLEMENTED | Alert в Telegram при отсутствии Daily-протокола за текущий день, cron 18:00 МСК (requirements, design, tasks) |
| daily-jira-sync/ | APPROVED, IMPLEMENTED | Извлечение Jira-ключей из daily-протоколов, авто-импорт недостающих, Obsidian wiki-links (requirements, design, tasks) |
| daily-progress-report/ | APPROVED, IMPLEMENTED | Команда /progress — отправка ежедневного отчёта о ходе проекта в Telegram (requirements, design, tasks) |
| domain-config/ | APPROVED, IMPLEMENTED | Настройка доменов (requirements, design, tasks) |
| ds v4/ | — | Дизайн-система v4: HTML-макеты matrix theme (matrix-ds-v4, pmassistant-design-system-v2) |
| guided-enrichment/ | APPROVED, IMPLEMENTED | Telegram-напоминания о незаполненных секциях идей (enrichment_reminder.py + enrichment_db.py, daily cron, SQLite cooldown) |
| health-scoring/ | APPROVED, IMPLEMENTED | Vault health score (0-100) + wikilink resolver. 7 категорий штрафов, endpoint /vault/health, overview виджет, ke-cron 04:00, .health-history.json 90д (requirements, design, tasks — 14 задач, BL-114, BL-115) |
| idea-board/ | APPROVED, IMPLEMENTED | Канбан-доска идей с 4 колонками (requirements, design, tasks) |
| idea-pipeline/ | APPROVED, IMPLEMENTED | Orchestrator Analyst→PM→Decomposer (requirements, design, tasks) |
| ideas-drag-n-drop/ | APPROVED, IMPLEMENTED | Drag-n-drop для идей (requirements, design, tasks) |
| ingest-clippings/ | DRAFT | Автообработка web-клиппингов из raw/inbound/clippings/ (requirements, design, tasks) |
| jira-create/ | APPROVED, IMPLEMENTED | Создание Jira-тикетов из vault (requirements, design, tasks) |
| jira-import/ | APPROVED, IMPLEMENTED | Импорт единичного тикета (requirements) |
| jira-polling/ | APPROVED, IMPLEMENTED | Регулярная синхронизация с Jira (requirements, design, tasks) |
| jira-sync-notify-toggle/ | APPROVED, IMPLEMENTED | Управление Telegram-уведомлениями после Jira sync: toggle в settings, user-prefs, двойная защита (requirements, design, tasks) |
| jira-sync-ui/ | APPROVED, IMPLEMENTED | Jira Sync UI: кнопка SYNC NOW + статус синхронизации (requirements, design, tasks) |
| knowledge-base-migration/ | ANALYSIS | Миграция базы знаний (analysis, tasks) |
| knowledge-engine/ | APPROVED, IMPLEMENTED | Enrichment + synthesis (requirements, design, tasks) |
| marketing_promo/ | — | Промо-материалы: презентации, слайды, обложки (PDF, PPTX, MD) |
| meeting-fetcher/ | APPROVED, IMPLEMENTED | Импорт транскриптов из email (requirements, design, tasks) |
| ollama-hybrid/ | APPROVED, IMPLEMENTED | Гибридная LLM-архитектура: Claude API + Ollama (requirements, design, tasks) |
| overview-dashboard/ | APPROVED, IMPLEMENTED | Overview дашборд (requirements, tasks) |
| overview-redesign/ | APPROVED, IMPLEMENTED | Редизайн overview (requirements, design, tasks) |
| pipeline-inline-prompt/ | APPROVED, IMPLEMENTED | Inline prompt для pipeline (requirements, tasks) |
| pm-web-ui/ | IN PROGRESS | Web-дашборд (SPEC, screens, tasks) |
| pm-web-ui-ds/ | — | Дизайн-система: CSS-темы flat, clip, matrix |
| pm-web-ui-terminal/ | — | Дизайн-система matrix theme: CSS/HTML-макеты (v1, v4) |
| pm_assistant_promo/ | — | Продуктовый маркетинг: FAQ, LinkedIn-посты, презентации, product assessment |
| refresh-mode/ | APPROVED, IMPLEMENTED | Режим обновления: auto/manual для board и roadmap (requirements, design, tasks) |
| report-md-support/ | APPROVED, IMPLEMENTED | Поддержка MD формата в просмотре отчётов (requirements) |
| roadmap-status-model/ | APPROVED, IMPLEMENTED | Roadmap status model: horizon→status, 4 columns, STATUS_COLUMN_MAP (requirements, design, tasks) |
| task-lifecycle/ | APPROVED, IMPLEMENTED | ЖЦ идеи: 9 полей, readiness %, статусы Новая/Проверка гипотезы/Готова/Отсев |
| tasks/ | — | Отдельные задачи вне спек (TASK-idea-naming-convention) |
| template-based-capture/ | APPROVED, IMPLEMENTED | Двухэтапный capture: Claude→JSON + шаблон templates/idea.md (requirements, design, tasks) |
| theme-cleanup/ | APPROVED, IMPLEMENTED | Удаление тем flat/clip, оставлена только matrix (tasks) |
| theme-light/ | APPROVED, IMPLEMENTED | Светлая тема LIGHT cream (requirements, design, tasks) |
| ui-audit/ | DONE | UI/UX аудит Web Dashboard: 10 страниц, 3 темы (report, screenshots) |
| v2/ | — | Прототипы дизайн-системы v2/v3: CSS + HTML макеты matrix theme |
| voice-messages/ | APPROVED, IMPLEMENTED | Голосовые сообщения в Telegram (requirements, design, tasks) |
