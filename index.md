# PM Assistant — Project Index

Платформа управления знаниями продакт-менеджера OTA-компании. Монорепо из 4 компонентов: pm-bot (Telegram-бот + Web UI + Vault API), knowledge-engine (обогащение, синтез, Jira, email-fetch), idea-pipeline (оркестратор Analyst→PM→Decomposer), web-ui (SPA-дашборд). Гибридная LLM-архитектура: Claude API + Ollama + OpenRouter. Данные в Obsidian vault как структурированные .md файлы.

## Монорепо структура

```
pm_assistant/
├── .env                            # общие секреты (не коммитить)
├── .env.example                    # шаблон переменных
├── .pre-commit-config.yaml         # pre-commit hook (ruff)
├── pyproject.toml                  # ruff + mypy конфигурация
├── requirements-dev.txt            # dev-зависимости (pytest, ruff, mypy)
├── .github/workflows/ci.yml       # GitHub Actions CI (lint + typecheck + test)
├── docker-compose.yml              # оркестрация: pm-bot + knowledge-engine (:8001 API) + ke-cron + idea-pipeline
├── settings.yaml                   # централизованная runtime-конфигурация (timeouts, cooldowns, rate_limits)
├── CHANGELOG.md                    # журнал изменений по всем компонентам (от новых к старым)
├── BACKLOG.md                      # бэклог: реализованные фичи (94, +BL-166), баги (26), идеи (35), итого (157)
│
├── shared/                         # общий модуль — единый источник для pm-bot, KE, idea-pipeline
│   ├── __init__.py                 # __version__ = "0.1.0"
│   ├── file_writer.py              # file_lock, atomic_write, locked_append, append_section
│   ├── llm_client.py               # _load_llm_prefs, get_client, call (unified fallback chain), call_detailed (отдаёт provider_record, BL-145), мультимодельные fallback-цепочки с нормализацией шага {provider, model} (BL-155), backoff 429 между openrouter-шагами, deprecated: call_with_fallback, call_transcription
│   ├── meeting_queue.py            # enqueue-ядро файловой очереди: Unit, make_unit_id, build_meta, enqueue, path-хелперы (BL-145)
│   ├── openrouter_client.py        # HTTP client for OpenRouter API (list_models с live-запросом и TTL-кэшем, call, test_connection, BL-156)
│   ├── vault_paths.py              # superset путей vault (26 функций, +llm_wiki_cowork_session)
│   ├── domain_config.py            # загрузка/сохранение domain-config.yaml (13 функций)
│   ├── frontmatter_utils.py        # read_frontmatter, update_frontmatter
│   ├── settings.py                 # загрузка settings.yaml, dot-notation доступ, singleton
│   ├── system_log.py               # Централизованный журнал системных операций (SQLite, 13 process types вкл. cowork-context)
│   ├── langfuse_client.py          # Singleton Langfuse client с graceful degradation (BL-166)
│   └── tests/                      # unit-тесты для shared/
│       ├── test_settings.py        # 14 тестов
│       ├── test_openrouter.py      # 9 тестов (call, test_connection, models)
│       ├── test_llm_client.py     # 21 тестов (call, fallback chains, migration, resolve)
│       ├── test_llm_transcription.py  # 5 тестов (call_transcription fallback chain)
│       └── test_system_log.py      # unit-тесты для system_log.py
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
│   ├── unified-domain-rules/        # BL-119: requirements.md, design.md, tasks.md
│   ├── domain-general-revision/     # BL-124 DONE: requirements.md, design.md, tasks.md
│   ├── dedup-and-config/            # BL-126+BL-130 DONE: requirements.md, design.md, tasks.md (28 задач)
│   ├── decay-engine-dashboard/      # BL-132 DONE: requirements.md, design.md, tasks.md (13 задач), прототип index.html
│   ├── decision-journal/           # BL-24 DONE: requirements.md, design.md, tasks.md
│   ├── capture-terminal-redesign/   # BL-137 DONE: requirements.md, design.md, tasks.md (13 задач)
│   ├── meeting-protocol-enrich/     # BL-133+BL-134 DONE: requirements.md, design.md, tasks.md (4 задачи)
│   ├── openrouter-transcription/    # BL-138 DONE: requirements.md, design.md, tasks.md (10 задач)
│   ├── openrouter-model-selection/  # BL-155+BL-156 DONE: requirements.md, design.md, tasks.md (13 задач)
│   ├── openrouter-model-filter/    # BL-158 DONE: requirements.md, design.md, tasks.md (4 задачи)
│   ├── BL-166_langfuse-observability/  # BL-166: спека Langfuse LLM Observability (requirements, design, tasks)
│   └── architecture/adr/           # 5 ADR (решения по архитектуре)
│
├── pm-bot/                         # Telegram-бот (capture)
│   ├── Dockerfile                  # образ Python 3.12-slim + shared/
│   ├── requirements.txt            # 11 зависимостей (+tiktoken для BL-147)
│   ├── CLAUDE.md                   # инструкции для Claude Code
│   ├── CONTEXT.md                  # история проектных решений
│   └── app/                        # исходный код
│       ├── __init__.py
│       ├── main.py                 # точка входа: запуск бота + watcher
│       ├── handlers.py             # Telegram: /start, /idea, /jira, /daily, /synthesize, /jira_sync, /jira_import, /jira_create, /pipeline, /domain, /lint, /status, /test_enrichment, текст, голос
│       ├── claude_client.py        # Claude/Ollama: process_idea (→dict/JSON + digest context injection), process_meeting, process_jira_ticket, process_daily (через llm_client)
│       ├── obsidian_writer.py      # запись .md: write_idea (template-based), write_meeting, write_jira_draft, write_daily, write_report
│       ├── pdf_exporter.py         # конвертация markdown → HTML → PDF (WeasyPrint, markdown-it-py)
│       ├── pipeline_client.py      # HTTP-клиент к idea-pipeline API
│       ├── reporter.py             # генерация еженедельных отчётов через Claude
│       ├── scheduler.py            # APScheduler: weekly_report (Mon 09:00), enrichment_reminder (daily, configurable), daily_alert (пн-пт 18:00)
│       ├── stt.py                  # Speech-to-Text (faster-whisper, lazy import, env STT_ENABLED)
│       ├── transcript_watcher.py   # watchdog: транскрипты .txt → Meetings/
│       ├── vault_api.py            # FastAPI REST сервер: vault API + user-prefs API (валидация openrouter-шагов, BL-155) + capture + test-ollama + in-memory TTL cache + GET /openrouter-models (BL-156)
│       ├── context_assembler.py    # Waterfall context assembly из llm_wiki/ (one-liners→core→extended), kill switch DIGEST_CONTEXT_SOURCE, enrich_creative_recall (BL-147)
│       ├── ke_client.py            # HTTP-клиент к KE API (22 функции, +digest_generate, digest_bulk, digest_status)
│       ├── rate_limiter.py         # TelegramRateLimiter (token bucket, params из settings)
│       ├── enrichment_reminder.py  # ЖЦ идей: скан по доменам, readiness %, Telegram-напоминания
│       ├── enrichment_db.py        # SQLite: дедупликация напоминаний (cooldown 24ч, cleanup 90д)
│       ├── daily_alert.py          # Alert при отсутствии Daily-протокола (cron 18:00 МСК, пн-пт, weekend skip)
│       └── prompts/                # 5 промптов (idea, meeting, jira_ticket, daily, weekly_report)
│   └── web/                        # SPA веб-дашборд (Vue 3 + vanilla JS)
│       ├── index.html              # redirect → overview.html
│       ├── overview.html           # дашборд: system status, idea funnel, today's queue, activity feed, quick capture
│       ├── board.html              # канбан-доска (auto-refresh 30s / manual + refresh icon)
│       ├── ideas.html              # канбан идей по статусам + capture drawer (4 типа) + readiness %
│       ├── meeting.html            # просмотр одного протокола встречи (markdown render)
│       ├── dashboard.html           # домены, статистика артефактов, Jira sync status, Vault Health card
│       ├── roadmap.html            # roadmap с эпиками (auto-refresh 60s / manual + refresh icon)
│       ├── timeline.html           # таймлайн фич
│       ├── decay.html              # decay state dashboard: bubble scatter, donut, projection, domain bars, gems
│       ├── decay.js                # логика decay dashboard: Chart.js, проекция, gems (424 строки)
│       ├── decisions.html          # журнал решений из протоколов (поиск, фильтры, expand контекст)
│       ├── playground.html         # LLM Playground: тестирование провайдеров и моделей
│       ├── report.html             # просмотр отчётов (marked.js для MD)
│       ├── settings.html           # настройки (theme, refresh mode, LLM Providers с мультимодельными fallback chains + inline model selector (BL-155), prompts, Jira sync)
│       ├── processes.html          # каталог системных процессов
│       ├── process.html            # детальная страница процесса
│       ├── system-log.html         # Журнал системных операций — лог cron/pipeline/scheduler с фильтрацией
│       ├── api.js                  # fetch-клиент к vault_api (cancellation, caching, user-prefs, decay snapshot)
│       ├── components.js           # shared Vue 3 компоненты (sidebar, cards, drawer)
│       ├── style.css               # базовая тема (flat)
│       ├── style-matrix.css        # matrix тема (glow, neon)
│       ├── style-light.css         # light тема (cream, warm)
│       ├── vendor/                 # локальные зависимости
│       │   └── fonts/              # локальные шрифты (Material Symbols, JetBrains Mono, Inter, Share Tech Mono)
│       └── tests/                  # Node.js unit-тесты для страниц
│           ├── test-report-node.js
│           ├── test-components-node.js
│           ├── test-api-node.js
│           └── test-roadmap-node.js
│
├── knowledge-engine/               # сервис обогащения и синтеза
│   ├── Dockerfile                  # образ Python 3.12-slim
│   ├── requirements.txt            # 9 зависимостей (+ tiktoken для BL-147)
│   └── app/                        # исходный код
│       ├── __init__.py
│       ├── __main__.py             # точка входа: python -m app
│       ├── cli.py                  # CLI: jira-sync, jira-import, jira-create, jira-projects, jira-epics, jira-issue-types, enrich, synthesize, watch, index, lint, status, digest, digest-bulk, digest-index, digest-audit, digest-status, cowork-context
│       ├── api.py                  # FastAPI HTTP API (29 эндпоинтов, порт 8001) — +digest/generate, digest/bulk, digest/status (BL-147), +cowork-context (BL-151)
│       ├── enricher.py             # обогащение идеи связями из vault
│       ├── synthesizer.py          # синтез: кластеризация + сводка
│       ├── vault_index.py          # сканирование vault, in-memory индекс
│       ├── domain_manager.py       # управление доменами: scaffold, index, log
│       ├── matcher.py              # keyword + tag matching
│       ├── claude_client.py        # Claude API для enrichment/synthesis/meeting_protocol, min response length validation
│       ├── notifier.py             # Telegram уведомления через Bot API
│       ├── watcher.py              # watchdog: InboxHandler (auto-enrichment), ClippingsHandler (ingest), DigestHandler (auto-digest при DIGEST_ENABLED=1, debounce 5s)
│       ├── artifact_extractor.py   # извлечение артефактов
│       ├── linter.py               # линтер vault-файлов
│       ├── status_migrator.py          # миграция статусов идей: STATUS_MAP + VALID_STATUSES + migrate_statuses()
│       ├── process_one.py          # обработка одного файла
│       ├── jira_fetcher/           # модуль синхронизации с Jira
│       │   ├── __init__.py
│       │   ├── client.py           # Jira REST API v2 client (Bearer PAT auth): get_projects, get_project_issue_types, get_project_epics, create_issue, search
│       │   ├── state.py            # .jira-sync-state.json — отслеживание состояния
│       │   ├── mapper.py           # Jira issue → Markdown с frontmatter + domain detection
│       │   └── fetcher.py          # оркестратор: fetch → diff → write → log → notify
│       ├── meeting_fetcher/        # импорт транскриптов из email + файловая очередь обработки (BL-145)
│       │   ├── __init__.py
│       │   ├── imap_client.py      # IMAP клиент для почты
│       │   ├── classifier.py       # классификация транскриптов
│       │   ├── fetcher.py          # Fetch-фаза (BL-145): fetch_emails → enqueue в pending/ (без LLM); дедуп is_enqueued OR is_processed
│       │   ├── queue.py            # MeetingQueue: claim/claim_next/complete/fail/requeue/reclaim_stuck/status_counts (BL-145)
│       │   ├── processor.py        # Process-воркер: process_one/process_pending + validate_protocol; LLM call_detailed → валидация → write wiki (BL-145)
│       │   ├── queue_watcher.py    # watchdog-демон на pending/ (on_created+on_moved → claim → process_one), near-realtime (BL-145)
│       │   └── state.py            # состояние fetch: processed + enqueued (постоянный дедуп-маркер, BL-145)
│       ├── digest/                 # генерация LLM-дайджестов для llm_wiki/ (BL-147)
│       │   ├── __init__.py         # экспорты: generate_digest, validate, count_tokens, detect_type и др.
│       │   ├── generator.py        # generate_digest, generate_bulk, regenerate_index
│       │   ├── paths.py            # wiki_to_llm_wiki, llm_wiki_to_wiki, ensure_llm_wiki_structure
│       │   ├── templates.py        # detect_type, get_template, ARTIFACT_TYPE_MAP
│       │   ├── token_counter.py    # count_tokens, count_sections (tiktoken cl100k_base)
│       │   └── validator.py        # validate: token budgets, required fields, key-value format
│       ├── cowork_context.py       # генерация _cowork-session.md для Cowork (BL-151): 5 коллекторов, детерминированная сборка
│       └── prompts/                # 16 промптов (enrich, synthesize, meeting_protocol, digest + 12 type-specific)
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
| **pm-bot** | 1.18.2 | 2026-07-13 | Telegram-бот + Web UI + Vault API. Гибридная LLM-архитектура. KE через HTTP API (ke_client.py, 22 функции). Rate limiter для Telegram. SQLite volume (pm-bot-data). Импорты из shared/. context_assembler: waterfall сборка контекста из llm_wiki/ (kill switch DIGEST_CONTEXT_SOURCE), enrich_creative_recall (BL-147 Phase 2). Digest context injection в process_idea и weekly report. Мультимодельные OpenRouter fallback-цепочки с inline model selector + GET /openrouter-models (BL-155, BL-156). Playground providers: live-список моделей OpenRouter через list_models() (BL-158). Report search/filter: _extract_report_type + type в ответе /api/v1/reports, UI поиск + фильтр-чипы (BL-161). Epic body в drawer roadmap: SHOW_BODY/SHOW_TICKETS тогглер, body в ответе /api/v1/epics (BL-162). |
| **knowledge-engine** | 1.15.2 | 2026-07-17 | Enrichment, synthesis, Jira sync, meeting fetch. HTTP API на порту 8001 (29 эндпоинтов). DigestHandler в watcher.py (DIGEST_ENABLED env, debounce 5s, body_hash check). 3 API endpoints: digest/generate, digest/bulk, digest/status (BL-147 Phase 2). cowork_context: _cowork-session.md для Cowork (BL-151). Jira sync fallback: поиск vault-файлов по jira_key в frontmatter для кастомных имён (BUG-023). Fix _CLOSED_STATUSES: задачи "Отменена" корректно распознаются как закрытые (BUG-025). |
| **idea-pipeline** | 1.2.0 | 2026-07-22 | Orchestrator: Analyst → PM → Decomposer. LLM-вызовы через shared/llm_client с fallback-цепочками (pipeline_analyst, pipeline_pm, pipeline_decomposer). PipelineClaudeClient удалён. Импорты vault_paths и file_writer из shared/. |
| **web-ui** | 1.26.3 | 2026-07-13 | Dual-theme SPA дашборд. Inline Editing (BL-61): click-to-edit полей + body editor split view. Keyword Search (BL-60), Scroll-to-Card (BL-64), Forgotten Gems popup (BL-135), Capture Terminal Redesign (BL-137), Drag-and-drop fallback chains в Settings (BL-140, BL-141), LLM Playground (BL-142). Decision Journal (BL-24): decisions.html + meeting.html + overview виджет RECENT DECISIONS. Process Catalog (processes.html, process.html). Searchable dropdown для моделей OpenRouter в settings.html и playground.html, общий CSS в style.css (BL-158). Report search/filter: поиск по имени/заголовку + фильтр-чипы по типу (BL-161). Epic body toggle в drawer roadmap (BL-162). BUG-021/022: Jira Import direct key fix + ticket list filtering. |
| **инфраструктура** | 1.1.0 | 2026-06-30 | CI pipeline: GitHub Actions (ruff + mypy + pytest, matrix strategy), pre-commit hook, pyproject.toml, requirements-dev.txt (BL-120). KE-контейнер: процесс queue-watch (watchdog на pending/); ke-cron: process-queue каждые 10 мин — страховка/reclaim (BL-145). |
| **shared** | 0.7.2 | 2026-07-22 | Общий модуль: llm_client (call с настраиваемыми fallback-цепочками, 4 группы операций: capture/transcription/analysis/pipeline, _normalize_step для мультимодельных цепочек {provider, model}, backoff 0.7s при 429, Ollama timeout ×5, call_transcription, call_detailed — additive, отдаёт provider_record + chain/used_model/used_step_index + автоматический LLM trace в system_log — BL-155, BL-167), langfuse_client (singleton с graceful degradation — BL-166), meeting_queue (enqueue-ядро файловой очереди: Unit, make_unit_id, build_meta, enqueue, path-хелперы — BL-145), openrouter_client (list_models с live API + TTL-кэш 1ч + fallback — BL-156; call() с детальным логированием raw-body при ошибке парсинга — BUG-020), system_log (13 process types, LoggedProcess, per-unit details), file_writer, vault_paths (26 функций, +llm_wiki_cowork_session), domain_config, frontmatter_utils, settings. Единый источник для всех компонентов. |

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
| FastAPI | >=0.111.0 (pm-bot), >=0.115.0 (pipeline, KE) | pm-bot, idea-pipeline, knowledge-engine |
| uvicorn | >=0.30.0 (pm-bot), >=0.32.0 (pipeline, KE) | pm-bot, idea-pipeline, knowledge-engine |
| python-slugify | >=8.0.0 | idea-pipeline |
| Claude модель | claude-sonnet-4-6 | pm-bot, knowledge-engine, idea-pipeline |
| marked.js | 15.x (CDN) | pm-bot (web) |
| Vue.js | 3.x (CDN) | pm-bot (web) |
| faster-whisper | >=1.0.0 | pm-bot |
| apscheduler | >=3.10.4 | pm-bot |
| weasyprint | >=62.0 | pm-bot |
| markdown-it-py | >=3.0.0 | pm-bot |
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
| knowledge-engine | HTTP API (:8001) + Watchdog на Inbox/ | sh -c "python -m knowledge_engine serve & python -m knowledge_engine watch" |
| idea-pipeline | Orchestrator: Analyst → PM → Decomposer | python -m idea_pipeline serve |
| ke-cron | Синтез (09:00) + Cowork-context (01:00) + Jira sync (каждые 3ч) | crond |
| langfuse-db | PostgreSQL 15, хранилище Langfuse | — |
| langfuse | Langfuse v2 (LLM observability UI), порт 3100 | — |

## Web UI

Статические HTML-страницы (`pm-bot/web/`) раздаются через `python -m http.server` на порту 8080.
Данные получают из vault_api (FastAPI, порт 8000) через `api.js`.

| Страница | Назначение |
|---|---|
| index.html | Redirect → overview.html |
| overview.html | Дашборд: system status, idea funnel, today's queue, activity feed, quick capture |
| ideas.html | Канбан идей: 4 колонки по статусам, фильтр по доменам, capture drawer, readiness % |
| meeting.html | Просмотр одного протокола встречи (markdown render, кнопка НАЗАД) |
| board.html | Канбан-доска задач |
| dashboard.html | Домены, статистика артефактов, Jira sync status (overdue alert) |
| decisions.html | Журнал решений: карточки из протоколов, поиск, фильтр по домену/дате, expand с контекстом |
| roadmap.html | Roadmap с эпиками и прогрессом |
| timeline.html | Таймлайн по фичам |
| report.html | Просмотр еженедельных отчётов (Markdown → HTML через marked.js) |
| settings.html | Настройки: тема, refresh mode, LLM Provider (Claude/Ollama/Hybrid + Test Connection), prompts, Jira sync, Email Fetch |
| playground.html | LLM Playground: тестирование провайдеров и моделей |
| processes.html | Каталог системных процессов |
| process.html | Детальная страница процесса |
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
| CLI digest | `python -m app digest <path>` | knowledge-engine/ |
| CLI digest-bulk | `python -m app digest-bulk [--domain X] [--type Y]` | knowledge-engine/ |
| CLI digest-index | `python -m app digest-index` | knowledge-engine/ |
| CLI digest-audit | `python -m app digest-audit` | knowledge-engine/ |
| CLI digest-status | `python -m app digest-status` | knowledge-engine/ |
| Запуск pipeline сервера | `python -m idea_pipeline serve` | idea-pipeline/ |
| CLI запуск pipeline | `python -m idea_pipeline run --text "..."` | idea-pipeline/ |
| CLI статус pipeline | `python -m idea_pipeline status <id>` | idea-pipeline/ |
| Линтер | `ruff check pm-bot/app/ knowledge-engine/app/ idea-pipeline/app/` | pm_assistant/ |
| Линтер (автофикс) | `ruff check --fix pm-bot/app/ knowledge-engine/app/ idea-pipeline/app/` | pm_assistant/ |
| Типы (KE) | `mypy knowledge-engine/app/ --config-file pyproject.toml` | pm_assistant/ |
| Типы (pm-bot) | `mypy pm-bot/app/ --config-file pyproject.toml` | pm_assistant/ |
| Тесты KE | `PYTHONPATH=knowledge-engine pytest knowledge-engine/tests/` | pm_assistant/ |
| Тесты pm-bot | `PYTHONPATH=pm-bot:knowledge-engine pytest pm-bot/tests/` | pm_assistant/ |
| Тесты pipeline | `PYTHONPATH=idea-pipeline:knowledge-engine pytest idea-pipeline/tests/` | pm_assistant/ |

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
| OPENROUTER_API_KEY | нет | pm-bot, knowledge-engine | Ключ OpenRouter API для транскрибаций (настраивается через Web UI) |
| DAILY_ALERT_HOUR | нет | pm-bot | Час ежедневной проверки наличия Daily-протокола (default: 18) |
| DAILY_ALERT_MINUTE | нет | pm-bot | Минута проверки наличия Daily-протокола (default: 0) |
| KE_API_URL | нет | pm-bot | URL KE HTTP API (default: http://knowledge-engine:8001) |
| DB_PATH | нет | pm-bot | Путь к SQLite БД (default: /data) |
| LANGFUSE_PUBLIC_KEY | нет | pm-bot, knowledge-engine, idea-pipeline | Public key проекта Langfuse |
| LANGFUSE_SECRET_KEY | нет | pm-bot, knowledge-engine, idea-pipeline | Secret key проекта Langfuse |
| LANGFUSE_HOST | нет | pm-bot, knowledge-engine, idea-pipeline | Внутренний URL Langfuse (default: http://langfuse:3000) |
| LANGFUSE_ENABLED | нет | pm-bot, knowledge-engine, idea-pipeline | Включить/отключить Langfuse (default: true) |

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
| /decisions | ~1500ms | 100ms |

## Документация (docs/)

| Папка | Статус | Описание |
|---|---|---|
| architecture/adr/ | — | 5 ADR: CLI-over-HTTP, keyword-matching, vault-as-DB, monorepo, file-based-meeting-queue (ADR-005, BL-145) |
| bugs/ | — | BUG-001..008 (fixed), BUG-009..010 (theme fixes), BUG-011 (jira-sync closed handler, fixed), BUG-012 (daily-log naming, fixed), BUG-013 (vault_index.py None in tags/keywords — fix: filter None before .lower(), fixed), BUG-014 (settings.html testOllamaConnection silent early return — fix: show error + log, fixed), BUG-015 (handlers.py Telegram Markdown parse error on jira reply — fix: try/except fallback to plain text, fixed), BUG-016 (patch_jira_links exact match не патчит ключи с комментариями, fixed), BUG-017 (_inject_source_file footer wikilink append fallback, fixed), BUG-018 (capture_mode теряется при PUT /user-prefs, fixed), BUG-019 (enrich() NoneType на протоколах встреч, fixed), BUG-020 (OpenRouter Nemotron parse error, monitoring), BUG-021 (Jira Import direct key не работает в extended capture, fixed), BUG-022 (список задач Jira не фильтруется по ключу, fixed). Capture fix: vault_api.py — import _fallback_idea_data + dict→JSON serialization |
| claude-code-cli-migration/ | ANALYSIS | Анализ миграции pm_assistant на Claude Code CLI / Claude Agent SDK (analysis, ollama-qwen3-analysis) |
| context_compaction/ | DRAFT | LLM-оптимизированный контекстный слой модели знаний — PRD Layer 1' (PRD, design, SWOT, test results) |
| capture-terminal-redesign/ | APPROVED, DONE | BL-137: Редизайн capture terminal — extended mode с card-based UI, Jira Import, Settings toggle (requirements, design, tasks — 13 задач) |
| daily-alert/ | APPROVED, IMPLEMENTED | Alert в Telegram при отсутствии Daily-протокола за текущий день, cron 18:00 МСК (requirements, design, tasks) |
| daily-jira-sync/ | APPROVED, IMPLEMENTED | Извлечение Jira-ключей из daily-протоколов, авто-импорт недостающих, Obsidian wiki-links (requirements, design, tasks) |
| daily-progress-report/ | APPROVED, IMPLEMENTED | Команда /progress — отправка ежедневного отчёта о ходе проекта в Telegram (requirements, design, tasks) |
| decision-journal/ | DONE | BL-24: Decision Journal — единый реестр решений из протоколов (requirements, design, tasks — 6 задач) |
| dedup-and-config/ | APPROVED, DONE | BL-126+BL-130: Дедупликация + декаплинг — shared/ модуль, KE HTTP API, ke_client, settings.yaml (requirements, design, tasks — 28 задач) |
| domain-config/ | APPROVED, IMPLEMENTED | Настройка доменов (requirements, design, tasks) |
| domain-general-revision/ | APPROVED, DONE | BL-124: Ревизия домена general — domain_mover.py + 3 CLI + 14 тестов. Batch выполнен: 1 moved, 7 дубликатов удалены, 148 unmatched (requirements, design, tasks) |
| ds v4/ | — | Дизайн-система v4: HTML-макеты matrix theme (matrix-ds-v4, pmassistant-design-system-v2) |
| guided-enrichment/ | APPROVED, IMPLEMENTED | Telegram-напоминания о незаполненных секциях идей (enrichment_reminder.py + enrichment_db.py, daily cron, SQLite cooldown) |
| health-scoring/ | APPROVED, IMPLEMENTED | Vault health score (0-100) + wikilink resolver. 7 категорий штрафов, endpoint /vault/health, overview виджет, ke-cron 04:00, .health-history.json 90д (requirements, design, tasks — 14 задач, BL-114, BL-115) |
| idea-status-unification/ | APPROVED, IMPLEMENTED | Унификация статусов идей: миграция legacy→каноничные, linter проверка, fallback fix (requirements, design, tasks — 7 задач, BL-122) |
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
| meeting-processing-queue/ | APPROVED, IMPLEMENTED, e2e VERIFIED | BL-145: трёхфазная файловая очередь обработки протоколов (Fetch/Queue/Process), watchdog (PollingObserver) + cron, retry по fallback-цепочке (max_attempts=5), валидация ответа до записи в wiki. E2E пройден на Docker 30.06.2026 (requirements, design, tasks, ADR-005) |
| system-activity-log/ | APPROVED, DONE | Централизованный журнал системных операций (cron/pipeline/scheduler) с фильтрацией и пагинацией (requirements, design, tasks — 14 задач). LLM trace в call_detailed, system-log.html, overview badge |
| ollama-hybrid/ | APPROVED, IMPLEMENTED | Гибридная LLM-архитектура: Claude API + Ollama (requirements, design, tasks) |
| overview-dashboard/ | APPROVED, IMPLEMENTED | Overview дашборд (requirements, tasks) |
| overview-redesign/ | APPROVED, IMPLEMENTED | Редизайн overview (requirements, design, tasks) |
| pipeline-inline-prompt/ | APPROVED, IMPLEMENTED | Inline prompt для pipeline (requirements, tasks) |
| pm-web-ui/ | APPROVED, DONE | Web-дашборд: 13 страниц, 14 Vue-компонентов, dual-theme, vault API (SPEC, screens, tasks — 11 задач + 6 DS задач) |
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
| vault-write-coordination/ | APPROVED, IMPLEMENTED | BL-125: Координация писателей в vault — file locks, atomic write, устранение race conditions в LOG.md, index.md, append_section (requirements, design, tasks) |
| voice-messages/ | APPROVED, IMPLEMENTED | Голосовые сообщения в Telegram (requirements, design, tasks) |
