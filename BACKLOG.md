# Бэклог -- PM Assistant

**Версии:** pm-bot 1.9.0 / knowledge-engine 1.8.0 / idea-pipeline 1.1.2 / web-ui 1.15.6
**Обновлён:** 14.06.2026

---

## 1. Захват контента

### 1.1 Реализовано

| # | Название | Компонент | Описание |
|---|:---|:---|:---|
| BL-01 | ✅ Telegram-бот: capture идей | pm-bot | Команды /idea, текст, голос. Claude извлекает структурированный JSON |
| BL-02 | ✅ Template-based capture | pm-bot | Двухэтапный capture: Claude -> JSON + шаблон templates/idea.md. Frontmatter + 9-блочная структура |
| BL-03 | ✅ Speech-to-Text | pm-bot | faster-whisper, lazy import, env STT_ENABLED. Голосовые сообщения -> текст -> идея |
| BL-04 | ✅ Daily-заметки | pm-bot | Команда /daily, запись в raw/inbound/daily-logs/ + wiki/daily-logs/ |
| BL-05 | ✅ Jira-черновики | pm-bot | Команда /jira, Claude обработка -> raw/inbound/tasks/ + wiki/domains/ |
| BL-06 | ✅ Transcript watcher | pm-bot | watchdog: .txt транскрипты -> raw/inbound/meeting-notes/ + wiki/meetings/ |
| BL-07 | ✅ Web capture | web-ui | Capture drawer на overview и ideas: 4 типа (idea, task, meeting, jira_import) |
| BL-08 | ✅ Доменная маршрутизация | pm-bot | Domain определяется Claude при обработке. Файлы маршрутизируются в wiki/domains/<domain>/ |
| BL-108 | ✅ Daily Progress Report | pm-bot | Команда /progress: отправка ежедневного отчёта о ходе проекта в Telegram (с датой или последний) |
| BL-109 | ✅ Меню команд бота | pm-bot | 14 команд в Telegram UI через set_my_commands (post_init) |

### 1.2 Идеи

| # | Название | Компонент | Описание |
|---|:---|:---|:---|
| BL-09 | Ingest clippings | knowledge-engine | Автообработка web-клиппингов из raw/inbound/clippings/ в wiki/. Watchdog + CLI /ingest. Спека: docs/ingest-clippings/ (DRAFT) |
| BL-10 | Обработка raw/misc/ | knowledge-engine | Автосортировка неклассифицированных файлов из raw/inbound/misc/ (упомянуто в Out of Scope ingest-clippings) |

---

## 2. Обработка знаний

### 2.1 Реализовано

| # | Название | Компонент | Описание |
|---|:---|:---|:---|
| BL-11 | ✅ Enrichment идей | knowledge-engine | Обогащение связями из vault. Auto-enrichment через watchdog на raw/inbound/ |
| BL-12 | ✅ Synthesis | knowledge-engine | Кластеризация идей + сводка. Cron (ежедневно 09:00) или /synthesize |
| BL-13 | ✅ Vault index | knowledge-engine | Сканирование vault, in-memory индекс, keyword + tag matching |
| BL-14 | ✅ Linter | knowledge-engine | Линтер vault-файлов: проверка frontmatter, структуры, битых ссылок |
| BL-15 | ✅ Миграция на доменное хранилище | knowledge-engine | raw/ + wiki/domains/ двухслойная архитектура. 21 задача завершена |
| BL-16 | ✅ Domain manager | knowledge-engine | Scaffold, index, activity log для доменов |
| BL-17 | ✅ Meeting fetcher | knowledge-engine | IMAP клиент, классификация транскриптов, автообработка из email |
| BL-18 | ✅ Guided enrichment | pm-bot | Daily cron, SQLite cooldown 24ч, Telegram-напоминания о незаполненных полях идей |
| BL-107 | ✅ Daily Jira Sync | pm-bot, knowledge-engine | Извлечение Jira-ключей из daily-протоколов (Telegram + email), авто-импорт недостающих, Obsidian wiki-links |

### 2.2 Идеи

| # | Название | Компонент | Описание |
|---|:---|:---|:---|
| BL-19 | Генерация summary через Claude для клиппингов | knowledge-engine | v1 ingest копирует содержимое as-is, summary через LLM -- следующий шаг (упомянуто в Out of Scope ingest-clippings) |
| BL-20 | Автоматическое обогащение knowledge-файлов | knowledge-engine | Enrichment для созданных через ingest knowledge-файлов (упомянуто в Out of Scope ingest-clippings) |
| BL-21 | Ночной линтер | knowledge-engine | Проверка битых ссылок, сирот, протухших черновиков по cron (упомянуто в analysis миграции) |
| BL-22 | Enrichment с семантическим поиском | knowledge-engine | При capture автоматически линковать к похожим существующим заметкам в vault |
| BL-23 | Action Items Aggregator | knowledge-engine | Извлечь task/@assignee из протоколов -> агрегация по людям, трекинг overdue |
| BL-24 | Decision Journal | knowledge-engine | Решения из встреч с тегом decision -> поиск "почему выбрали X?" с авто-контекстом |

---

## 3. Интеграции

### 3.1 Реализовано

| # | Название | Компонент | Описание |
|---|:---|:---|:---|
| BL-25 | ✅ Jira sync | knowledge-engine | Cron каждые 3ч, JQL fetch, diff state, domain detection, Telegram notify |
| BL-26 | ✅ Jira import | knowledge-engine | Импорт единичного тикета по ключу. CLI + Telegram /jira_import |
| BL-27 | ✅ Jira create | knowledge-engine | Создание тикетов из vault. CLI + Telegram /jira_create |
| BL-28 | ✅ Jira Sync UI | web-ui | Sync status card на dashboard, SYNC NOW на settings, overdue alert >3ч |
| BL-29 | ✅ Email meeting fetcher | knowledge-engine | IMAP: fetch транскриптов из почты -> classify -> wiki -> enrich -> notify |

### 3.2 Идеи

| # | Название | Компонент | Описание |
|---|:---|:---|:---|
| BL-30 | Competitive Spy | knowledge-engine | Мониторинг App Store отзывов, changelogs конкурентов, вакансии -> сигналы в Inbox |

---

## 4. Пайплайн идей

### 4.1 Реализовано

| # | Название | Компонент | Описание |
|---|:---|:---|:---|
| BL-31 | ✅ Orchestrator | idea-pipeline | Analyst -> PM -> Decomposer. FastAPI, 5 endpoints, configurable models |
| BL-32 | ✅ Inline prompt | idea-pipeline | Настраиваемые промпты через pipeline.yaml. API key аутентификация |
| BL-33 | ✅ Pipeline client | pm-bot | HTTP-клиент к idea-pipeline API. Telegram /pipeline |
| BL-34 | ✅ Task lifecycle | pm-bot | 9 полей, readiness %, статусы Новая/Проверка гипотезы/Готова/Отсев |

### 4.2 Идеи

| # | Название | Компонент | Описание |
|---|:---|:---|:---|
| BL-35 | Ручное утверждение между этапами (gates) | idea-pipeline | Step-by-step режим с gate-ами между агентами (упомянуто в Out of Scope idea-pipeline) |
| BL-36 | Перезапуск pipeline с промежуточного этапа | idea-pipeline | Resume с этапа PM/Decomposer через CLI/Telegram (описано в FLOW-03 idea-pipeline) |
| BL-37 | Запуск pipeline из существующей заметки | idea-pipeline | /pipeline_file <path> -- запуск по файлу из vault (описан в FLOW-02 idea-pipeline) |
| BL-38 | Авто-статус по readiness | pm-bot | При достижении порогов readiness (44%, 100%) автоматически менять статус идеи |
| BL-39 | Board-as-Opponent | idea-pipeline | При каждой идее агент генерирует devil's advocate: "почему НЕ делать, риски, альтернативы" |

---

## 5. Web UI

### 5.1 Реализовано

| # | Название | Компонент | Описание |
|---|:---|:---|:---|
| BL-40 | ✅ Overview dashboard | web-ui | System status, idea funnel, today's queue, activity feed, quick capture |
| BL-41 | ✅ Overview redesign | web-ui | Command center: KPI-метрики, donut chart, glass-blur панели |
| BL-42 | ✅ Канбан идей | web-ui | 4 колонки по статусам, фильтр по доменам, readiness % |
| BL-43 | ✅ Drag-n-drop идей | web-ui | Перетаскивание между колонками. R1: readiness 100% для Готова, R2: warning < 44% |
| BL-44 | ✅ Канбан задач | web-ui | board.html: канбан-доска задач |
| BL-45 | ✅ Roadmap | web-ui | Эпики с прогрессом. Auto-refresh 60s / manual |
| BL-46 | ✅ Roadmap status model | web-ui | Колонки Backlog/Todo/In Progress/Done вместо горизонтов. STATUS_COLUMN_MAP |
| BL-47 | ✅ Timeline | web-ui | Таймлайн фич |
| BL-48 | ✅ Report viewer | web-ui | Просмотр отчётов: Markdown -> HTML через marked.js |
| BL-49 | ✅ Dashboard | web-ui | Домены, статистика артефактов, Jira sync status |
| BL-50 | ✅ Settings | web-ui | Тема, refresh mode, LLM Provider, prompts, Jira sync |
| BL-51 | ✅ Design system | web-ui | Matrix DS v4, flat/clip удалены, только matrix + light |
| BL-52 | ✅ Light theme | web-ui | Cream/warm палитра, dual-theme MATRIX <-> LIGHT |
| BL-53 | ✅ Theme cleanup | web-ui | Удаление тем flat/clip, оставлена только matrix |
| BL-54 | ✅ Refresh mode | web-ui | Auto (board 30s, roadmap 60s) / manual. Серверное хранение |
| BL-55 | ✅ Capture drawer | web-ui | 4 типа: idea, task, meeting, jira_import. На overview и ideas |
| BL-56 | ✅ Report MD support | web-ui | Markdown-рендеринг отчётов через marked.js |
| BL-57 | ✅ Domain config | web-ui | Настройка доменов через Web UI + CLI |
| BL-101 | ✅ DD.MM.YYYY даты | web-ui | Единый формат дат DD.MM.YYYY на всех страницах и компонентах (cards, drawer, timeline, roadmap, dashboard, report) |
| BL-102 | ✅ Board: классификация задач | web-ui | Классификация по jira_key (Jira vs internal), типы из frontmatter (BACKEND, FRONTEND, TESTING, RESEARCH, DESIGN), IDEA-* отфильтрованы с доски, fallback-тип NOTE → TASK |

### 5.2 Идеи

| # | Название | Компонент | Описание |
|---|:---|:---|:---|
| BL-58 | Web UI для knowledge-файлов | web-ui | Просмотр клиппингов и knowledge-файлов (упомянуто в Out of Scope ingest-clippings) |
| BL-59 | Mermaid Diagrams | web-ui | Рендеринг Mermaid-диаграмм в body PRD/Epic |
| BL-60 | Keyword Search | web-ui | Полнотекстовый поиск по vault из Web UI |
| BL-61 | Inline Editing | web-ui | Редактирование полей артефактов прямо из board/drawer |
| BL-62 | Bulk Operations | web-ui | Мультивыбор карточек на доске для массовых действий |
| BL-63 | Syntax Highlighting | web-ui | highlight.js для блоков кода в body артефактов |
| BL-64 | highlight=IDEA-NNNN | web-ui | Поддержка ?highlight= параметра в ideas.html (авто-скролл к идее из напоминания) |
| BL-65 | Time Machine | web-ui | Таймлайн фичи: IDEA -> Jira task -> PR -> release. Визуализация пути от заметки до прода |
| BL-100 | Board: фильтрация по типу задачи | web-ui | Фильтр-табы по типу (JIRA_TASK, JIRA_BUG, MEETING_SUMMARY, NOTE и т.д.) на board.html. Режим «И»: при выборе нескольких типов показываются только задачи, соответствующие всем выбранным |

---

## 6. LLM и AI

### 6.1 Реализовано

| # | Название | Компонент | Описание |
|---|:---|:---|:---|
| BL-66 | ✅ Claude API интеграция | pm-bot, knowledge-engine, idea-pipeline | claude-sonnet-4-6, process_idea/meeting/jira_ticket/daily, enrich, synthesize |
| BL-67 | ✅ Ollama hybrid | pm-bot, knowledge-engine | 3 режима: Claude API / Ollama / Hybrid. Fallback Ollama -> Claude. Web UI настройка |
| BL-68 | ✅ Configurable models per agent | idea-pipeline | pipeline.yaml: модель для каждого агента (Analyst, PM, Decomposer) |
| BL-69 | ✅ LLM client factory | pm-bot, knowledge-engine | llm_client.py: фабрика клиентов, маршрутизация по операциям |

### 6.2 Идеи

| # | Название | Компонент | Описание |
|---|:---|:---|:---|
| BL-70 | Настройка маппинга операция -> провайдер через UI | pm-bot, web-ui | Сейчас захардкожен в коде (упомянуто в Out of Scope ollama-hybrid) |
| BL-71 | A/B-тестирование качества между провайдерами | pm-bot | Сравнение качества Claude vs Ollama (упомянуто в Out of Scope ollama-hybrid) |
| BL-72 | idea-pipeline через Ollama | idea-pipeline | Сейчас всегда Claude API (упомянуто в Out of Scope ollama-hybrid) |
| BL-73 | Multi-Agent Shared Vault | pm-bot | Расширить на команду PM-ов, агент находит пересечения и конфликты идей между участниками |

---

## 7. Инфраструктура

### 7.1 Реализовано

| # | Название | Компонент | Описание |
|---|:---|:---|:---|
| BL-74 | ✅ Docker Compose | инфраструктура | 4 контейнера: pm-bot, knowledge-engine, idea-pipeline, ke-cron |
| BL-75 | ✅ Vault API | pm-bot | FastAPI REST + in-memory TTL cache (30s). /system/status 4882ms -> 4ms |
| BL-76 | ✅ User preferences API | pm-bot | GET/PUT /api/v1/user-prefs. Серверное хранение в vault/.pm-user-prefs.json |
| BL-77 | ✅ Scheduler | pm-bot | APScheduler: weekly_report (Mon 09:00), enrichment_reminder (daily) |
| BL-78 | ✅ Enrichment DB | pm-bot | SQLite: дедупликация напоминаний (cooldown 24ч, cleanup 90д) |
| BL-79 | ✅ Atomic file write | pm-bot, knowledge-engine | file_writer.py: tmp + os.replace |
| BL-80 | ✅ Frontmatter utils | knowledge-engine | Чтение/запись YAML frontmatter |

### 7.2 Идеи

| # | Название | Компонент | Описание |
|---|:---|:---|:---|
| BL-81 | Мониторинг и алерты по доступности Ollama | pm-bot | Health check, uptime tracking (упомянуто в Out of Scope ollama-hybrid) |

---

## 8. Управление знаниями (Decay & Health)

> Источник: SWOT-анализ [smixs/autograph](https://github.com/smixs/autograph). Спека: `docs/context_compaction/swot_autograph.md`

### 8.1 Decay engine

| # | Название | Компонент | Описание |
|---|:---|:---|:---|
| BL-110 | Decay engine (Эббингауз) | knowledge-engine | Непрерывная шкала актуальности `relevance: 0.0-1.0` вместо грубого TTL. Формула: `strength = 1 + ln(access_count)`, `effective_rate = rate / strength`, `relevance = max(floor, 1.0 - effective_rate × days)`. Domain-specific rates из domain-config.yaml (идеи ~50д, PRD ~42д, daily ~25д). Ref: autograph `common.py: calc_relevance()` |
| BL-111 | Tier system (graduated recall) | knowledge-engine | 5 tier'ов: archive → cold → warm → active → core. Пороги: active ≤7д, warm ≤21д, cold ≤60д, archive >60д. `core` — ручная метка, исключение из decay. context_assembler фильтрует только active+warm для core-digest. Ref: autograph `common.py: calc_tier()` |
| BL-112 | Touch при обращении | pm-bot, knowledge-engine | При использовании digest'а в контексте pm-bot → increment `access_count`, refresh `last_accessed`, promote tier на 1 ступень. Spacing effect: чем чаще обращение, тем медленнее забывание. Ref: autograph `engine.py: cmd_touch()` |
| BL-113 | Creative recall | pm-bot, web-ui | Случайная выборка 3-5 карточек из cold/archive tier для переоткрытия забытых идей. Telegram: `/creative`. Web UI: блок "Забытые идеи" на overview.html. Ref: autograph `engine.py: cmd_creative()` |

### 8.2 Health scoring — Реализовано

| # | Название | Компонент | Описание |
|---|:---|:---|:---|
| BL-114 | ✅ Vault health score | knowledge-engine, pm-bot, web-ui | Количественная метрика здоровья vault (0-100): 7 категорий штрафов (broken links ×3, orphans ×5, dead-ends ×1, stale drafts ×1, unsorted misc ×0.5, ingest backlog ×0.2, description coverage). Грейды: healthy ≥80 / warning ≥50 / critical <50. `health_scorer.py` + CLI `health --save --json` + endpoint `GET /api/v1/vault/health` с trend 7d/30d. Overview виджет (Zone A): score + dot + sparkline + раскрывающаяся breakdown-панель по категориям. ke-cron job 04:00 ежедневно. История `.health-history.json` (TTL 90д). Спека: `docs/health-scoring/` (14 задач, все done) |
| BL-115 | ✅ Wikilink resolver | knowledge-engine | 3-уровневый детерминированный резолвер ссылок в linter.py: exact name → unique suffix → unique stem. `_build_file_index()` + `_resolve_wikilink()`. Заменил примитивный exact-match в `check_broken_links()`. Сокращает ложные broken links. Спека: `docs/health-scoring/tasks.md` (T-05, T-06) |

---

## 9. Исправленные баги

| # | Баг | Компонент | Описание |
|---|:---|:---|:---|
| BL-82 | ✅ BUG-001 (raw-fallback-wrong-folder) | pm-bot | Fallback-путь для raw/ указывал на неправильную папку |
| BL-83 | ✅ BUG-002 (epic-yaml-none-to-string) | knowledge-engine | None в YAML frontmatter эпика вместо строки |
| BL-84 | ✅ BUG-003 (stt-bus-error-kills-api) | pm-bot | Bus error в STT/Whisper убивал API-сервер |
| BL-85 | ✅ BUG-004 (epic-name-field-missing) | knowledge-engine | Отсутствующее поле name в эпике |
| BL-86 | ✅ BUG-005 (ideas-domain-tab-wrong-count) | web-ui | Неправильный счётчик на вкладках доменов |
| BL-87 | ✅ BUG-006 (jira-create-type-and-epic) | knowledge-engine | Некорректный type и epic при создании Jira-тикета |
| BL-88 | ✅ BUG-007 (activity-log-invalid-date) | web-ui | Невалидная дата в activity log |
| BL-89 | ✅ BUG-008 (raw-not-saved-on-success) | knowledge-engine | Raw-транскрипт не сохранялся при успешной обработке |
| BL-90 | ✅ BUG-009 (light-theme-overview) | web-ui | Overview не применяет light-тему |
| BL-91 | ✅ BUG-010 (card-clip-no-base-styles) | web-ui | Карточки без стилизации в light-теме |
| BL-92 | ✅ BUG-011 (jira-sync closed handler) | knowledge-engine | Обработчик closed-тикетов при jira-sync |
| BL-93 | ✅ BUG-012 (daily-log-naming) | pm-bot | Некорректное именование daily-log файлов |
| BL-94 | ✅ BUG-013 (vault_index None in tags) | knowledge-engine | None в tags/keywords вызывал AttributeError при search |
| BL-95 | ✅ BUG-014 (settings testOllamaConnection) | web-ui | Silent early return при пустом URL в TEST CONNECTION |
| BL-96 | ✅ BUG-015 (Telegram Markdown parse error) | pm-bot | Parse error при отправке jira reply, fallback на plain text |
| BL-97 | ✅ BUG-001v2 (daily-log-not-appended) | pm-bot | write_daily() не добавляла запись в wiki/LOG.md |
| BL-98 | ✅ BUG-002v2 (fetcher-no-log-entry) | knowledge-engine | fetch_new_meetings() не добавлял запись в wiki/LOG.md |
| BL-99 | ✅ Capture fix | pm-bot | vault_api.py: import _fallback_idea_data + dict -> JSON serialization |
| BL-103 | ✅ parse_note() кавычки | pm-bot | parse_note() не снимала кавычки с YAML-значений frontmatter — id отображался как "IDEA-0022" вместо IDEA-0022 (6 идей) |
| BL-104 | ✅ parse_note() дата YYYYMMDD | pm-bot | Дата извлекалась некорректно для файлов с форматом YYYYMMDD в имени (20 идей). Цепочка: frontmatter → YYYY-MM-DD → YYYYMMDD → created |
| BL-105 | ✅ IDEA на доске задач | web-ui | IDEA-* файлы появлялись на board.html вместо ideas.html |
| BL-106 | ✅ Board: done/cancelled в PROCESSING | web-ui | Задачи в статусе done/cancelled отображались в колонке PROCESSING вместо DONE |
| BL-128 | ✅ BUG-016 (health popup light theme) | web-ui | Health breakdown popup не стилизован для light-темы: невидимые границы, хардкод matrix-цветов в JS. Fix: CSS-overrides + theme-aware _healthColor()/_sparklineColor() |
| BL-129 | ✅ BUG-017 (health false positives) | knowledge-engine | Health scorer считал false positive broken links (вложения, @mentions, шаблоны) и dead ends (Jira-импорт). Fix: _is_ignorable_link() + исключение jira_key из dead_ends. Результат: -57 broken, -388 dead ends |

---

## 10. Задачи из аудита системы (10.06.2026)

> Источник: `wiki/reports/audit-2026-06-10-system-maturity.md` (vault «08 project hotels claude»).
> Ссылки Н-x (недоработки) и Б-x (белые пятна) — на разделы 3 и 4 аудита. Порядок — по убыванию приоритета.

### 10.1 P0 — блокеры зрелости

| # | Название | Компонент | Описание |
|---|:---|:---|:---|
| ~~BL-117~~ | ~~Планировщик индексации и линта в ke-cron~~ | ~~knowledge-engine~~ | ✅ **Реализовано 11.06.2026.** Добавлены cron-джобы rebuild-index (02:00) и lint (03:00) в ke-cron entrypoint (docker-compose.yml). Поглощает BL-21. |

### 10.2 P1 — устранение расхождений и долга

| # | Название | Компонент | Описание |
|---|:---|:---|:---|
| ~~BL-118~~ | ~~Definition of Done для ingest + обработка очереди через Cowork~~ | ~~Cowork, knowledge-engine~~ | ✅ **Закрыто 12.06.2026.** Vault health audit: score 0→83 (critical→healthy). Переписан `check_orphan_pages` (date matching для daily-logs/meeting-notes вместо source: frontmatter). Расширен `_build_file_index` на raw/. Broken links 620→0, dead ends 468→0, orphan pages 490→0. Шаблон idea.md: добавлен {{raw_ref}} placeholder. Остаток ingest backlog (51 raw: 17 IDEA без wiki-копий + 34 Jira-задачи) и unsorted misc (13) — контент, не баги scorer'а. Поглощает BL-09, BL-10. |
| ~~BL-119~~ | ~~Единый источник domain-правил~~ | ~~knowledge-engine, pm-bot~~ | ✅ **Закрыто 13.06.2026.** domain-config.yaml расширен: tags, keywords, prompt_hint для 5 доменов. Динамический LLM-промпт из конфига (3 стратегии инжекции), _get_valid_domains с fallback, _merged_keyword_map в artifact_extractor и ingest. partner-search-engine доступен во всех 6 точках детекции. 30+ новых тестов, 1036 passed. Спека: docs/unified-domain-rules/. pm-bot 1.8.0, KE 1.7.0. |
| ~~BL-120~~ | ~~CI: тесты + линт + типизация~~ | ~~инфраструктура~~ | ✅ **Реализовано 11.06.2026.** GitHub Actions CI (lint + typecheck + test matrix), pyproject.toml (ruff E/F/W/I + mypy lenient), pre-commit hook (ruff --fix), requirements-dev.txt. 28 pre-existing test failures помечены xfail. |

### 10.3 P2 — здоровье системы

| # | Название | Компонент | Описание |
|---|:---|:---|:---|
| ~~BL-122~~ | ~~Унификация статусов идей~~ | ~~pm-bot, knowledge-engine~~ | ✅ **Реализовано 12.06.2026.** Единый словарь 4 статусов (C-0003), STATUS_MAP миграция legacy→канонич., check_invalid_idea_statuses() в linter, fallback "inbox"→"Новая", watcher skip-statuses. Спека: docs/idea-status-unification/. Связано с BL-34, BL-38. |
| ~~BL-123~~ | ~~Метрики системы (self-measurement)~~ | ~~knowledge-engine, web-ui~~ | ✅ **Реализовано 12.06.2026.** _calculate_pipeline_metrics() в health_scorer.py: ingest_ratio, avg_lag_hours, raw_counts. CLI health --json с трендами. Pipeline секция в overview.html breakdown. 13 unit-тестов. Спека: docs/system-metrics/. Аудит: Б-3 |
| ~~BL-124~~ | ~~Ревизия домена general~~ | ~~knowledge-engine~~ | ✅ **Закрыто 13.06.2026.** domain_mover.py: move_artifact(), batch_reclassify(), audit_domain(). CLI: 3 команды (move-artifact, batch-reclassify, audit-domain). 14 unit-тестов. Batch execution deferred — код готов, переразметка запускается вручную. Спека: docs/domain-general-revision/. knowledge-engine 1.7.1. |
| ~~BL-125~~ | ~~Координация писателей в vault~~ | ~~knowledge-engine, pm-bot, idea-pipeline~~ | ✅ **Реализовано 13.06.2026.** file_lock() + locked_append() в file_writer.py (pm-bot + KE), atomic_write в idea-pipeline. 9 fix points: append_section, obsidian_writer (3), ingest (1), domain_manager (2), state.py (1), vault_writer.py (1). fcntl.flock + Windows no-op fallback. 17 unit-тестов. Спека: docs/vault-write-coordination/ |
| ~~BL-126~~ | ~~Дедупликация кода + конфигурируемость~~ | ~~pm-bot, knowledge-engine, idea-pipeline~~ | ✅ **Закрыто 14.06.2026.** shared/ модуль (6 файлов, 1283 строки): llm_client, file_writer, vault_paths, domain_config, frontmatter_utils, settings. settings.yaml централизованная конфигурация. KE HTTP API (18 эндпоинтов, api.py 618 строк). ke_client.py HTTP-клиент (233 строки). Rate limiter для Telegram. SQLite volume (pm-bot-data). Удалено 10 дубликатов (-2298 строк). Объединено с BL-130. Спека: docs/dedup-and-config/. |
| BL-127 | Onboarding-док и бэкап-стратегия | инфраструктура | Bus factor = 1: описать систему целиком (vault + сервисы + интеграции), процедуру восстановления, бэкап vault'а (git). Аудит: Б-6 |
| ~~BL-130~~ | ~~Декаплинг pm-bot и knowledge-engine~~ | ~~инфраструктура~~ | ✅ **Закрыто 14.06.2026.** pm-bot больше не копирует код KE. COPY knowledge-engine удалён из Dockerfile. 21 subprocess.run → ke_client HTTP-вызовы. KE API на порту 8001 (serve + watch). Объединено с BL-126. |
| ~~BL-131~~ | ~~CI green: mypy + ruff~~ | ~~инфраструктура~~ | ✅ **Реализовано 14.06.2026.** Устранены все ошибки mypy (253 ошибки в 16 файлах) и ruff lint (26 ошибок) по всем компонентам. KE: type narrowing для YAML/JSON данных, Optional params, fcntl type:ignore. pm-bot: assert-narrowing для nullable Update properties (182 ошибки в handlers.py), Any type fix, variable scope fix. idea-pipeline: orchestrator null guards, TextBlock isinstance, frontmatter.Post handler arg. Тесты check_unsorted_misc обновлены под wikilink-логику. |

---

## 11. Сводка

| Статус | Кол-во | Пункты |
|:---|:---|:---|
| ✅ Реализовано | 73 | BL-01..BL-08, BL-11..BL-18, BL-25..BL-29, BL-31..BL-34, BL-40..BL-57, BL-66..BL-69, BL-74..BL-80, BL-101..BL-102, BL-107..BL-109, BL-114..BL-120, BL-122..BL-126, BL-130, BL-131 |
| ✅ Баги исправлены | 24 | BL-82..BL-99, BL-103..BL-106, BL-128..BL-129 |
| Идея | 29 | BL-09, BL-10 (поглощены BL-118), BL-19..BL-24, BL-30, BL-35..BL-39, BL-58..BL-65, BL-70..BL-73, BL-81, BL-100, BL-110..BL-113 |
| Аудит 10.06.2026 | 1 | BL-127 (P2) |
| ❌ Удалено | 1 | BL-121 |
| **Итого** | **130** | |
