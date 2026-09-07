# Бэклог -- PM Assistant

**Версии:** pm-bot 1.29.0 / knowledge-engine 1.25.0 / idea-pipeline 1.3.0 / web-ui 1.33.0 / shared 0.7.5
**Обновлён:** 07.09.2026 (BL-235 — Редактирование business_context через Settings UI)
**Бэклог:** реализованные фичи (116), баги (36), идеи (69), итого (221)

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
| BL-133 | ✅ Ссылка на raw-источник в протоколе | knowledge-engine | source_file в frontmatter + wikilink на raw-файл в footer протокола. _inject_source_file() в fetcher.py |
| BL-134 | ✅ Линковка Jira-задач во всех протоколах | knowledge-engine | Jira sync для ВСЕХ типов протоколов (daily, sync, review, planning, other). Переименование sync_daily_jira_keys → sync_jira_keys + backward-compatible alias |
| BL-24 | ✅ Decision Journal | pm-bot | Единый реестр решений из протоколов встреч: API endpoint GET /api/v1/decisions + Web UI страница decisions.html + виджет на overview. Полнотекстовый поиск, фильтрация по домену/дате, expand карточки с контекстом |
| BL-145 | ✅ Meeting Processing Queue | knowledge-engine, pm-bot | Трёхфазная файловая очередь обработки протоколов (`raw/meeting-queue/{pending,processing,done,failed}/`): Fetch (IMAP + transcript_watcher → enqueue в pending/ без LLM), Process-воркер (watchdog PollingObserver near-realtime + cron-страховка /10мин, по одному юниту, LLM через fallback chain max_attempts=5, validate_protocol до записи в wiki), Queue (атомарный claim через rename, reclaim_stuck, status_counts). shared/meeting_queue (enqueue-ядро) + call_detailed (provider_history). CLI process-queue/queue-watch/queue-status, API GET /meeting-queue/status + POST /process-queue. ADR-005. E2E verified на Docker 30.06.2026 |
| BL-147 | ✅ Слой 1' Context Compaction (Phase 1+2) | knowledge-engine, pm-bot | Phase 1: offline-генерация LLM-дайджестов wiki/ → llm_wiki/ (3 уровня, body_hash, decay). Phase 2: DigestHandler в watcher (auto-digest при DIGEST_ENABLED=1), context_assembler (waterfall сборка: one-liners→core→extended, kill switch DIGEST_CONTEXT_SOURCE), 3 API endpoints (digest/generate, bulk, status), digest context injection в process_idea и weekly report, enrich_creative_recall. 80 unit-тестов, 11 API тестов |
| BL-151 | ✅ llm_wiki как контекст для Claude Cowork | knowledge-engine | Расширение BL-147: cowork_context.py — детерминированная генерация _cowork-session.md (5 секций: дейли, задачи, эпики, решения, активность). CLI cowork-context, API POST /api/v1/cowork-context, cron 01:00 ежедневно. system_log: process type "cowork-context" |

### 2.2 Идеи

| # | Название | Компонент | Описание |
|---|:---|:---|:---|
| BL-19 | Генерация summary через Claude для клиппингов | knowledge-engine | v1 ingest копирует содержимое as-is, summary через LLM -- следующий шаг (упомянуто в Out of Scope ingest-clippings) |
| BL-20 | Автоматическое обогащение knowledge-файлов | knowledge-engine | Enrichment для созданных через ingest knowledge-файлов (упомянуто в Out of Scope ingest-clippings) |
| BL-21 | Ночной линтер | knowledge-engine | Проверка битых ссылок, сирот, протухших черновиков по cron (упомянуто в analysis миграции) |
| BL-22 | Enrichment с семантическим поиском | knowledge-engine | При capture автоматически линковать к похожим существующим заметкам в vault |
| BL-23 | Action Items Aggregator | knowledge-engine | Извлечь task/@assignee из протоколов -> агрегация по людям, трекинг overdue |
| BL-146 | Temporal Summarization — периодические отчёты по wiki | knowledge-engine | Cron-job (раз в неделю/месяц): собирает все wiki-документы за период (встречи, дейли, идеи, решения), отправляет в LLM, генерирует суммаризацию → `wiki/reports/weekly/YYYY-WW.md` / `monthly/YYYY-MM.md`. Отвечает на вопросы "что сделали за май", "какие решения в Q1". Один дополнительный пайплайн поверх существующей архитектуры. Связан с BL-23 (Action Items) и BL-24 (Decision Journal) |
| BL-233 | BM25 поиск (SQLite FTS5) | pm-bot, knowledge-engine | Замена текущего keyword-based `_SearchIndex` в vault_api.py на BM25 через SQLite FTS5. In-memory индекс при старте, инвалидация по watchdog/TTL. Колонки: title (вес ×3), meta (name/domain/tags, вес ×2), body. Unicode-токенизация. Улучшает Ctrl+K поиск и API `/search`. Inspiration: iva (github.com/smixs/iva) — аналогичный подход с in-memory FTS5. Не требует внешних зависимостей (SQLite встроен в Python). Связан с BL-153 (семантический поиск — следующий этап) |
| BL-234 | Graph reranking поиска по wikilinks | pm-bot, knowledge-engine | Ребустинг результатов поиска на основе графа wikilinks. После BM25 retrieval: BFS до 2 хопов от top-результатов, буст связанных артефактов с учётом количества backlinks (authority). Требует: (1) построение графа связей при индексации vault (scan `[[wikilinks]]` из всех .md), (2) reranking pipeline после BM25. Штраф для `status: Отсев`. Coverage-метрика (% покрытия query terms). Inspiration: iva — graph reranking поверх BM25. **Предварительное условие:** качественные wikilinks (текущий enricher.py — keyword matching, возможно потребуется LLM-валидация связей перед внедрением reranking). Зависит от BL-233 (BM25 как base retrieval) |
| BL-153 | Семантический поиск + векторное хранилище | knowledge-engine, pm-bot | Внедрение семантического поиска по смыслу (а не по ключевым словам) поверх vault. **Триггер внедрения: vault достиг 3000+ артефактов И появилась потребность в кросс-доменных запросах без явных тегов** (пример: «найди всё, что связано с проблемой конверсии»). До этого момента — не реализовывать. Архитектура: (1) Эмбеддинги считаются по `llm_wiki/` one-liner'ам и core-digest'ам (BL-147), не по сырым wiki-файлам — это сокращает объём и повышает качество векторов. (2) Хранилище — ChromaDB (embedded, без сервера, один файл `.chroma/`) или LanceDB — оба работают локально без Docker-сервиса. (3) Индекс перестраивается инкрементально при обновлении llm_wiki/ (тот же триггер, что и digest-генерация). Применение: enricher.py (связи между идеями по смыслу вместо keyword matching), context_assembler.py в pm-bot (выбор релевантных digest'ов по смыслу запроса), endpoint `/search` в vault_api.py (качественнее текущего _SearchIndex). Зависит от BL-147 (llm_wiki/ как источник текстов для эмбеддингов) и BL-152 (index_store.py как инфраструктура инкрементального обновления). |

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
| BL-173 | ✅ TTL для уведомлений Meeting Fetcher | knowledge-engine | Автоудаление summary-уведомления Meeting Fetcher через 5 минут. threading.Timer + deleteMessage API |
| BL-189 | ✅ News Moderator — агентная цепочка анализа новостей | knowledge-engine, shared | Агентная цепочка: digest JSON → скоринг → анализ (AgentLoop + QualityGate) → dispatch идея/отчёт → извлечение идей из отчётов → persistent memory (SQLite) → weekly trend detection. 6 модулей (~2400 LOC), 6 промптов, 3 LLM operation group, 194 теста |

### 3.2 Идеи

| # | Название | Компонент | Описание |
|---|:---|:---|:---|
| BL-30 | Competitive Spy | knowledge-engine | Мониторинг App Store отзывов, changelogs конкурентов, вакансии -> сигналы в Inbox |
| BL-150 | Jira sync из попапа задачи | web-ui, pm-bot | Кнопка синхронизации выбранной задачи с Jira прямо из попапа детальной информации (task-drawer). Обновление полей задачи из Jira или push изменений в Jира без перехода на другие страницы |
| BL-196 | Cowork Integration — deep research через Claude Code | knowledge-engine, инфраструктура | Интеграция Research Runner (BL-194) с Claude Cowork для Variant A (deep research с WebSearch). **Контракт задания:** JSON в `raw/inbound/cowork-tasks/` с полями topic, questions, scope, signal_source, output_path, naming_convention, expected_format. **Механизм запуска:** watchdog/cron на `cowork-tasks/`, запуск Claude Code CLI (`claude --print`) с deep-research skill. **Контракт отчёта:** markdown в `wiki/reports/report-{slug}-{YYYY-MM-DD}.md`, frontmatter `type: research-report` — совместимый с glob в `check_pending_reports()`. **CLAUDE.md для Cowork-агента:** инструкции формата отчёта, naming convention, использование WebSearch, fallback при ошибке поиска. **Handoff:** polling `wiki/reports/` (существующий `check_pending_reports`), таймаут `report_wait_timeout_minutes`. **Fallback:** при `report_method: cowork` и отсутствии инфраструктуры → warning + fallback на internal. Зависит от BL-194 (Research Runner internal), BL-154 (Claude CLI в Docker) |

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
| BL-60 | ✅ Keyword Search | web-ui | Полнотекстовый поиск по vault: overlay Ctrl+K, debounce 300ms, фильтры по типу, artifact_id matching (+10 score) |
| BL-61 | ✅ Inline Editing | web-ui | Click-to-edit полей (status, domain, priority, tags, tier) в drawer'ах + body editor (split view markdown/preview). PATCH /artifact/{filename}/field и /body endpoints |
| BL-64 | ✅ Scroll-to-Card Highlight | web-ui | ?highlight=filename → авто-скролл + cyan/gold pulse анимация на карточке. Интеграция с поиском Ctrl+K |
| BL-135 | ✅ Forgotten Gems Popup | web-ui | Popup деталей артефакта на decay.html: метаданные + rendered Markdown body через marked.js |
| BL-136 | ✅ Vault Health на dashboard | web-ui | Health-карточка на dashboard.html: score, грейд, тренд. Popup с детализацией по категориям штрафов (broken links, orphans, dead ends) |
| BL-137 | ✅ Редизайн CAPTURE_TERMINAL | web-ui | Редизайн capture drawer (chat-style терминал на board.html, ideas.html). В Settings переключатель «Тип терминала»: простой / расширенный |
| BL-158 | ✅ Фильтрация моделей OpenRouter в Settings и Playground | web-ui, pm-bot, shared | Searchable dropdown (`searchable-model-select` в components.js) вместо `<select>` для выбора моделей OpenRouter: текстовый фильтр по name/id (case-insensitive), autofocus, outside-click close, compact-режим для inline fallback-цепочки. 3 места: settings.html (глобальный OPENROUTER_MODEL + per-step в fallback chain), playground.html (при провайдере openrouter). CSS в общем style.css. Бэкенд: `GET /playground/providers` теперь отдаёт live-список моделей через `list_models()` (TTL-кэш 1ч) вместо хардкода. Попутно: BUG-020 (Nemotron parse error) — детальное логирование raw-ответа в openrouter_client.py. Связано с BL-155, BL-156 |
| BL-159 | ✅ Экспорт markdown-отчётов в PDF | web-ui, pm-bot | Кнопка EXPORT_PDF на report.html. Endpoint POST /api/v1/reports/{filename}/pdf. WeasyPrint + markdown-it-py рендеринг, шрифт Inter, монохромные emoji (Noto Emoji), кастомный CSS (pdf-export.css) |
| BL-161 | ✅ Поиск и фильтрация отчётов | web-ui, pm-bot | report.html: поиск по имени/заголовку (input, case-insensitive) + фильтрация по типу отчёта (12 типов из frontmatter `type:`). Фильтр-чипы с каунтерами, dynamic computed, watcher авто-выбора. Бэкенд: `_extract_report_type()` + поле `type` в ответе `/api/v1/reports`. 20 unit-тестов. Спека: docs/report-search-filter/ |
| BL-162 | ✅ Roadmap: просмотр тела эпика в popup | web-ui, pm-bot | roadmap.html: кнопка-тогглер SHOW_BODY / SHOW_TICKETS в drawer эпика. Полный markdown body рендерится через marked.js. Бэкенд: поле `body` добавлено в ответ GET /api/v1/epics. Сброс режима при смене эпика. Спека: docs/roadmap-epic-body/ |
| BL-168 | ✅ Реорганизация меню + страница TODAY | web-ui, pm-bot | Реорганизация sidebar-навигации: 4 группы (Рабочий день, Знания, Мониторинг, Система), collapse группы «Система». Новая страница TODAY — стартовая страница рабочего дня (Morning Digest, фокус дня, встречи, TODO, отчёты, новости). CalDAV-интеграция Яндекс Календаря. Парсеры vault-файлов. API для TODO CRUD и TODAY-данных. DS v2 CSS-токены. Спека: docs/BL-168_menu-reorganization/ |
| BL-172 | ✅ Настройка CalDAV в Settings UI | web-ui, pm-bot | Секция «CALENDAR» на settings.html: username, app password, timezone, URL. Сохранение через user-prefs API. TEST CONNECTION → POST /api/v1/test-caldav. Статус подключения (connected/disabled/error). calendar_client.py: динамические credentials из user-prefs с fallback на env. Маскировка пароля в GET. Спека: docs/BL-172_caldav-settings-ui/ |
| BL-188 | ✅ Auto-refresh встреч на TODAY | web-ui | today.html: автоматическое обновление блока встреч (CalDAV) каждые 15 минут через setInterval. loadMeetings(true) с инвалидацией CalDAV-кэша. cleanup в beforeUnmount. Безусловный (без проверки refreshMode). Спека: docs/BL-188_today-meetings-autorefresh/ |
| BL-195 | ✅ Research Queue UI — мониторинг исследований | web-ui, pm-bot, knowledge-engine | Pipeline graph страница `research.html` в стиле n8n: 7 узлов (2 ghost + 5 основных), SVG edges с dash-offset анимацией, drawer для деталей задания. 3 API endpoint (status, run, retry) через полный proxy-chain (KE → ke_client → vault_api → api.js). Completeness badges, auto-refresh 60s, responsive. Спека: docs/BL-195_research-queue-ui/ |
| BL-230 | ✅ AI-агент в редакторе идеи | web-ui, pm-bot | В body-editor (редактор идеи) добавлен режим AI-агента — чат с LLM для доработки идей. Тогл «Режим работы с ИИ», 3-колоночный layout, чат-интерфейс. Бизнес-контекст и текст идеи передаются автоматически. Quick-action кнопки (усилить проблему, гипотеза, KPI, PRD). Настройка модели в Settings: секция AI AGENT (Claude / Ollama / OpenRouter). Langfuse трейсинг (trace name: ai-agent-chat). User-prefs: поля ai_agent_provider, ai_agent_model. Endpoint POST /api/v1/ai-agent/chat. Спека: docs/BL-230_ai-agent-editor/ |
| BL-231 | ✅ Ресайз колонок в body-editor | web-ui, pm-bot | Drag-handle между колонками в body-editor (6px, подсветка при hover). Ресайз в 2-колоночном (editor + preview) и 3-колоночном (+ AI чат) режимах. Пропорции сохраняются в user-prefs (editor_col_split_2, editor_col_split_3). Двойной клик по handle — сброс к дефолтным пропорциям. Блокировка выделения текста при drag. Responsive: handles скрыты на экранах < 1024px |
| BL-197 | ✅ Управление промптами через Settings UI | web-ui, pm-bot, knowledge-engine, idea-pipeline | Подсекция PROMPTS в Settings: просмотр, редактирование, hot-reload и сброс всех 32 промптов (5 pm-bot, 24 KE, 3 pipeline). Proxy-архитектура: browser → vault_api → KE/Pipeline API. Дефолты через *.txt.default |
| BL-235 | ✅ Редактирование business_context через Settings UI | web-ui, pm-bot, knowledge-engine | Секция BUSINESS CONTEXT в settings.html: textarea для редактирования описания бизнес-контекста. Хранение в user-prefs с seed из файла `business-context-brief.md`. 3 потребителя (signal_orchestrator, research_runner, AI-agent) читают из prefs с fallback на файл. KE получает через HTTP API (_load_llm_prefs). 11 новых тестов. Спека: docs/BL-235_business-context-settings/ |

### 5.2 Идеи

| # | Название | Компонент | Описание |
|---|:---|:---|:---|
| BL-58 | Web UI для knowledge-файлов | web-ui | Просмотр клиппингов и knowledge-файлов (упомянуто в Out of Scope ingest-clippings) |
| BL-59 | Mermaid Diagrams | web-ui | Рендеринг Mermaid-диаграмм в body PRD/Epic |
| BL-62 | Bulk Operations | web-ui | Мультивыбор карточек на доске для массовых действий |
| BL-63 | Syntax Highlighting | web-ui | highlight.js для блоков кода в body артефактов |
| BL-65 | Time Machine | web-ui | Таймлайн фичи: IDEA -> Jira task -> PR -> release. Визуализация пути от заметки до прода |
| BL-100 | Board: фильтрация по типу задачи | web-ui | Фильтр-табы по типу (JIRA_TASK, JIRA_BUG, MEETING_SUMMARY, NOTE и т.д.) на board.html. Режим «И»: при выборе нескольких типов показываются только задачи, соответствующие всем выбранным |
| BL-148 | Запуск fetch_meetings из Settings | web-ui, pm-bot | Кнопка на странице Settings для ручного запуска fetch_meetings (обработка почты на новые транскрибации). Индикатор статуса выполнения. Требует прокси-endpoint в vault_api.py → ke_client.fetch_meetings() |
| BL-169 | Диагностический endpoint для UI-страниц | pm-bot | `GET /api/v1/diagnostics/today` — проверяет все API-зависимости страницы TODAY за 1 запрос: статус каждого endpoint, наличие данных, дата последнего отчёта. Team Lead вызывает перед объявлением готовности. Расширяемо на другие страницы (`/diagnostics/{page}`). Мотивация: BL-168 live-testing (20 ошибок после "готово") |
| BL-170 | DOM-валидация frontend-страниц (Node.js) | web-ui | Node.js скрипт валидации HTML/Vue: проверка CSS-классов на конфликты (отсутствие prefix), проверка `v-html` vs `{{ }}` для markdown-контента, проверка что все `@click` ссылаются на существующие методы. Расширение test-today-node.js. Мотивация: BL-168 — 6 из 20 ошибок были конфликты классов и неверные привязки |
| BL-171 | Visual regression testing (Playwright) | web-ui, инфраструктура | Playwright + фикстурный vault: headless-браузер открывает каждую страницу, делает скриншоты блоков, сравнивает с baseline (pixel diff). Клик по интерактивным элементам → скриншот popup. Отчёт: список блоков с % отклонения. Docker-контейнер с тестовым vault. Мотивация: BL-168 — ручное тестирование 10 страниц неэффективно |


---

## 6. LLM и AI

### 6.1 Реализовано

| # | Название | Компонент | Описание |
|---|:---|:---|:---|
| BL-66 | ✅ Claude API интеграция | pm-bot, knowledge-engine, idea-pipeline | claude-sonnet-4-6, process_idea/meeting/jira_ticket/daily, enrich, synthesize |
| BL-67 | ✅ Ollama hybrid | pm-bot, knowledge-engine | 3 режима: Claude API / Ollama / Hybrid. Fallback Ollama -> Claude. Web UI настройка |
| BL-68 | ✅ Configurable models per agent | idea-pipeline | pipeline.yaml: модель для каждого агента (Analyst, PM, Decomposer) |
| BL-69 | ✅ LLM client factory | pm-bot, knowledge-engine | llm_client.py: фабрика клиентов, маршрутизация по операциям |
| BL-138 | ✅ OpenRouter для транскрибаций | pm-bot, knowledge-engine, shared, web-ui | openrouter_client.py (shared/), call_transcription() в llm_client.py — fallback chain OpenRouter → Ollama → Claude API. Settings UI: toggle DEFAULT/OPENROUTER, model dropdown (6 моделей), test connection. Endpoints: /openrouter-key-status, /openrouter-models, /test-openrouter. Env: OPENROUTER_API_KEY |
| BL-140 | ✅ OpenRouter для enrichment протоколов | knowledge-engine, shared | Унификация LLM-вызовов: call_with_fallback() + call_transcription() → единый call() с настраиваемыми fallback-цепочками. Enrichment протоколов маршрутизируется через те же цепочки, что и транскрибация |
| BL-141 | ✅ Настраиваемые fallback-цепочки провайдеров | shared, pm-bot, web-ui, knowledge-engine | OpenRouter как альтернатива для capture. 3 группы операций (Capture, Transcription, Analysis) с per-group fallback-цепочкой. Drag-and-drop в Settings UI. Обратная совместимость с legacy prefs. 21 unit-тест |
| BL-142 | ✅ LLM Playground — страница тестирования моделей | web-ui, pm-bot | playground.html: чат-интерфейс для тестирования LLM. Выбор провайдера (Claude/Ollama/OpenRouter), модели, температуры. API: GET /playground/providers, POST /playground/chat. Sidebar ссылка PLAYGROUND |
| BL-155, BL-156 | ✅ Множественный выбор моделей OpenRouter + динамический список из API | shared, pm-bot, web-ui | `shared/openrouter_client.py::list_models()` с live-запросом и TTL-кэшем (1ч fallback). Мультимодельные fallback-цепочки: несколько шагов OpenRouter подряд с разными моделями, storage в объектном формате {provider, model}. `shared/llm_client.py::_normalize_step()` для обратной совместимости. `PUT /api/v1/user-prefs` валидирует openrouter-шаги (обязательна непустая model), дедупирует смежные дубли. `GET /api/v1/user-prefs` нормализует в объектный формат для UI. `settings.html`: редактор цепочек с инлайн-селектором модели, пометка fallback-списка (источник live|fallback). Backoff 0.7s между смежными openrouter-шагами после 429. Логирование используемой модели в system-log. Спека: docs/openrouter-model-selection/ |
| BL-190 | ✅ Agent Observability — мониторинг и аналитика агентной цепочки | knowledge-engine, shared | Langfuse e2e trace для Signal Moderator, 3 HTTP-endpoints диагностики (signals/runs, signals/runs/{id}, signals/stats), CLI signal-status, persistence решений агентов (iterations_history, gate_results, reaction, completed_at). 47 тестов |
| BL-191 | ✅ News Digest Converter | knowledge-engine | Конвертер daily-news markdown → JSON-дайджест. Парсинг markdown (frontmatter + regex items), CLI convert-news-digest, cron 07:55 Пн-Пт. 13 тестов |
| BL-192 | ✅ Signal Chain Settings — UI настройка LLM-цепочек | shared, pm-bot, web-ui | Дефолт signal_* → ["openrouter", "claude"]. API поддержка signal_triage/analysis/escalation_fallback. 3 группы в Settings FALLBACK CHAINS с drag-and-drop |
| BL-194 | ✅ Research Runner — обработчик research-queue | knowledge-engine, shared | Модуль подхвата заданий из `raw/inbound/research-queue/` (JSON от `dispatch_report`), генерация аналитических отчётов через LLM (Variant B — internal), completeness check, запись в `wiki/reports/`. CLI `research-run`, cron 08:05 Пн-Пт. 48 тестов. Downstream (`check_pending_reports` → `extract_ideas`) уже реализован. Спека: docs/BL-194_research-runner/ |
| BL-198 | ✅ Research Outcome — автоматический вердикт и UI отчётов | knowledge-engine, web-ui | Автоматический outcome LLM после генерации отчёта (idea/insight/not_relevant/error). `extract_ideas_full()` + `_extract_and_classify()` в research_runner. Кликабельный Reports нод в Research Queue UI, outcome-бейджи, drawer для отчётов. API: reports[] + outcome в processed[]. Нейминг отчётов: `{date}-{slug}.md`. 20 новых тестов. Спека: docs/BL-198_research-outcome/ |
| BL-199 | ✅ extract_ideas нод в Research Queue UI | web-ui, knowledge-engine | Активация ghost-нода extract_ideas в пайплайн-графе. Кликабельный нод с бейджем количества идей. API: `extracted_ideas[]` в `/research-queue/status` — сбор idea-файлов по `ideas_refs` из отчётов, парсинг frontmatter + body (problem/solution/rationale). Карточки идей с domain/priority бейджами, drawer с деталями + Obsidian links. 12 новых тестов. Спека: docs/BL-199_extract-ideas-node/ |
| BL-200 | ✅ Багфиксы Signal Chain — outcome, ideas count, logging | knowledge-engine | BUG-030: outcome recovery при повторном запуске research-runner (read_frontmatter → _extract_and_classify если outcome=null). BUG-031: ideas count в RunSummary по reaction вместо подстроки в filename. BUG-032: convert-news-digest обёрнут в LoggedProcess. 12 новых тестов. Спека: docs/BL-200_signal-chain-bugfixes/ |
| BL-201 | ✅ Signal Moderator нод в Research Queue UI | knowledge-engine, pm-bot, web-ui | Активация ghost-нода Signal Moderator в пайплайн-графе research.html. Расширение ItemState (relevance, reason, matched_entities, source_url). Proxy chain: ke_client → vault_api → api.js. Карточки сигналов с reaction-бейджами (SKIP/IDEA/REPORT/ERROR), score/threshold. Drawer с деталями: scoring, reason, entities, gates, iterations. Селектор прогонов. Edge-анимация при reports > 0. Dual-theme (matrix + light). Спека: docs/BL-201_signal-moderator-node/ |
| BL-202 | ✅ Откат BL-202 Signal-Idea endpoints | knowledge-engine, pm-bot, web-ui | Откат архитектурного подхода BL-202 (статус "Сигнал" для идей). Удалены endpoints signalIdeaDetail/Approve/Dismiss из vault_api.py, ke_client.py, api.js. Подготовка к BL-203 (Signal-First Pipeline). Спека: docs/BL-203_signal-first-pipeline/ |
| BL-203 | ✅ Signal-First Pipeline — HITL Triage для News Moderator | knowledge-engine, pm-bot, web-ui, shared | Перестройка pipeline News Moderator: LLM создаёт Signal (не IDEA), PM решает через HITL triage в today.html. Новый артефакт Signal (`raw/inbound/signals/` + `wiki/reports/signals/`). Новые функции: `generate_analysis_report()`, `extract_signals()`, `dispatch_signal()`. 4 API endpoints triage. Settings: relevance_threshold slider. Миграция existing IDEA "Сигнал" → "Отсев". 27 задач, 7 фаз. Спека: docs/BL-203_signal-first-pipeline/ |

### 6.2 Идеи

| # | Название | Компонент | Описание |
|---|:---|:---|:---|
| BL-204 | Связанные сигналы и идеи в report.html | pm-bot, web-ui | На странице report.html при просмотре signal-report показывать блок «Извлечённые сигналы» — кликабельный список сигналов, связанных через `report_ref`. Для каждого сигнала: title, threat_level, status, draft_idea (если есть). Реализация: добавить `related_signals` в API `/reports/{filename}` (сканирование `wiki/reports/signals/` по `report_ref == filename`), frontend-блок под content отчёта |
| BL-70 | Настройка маппинга операция -> провайдер через UI | pm-bot, web-ui | Сейчас захардкожен в коде (упомянуто в Out of Scope ollama-hybrid) |
| BL-71 | A/B-тестирование качества между провайдерами | pm-bot | Сравнение качества Claude vs Ollama (упомянуто в Out of Scope ollama-hybrid) |
| BL-72 | idea-pipeline через Ollama | idea-pipeline | Сейчас всегда Claude API (упомянуто в Out of Scope ollama-hybrid) |
| BL-73 | Multi-Agent Shared Vault | pm-bot | Расширить на команду PM-ов, агент находит пересечения и конфликты идей между участниками |
| BL-154 | Telegram Q&A по базе знаний через Claude CLI | pm-bot, инфраструктура | Новая команда `/ask <вопрос>` в Telegram-боте. pm-bot запускает `claude --print` как subprocess с `cwd=VAULT_PATH`, CLI подхватывает CLAUDE.md + читает wiki/, возвращает ответ в stdout. Авторизация через подписку (claude login). Каждый вопрос = отдельная сессия CLI, память между запросами не нужна. **Требования к реализации (по итогам архитектурного ревью):** (1) Dockerfile: добавить установку Claude CLI при сборке образа. (2) docker-compose.yml: добавить named volume для `~/.claude/` — иначе авторизация теряется при перезапуске контейнера. (3) Безопасность: `shell=False`, аргументы списком `["claude", "--print", "-p", prompt]` — исключает shell injection. Системный промпт явно запрещает запись: "Ты ассистент по базе знаний в режиме read-only. Никакие операции записи недопустимы. Отвечай только на основе файлов в wiki/. Вопрос: {question}". (4) Async: `asyncio.get_running_loop().run_in_executor()` (не deprecated get_event_loop). При таймауте (120с) — явный `proc.kill()`. (5) UX: немедленно отправлять "Думаю... (до 2 минут)" и блокировать повторный `/ask` пока выполняется текущий (флаг `_ask_in_progress`). (6) Логирование: оборачивать subprocess-вызов в `system_log` с теми же полями что и SDK-вызовы. **Открытый вопрос при реализации:** `context_assembler.py` (существует) собирает контекст детерминированно — рассмотреть как альтернативу надежде на то, что CLI сам найдёт нужные файлы в wiki/. |
| BL-139 | Перенос идеи при смене домена | web-ui, knowledge-engine | При смене домена идеи через Web UI (editable-field domain) — физически перемещать файл из wiki/domains/старый/ideas/ в wiki/domains/новый/ideas/. Обновлять log.md и index.md обоих доменов. Сейчас меняется только frontmatter, файл остаётся в старой папке |

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
| BL-143 | ✅ Trace Log — централизованный журнал операций | pm-bot, knowledge-engine, shared | shared/system_log.py (SQLite модуль), 11 процессов обёрнуты в LoggedProcess, API /system-log + /system-log/stats, Web UI system-log.html, LLM trace (provider chain, fallback, ошибки), per-unit details meeting queue, overview badge, cron cleanup 90д, 12 unit-тестов. Спека: docs/system-activity-log/ |
| BL-166 | ✅ Langfuse LLM Observability | shared, pm-bot, knowledge-engine, idea-pipeline, инфраструктура | Self-hosted Langfuse v2 (Docker: langfuse + langfuse-db, порт 3100). Инструментация shared/llm_client.py:call_detailed() — автоматические трассировки. Token usage проброс из Anthropic SDK и OpenRouter. shared/langfuse_client.py — singleton с graceful degradation. Sidebar ссылка LLM TRACES. Langfuse SDK v2.x. idea-pipeline инструментация частичная (AC-03 blocked — требует BL-167). Спека: docs/BL-166_langfuse-observability/ |
| BL-167 | ✅ Pipeline fallback chains | idea-pipeline, shared, web-ui | Перевод idea-pipeline на shared/llm_client fallback chains. Pipeline = 4-я группа операций. PipelineClaudeClient удалён. Settings UI: PIPELINE карточка. Спека: docs/BL-167_pipeline-fallback-chains/ |
| BL-232 | ✅ Вынос служебных файлов из vault в Docker volumes | shared, pm-bot, knowledge-engine, инфраструктура | Перенос 4 platform state файлов из VAULT_PATH в Docker volumes: .system-log.db → platform-data (новый shared volume), .pm-user-prefs.json → pm-bot-data, .jira-sync-state.json → platform-data, .health-history.json → ke-data. Env vars: PLATFORM_DATA_PATH, PM_BOT_DATA_PATH, KE_DATA_PATH. Миграция при старте (shared/platform_migrate.py). Оригиналы в vault не удаляются. Частично закрывает BL-157 |

### 7.2 Идеи

| # | Название | Компонент | Описание |
|---|:---|:---|:---|
| BL-81 | Мониторинг и алерты по доступности Ollama | pm-bot | Health check, uptime tracking (упомянуто в Out of Scope ollama-hybrid) |
| BL-152 | Рефакторинг vault_api.py — разбивка на роутеры | pm-bot | 4682-строчный God File (59 эндпоинтов, 120+ except-блоков) разбить на 9 FastAPI APIRouter-модулей: `routers/{jira,config,system,meetings,tasks,epics,reports,ideas,vault,playground}.py`. Параллельно вынести вспомогательные слои: `cache.py` (_VaultCache), `parsers.py` (parse_note, _calculate_readiness и др.), `scanner.py` (_scan_domain_folders), `search_index.py` (_SearchIndex). Порядок: сначала cache/parsers/scanner (чистый перенос без изменения логики), затем роутеры от простых к сложным (jira → config → system → meetings → tasks → epics → reports → ideas → vault). Каждый шаг атомарен и не ломает API. Репозиторный слой и сервисные абстракции не вводить — избыточны для однопользовательской системы. Обновлено 24.07.2026: рост с 3883 до 4682 строк, с 51 до 59 endpoints. |
| BL-144 | Pipeline Monitor — интерактивная визуализация обработки | web-ui, pm-bot, knowledge-engine | Расширение system-log (BL-143) до realtime pipeline view: текущий этап обработки для каждого элемента (fetch → parse → LLM call → write), elapsed time, provider chain, retry counts. Мотивация: BL-143 покрывает журнал завершённых операций, BL-144 — визуализацию процесса в реальном времени |
| BL-163 | Jira sync: partial update вместо full rewrite | knowledge-engine | `update_frontmatter()` в mapper.py делает полный rewrite через `to_markdown()`, затирая vault-only поля (access_count, tier, relevance, digest, last_accessed, epic_key если Jira вернула null). Заменить на partial update: обновлять только поля, которые Jira реально возвращает (status, assignee, priority, labels, updated_at, synced_at), сохраняя остальные. Обнаружено на GO-181: raw имел `epic_key: TMPL-15408`, wiki — `epic_key: null` после re-sync. Связано с BL-160 (partial update для custom-named files уже реализован через frontmatter_utils) |
| BL-157 | Пересмотреть место хранения пользовательских настроек | pm-bot, shared, инфраструктура | Открытый вопрос для повторного анализа: сейчас ВСЕ пользовательские настройки (fallback-цепочки провайдеров, тема, refresh-mode, openrouter_model и т.д., см. BL-76) хранятся в `VAULT_PATH/.pm-user-prefs.json` — том же смонтированном томе, что и контент vault (идеи, встречи, decision journal). Обоснование текущего выбора: vault — единственный durable-том проекта, персистентный между пересборками контейнеров (`docker-compose.yml`: `${VAULT_PATH}:/vault` монтируется во все сервисы), в отличие от файловой системы самого контейнера. Вопрос к пересмотру: стоит ли отделить app-конфигурацию от пользовательского контента — в проекте уже существует отдельный персистентный Docker-том `pm-bot-data:/data` (используется для SQLite: enrichment_db, system_log), который мог бы быть более подходящим местом для настроек приложения, не смешивая служебный JSON-файл с личным Obsidian-vault пользователя. Требует явного архитектурного решения (миграция формата хранения, обратная совместимость с уже существующим `.pm-user-prefs.json`) — не реализовывать без отдельного анализа. |

---

## 8. Управление знаниями (Decay & Health)

> Источник: SWOT-анализ [smixs/autograph](https://github.com/smixs/autograph). Спека: `docs/context_compaction/swot_autograph.md`

### 8.1 Decay engine — Реализовано

| # | Название | Компонент | Описание |
|---|:---|:---|:---|
| BL-110 | Decay engine (Эббингауз) | knowledge-engine | Непрерывная шкала актуальности `relevance: 0.0-1.0` вместо грубого TTL. Формула: `strength = 1 + ln(access_count)`, `effective_rate = rate / strength`, `relevance = max(floor, 1.0 - effective_rate × days)`. Domain-specific rates из domain-config.yaml (идеи ~50д, PRD ~42д, daily ~25д). Ref: autograph `common.py: calc_relevance()` |
| BL-111 | Tier system (graduated recall) | knowledge-engine | 5 tier'ов: archive → cold → warm → active → core. Пороги: active ≤7д, warm ≤21д, cold ≤60д, archive >60д. `core` — ручная метка, исключение из decay. context_assembler фильтрует только active+warm для core-digest. Ref: autograph `common.py: calc_tier()` |
| BL-112 | Touch при обращении | pm-bot, knowledge-engine | При использовании digest'а в контексте pm-bot → increment `access_count`, refresh `last_accessed`, promote tier на 1 ступень. Spacing effect: чем чаще обращение, тем медленнее забывание. Ref: autograph `engine.py: cmd_touch()` |
| BL-113 | Creative recall | pm-bot, web-ui | Случайная выборка 3-5 карточек из cold/archive tier для переоткрытия забытых идей. Telegram: `/creative`. Web UI: блок "Забытые идеи" на overview.html. Ref: autograph `engine.py: cmd_creative()` |

### 8.2 Decay dashboard — Реализовано

| # | Название | Компонент | Описание |
|---|:---|:---|:---|
| BL-132 | ✅ Decay state dashboard | web-ui, knowledge-engine, pm-bot | Интерактивный дашборд состояния базы знаний на основе decay-модели. 6 блоков: (1) Metrics strip (4 KPI), (2) Decay landscape — bubble scatter (Chart.js), (3) Tier distribution donut с центральным счётчиком, (4) Проекция без активности — слайдер +30 дней с дельтами, (5) Здоровье по доменам — stacked horizontal bars, (6) Forgotten gems — top-5 cold/archive. API: GET /api/v1/decay/snapshot (922 артефакта, <3с). Спека: docs/decay-engine-dashboard/ (13 задач, все done). |

### 8.3 Health scoring — Реализовано

| # | Название | Компонент | Описание |
|---|:---|:---|:---|
| BL-114 | ✅ Vault health score | knowledge-engine, pm-bot, web-ui | Количественная метрика здоровья vault (0-100): 7 категорий штрафов (broken links ×3, orphans ×5, dead-ends ×1, stale drafts ×1, unsorted misc ×0.5, ingest backlog ×0.2, description coverage). Грейды: healthy ≥80 / warning ≥50 / critical <50. `health_scorer.py` + CLI `health --save --json` + endpoint `GET /api/v1/vault/health` с trend 7d/30d. Overview виджет (Zone A): score + dot + sparkline + раскрывающаяся breakdown-панель по категориям. ke-cron job 04:00 ежедневно. История `.health-history.json` (TTL 90д). Спека: `docs/health-scoring/` (14 задач, все done) |
| BL-115 | ✅ Wikilink resolver | knowledge-engine | 3-уровневый детерминированный резолвер ссылок в linter.py: exact name → unique suffix → unique stem. `_build_file_index()` + `_resolve_wikilink()`. Заменил примитивный exact-match в `check_broken_links()`. Сокращает ложные broken links. Спека: `docs/health-scoring/tasks.md` (T-05, T-06) |

### 8.4 Идеи

| # | Название | Компонент | Описание |
|---|:---|:---|:---|
| BL-149 | Dead ends: исключить IDEA и учитывать index/log | knowledge-engine | Текущая проверка dead_ends ложно срабатывает на IDEA-файлах (новая идея без входящих ссылок — нормальное состояние). Исправления: (1) исключить `wiki/domains/*/ideas/` из проверки dead_ends, (2) учитывать входящие ссылки из служебных файлов домена (`index.md`, `log.md`) при подсчёте |

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
| BL-160 | ✅ BUG-023 (jira-sync custom-named files) | knowledge-engine | Jira sync не обновлял статус vault-файлов с кастомными именами (E-*.md). Fix: fallback-поиск по jira_key в frontmatter в секциях UPDATED, CLOSED и import_single_issue. Partial update через frontmatter_utils вместо полного rewrite |
| BL-165 | ✅ BUG-025 (_CLOSED_STATUSES raw values) | knowledge-engine | _CLOSED_STATUSES содержал сырые Jira-статусы вместо нормализованных — задачи со статусом "Отменена" не распознавались как закрытые. Fix: замена на нормализованные значения (done, deploy, staging, cancelled) |
| BL-193 | ✅ BUG-026 (quality_gate report_brief crash) | knowledge-engine | `_extract_fields` падал на `reaction=report`: проверка `"idea_draft" in analysis` всегда True (dataclass key). Fix: truthiness check `analysis.get("idea_draft")` |
| — | ✅ BUG-027 (signal_moderator competitor misclassification) | knowledge-engine | `dispatch_report` записывал домен источника новости (skift.com, TechCrunch) в поле `competitor` research-queue JSON вместо реального конкурента. Fix: LLM извлекает `competitor` в `report_brief` (промпт `signal_analyze.txt`), `_process_item` в `signal_orchestrator.py` передаёт entity из `scoring.matched_entities` как fallback через `_handle_report(..., competitor=...)` → `dispatch_report(..., competitor=...)` |
| — | ✅ BUG-028 (research_runner no quality gate) | knowledge-engine | `process_task` сохранял мусорные отчёты (completeness=0, quality_warning=True) вместо отклонения. Fix: reject gate при score < threshold → failed/, полная перегенерация при score < 2 (catastrophic), порог из `config.completeness_threshold` |
| BL-205 | ✅ BUG-029 (today-focus-emoji) | pm-bot | Фокус дня не отображался на today.html: парсер делал exact match `== "фокус дня"`, но заголовок в дайджесте содержит emoji-префикс `📌`. Fix: contains-проверка `in label.lower()` |
| BL-206 | ✅ BUG-030 (signal-score-think-blocks) | knowledge-engine | 75% новостей получали relevance=0 из-за `<think>...</think>` блоков в ответах LLM (Nemotron, Qwen). `_parse_json_response` не умел чистить thinking-блоки. Fix: `re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)` перед парсингом |
| BL-207 | ✅ BUG-031 (langfuse-null-traces) | shared, knowledge-engine | Langfuse трейсы показывали NULL: (1) `atexit.register(shutdown)` в langfuse_client.py, (2) `try/finally` обёртка dispatch в cli.py, (3) `input=` в lf.trace() в llm_client.py, (4) `_safe_span()` принимает input/output |
| BL-208 | ✅ BUG-032 (openrouter-null-content) | shared | OpenRouter `content: null` от reasoning-моделей вызывал crash вместо fallback. Fix: null → пустая строка + RuntimeError для корректного перехода к следующей модели в цепочке |
| BL-209 | ✅ BUG-033 (signal-approve-no-module) | pm-bot, knowledge-engine | Signal approve endpoint делал прямой import `knowledge_engine` → crash 500 в Docker. Fix: бизнес-логика в KE API, pm-bot проксирует через ke_client |
| BL-210 | ✅ BUG-034 (digest-section-count-zero) | pm-bot | `_parse_section()` в today_parsers.py не поддерживал plain-line формат дайджеста → count=0 для всех секций. Fix: attempt 3 — парсинг plain lines (skip bold subheaders и group headers) |
| BL-211 | ✅ BUG-035 (dispatch-idea-no-wiki-copy) | knowledge-engine | `dispatch_idea()` записывал IDEA только в `raw/inbound/ideas/`, без wiki-копии → идея не попадала в enrichment/synthesis/UI. Fix: добавлена запись в `wiki/domains/<domain>/ideas/` через `wiki_domain_dir()` |
| BL-213 | ✅ BUG-036 (KE не видит user-prefs после BL-232 → API fallback) | shared, knowledge-engine, инфраструктура | KE и ke-cron контейнеры не имели доступа к `.pm-user-prefs.json` после BL-232 (volume только в pm-bot) → fallback chain всегда `["claude"]` (без OpenRouter) → 290 протоколов в failed/ за недостатком кредитов. Fix: HTTP fallback в `_load_llm_prefs()` к pm-bot REST API + PM_BOT_API_URL env var. Очистка: 179 дублей из failed/ удалены, 5 августовских протоколов в pending/ (25.08.2026) |
| BL-212 | ✅ Playground: think-blocks + Langfuse + max_tokens | pm-bot | `playground_chat()`: (1) `<think>` блоки reasoning-моделей (Nemotron, Qwen) убираются из ответа regex. (2) Langfuse трейсинг: trace + generation для каждого запроса. (3) max_tokens 4096→8192 (дефолт) с UI-селектором (4096/8192/16384) |

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
| ~~BL-127~~ | ~~Onboarding-док и бэкап-стратегия~~ | ~~инфраструктура~~ | ✅ **Реализовано 14.06.2026.** ONBOARDING.md в корне проекта: архитектура (4 контейнера, 9 потоков, LLM-слой, Web UI, домены), развёртывание с нуля (6 шагов), 23 переменные окружения, settings.yaml, 11 cron-задач (ke-cron + Cowork + headless), бэкап/восстановление (vault + SQLite + .env), troubleshooting (13 проблем), команды (Docker + CLI + Telegram). Аудит: Б-6. |
| ~~BL-130~~ | ~~Декаплинг pm-bot и knowledge-engine~~ | ~~инфраструктура~~ | ✅ **Закрыто 14.06.2026.** pm-bot больше не копирует код KE. COPY knowledge-engine удалён из Dockerfile. 21 subprocess.run → ke_client HTTP-вызовы. KE API на порту 8001 (serve + watch). Объединено с BL-126. |
| ~~BL-131~~ | ~~CI green: mypy + ruff~~ | ~~инфраструктура~~ | ✅ **Реализовано 14.06.2026.** Устранены все ошибки mypy (253 ошибки в 16 файлах) и ruff lint (26 ошибок) по всем компонентам. KE: type narrowing для YAML/JSON данных, Optional params, fcntl type:ignore. pm-bot: assert-narrowing для nullable Update properties (182 ошибки в handlers.py), Any type fix, variable scope fix. idea-pipeline: orchestrator null guards, TextBlock isinstance, frontmatter.Post handler arg. Тесты check_unsorted_misc обновлены под wikilink-логику. |

---

## 11. Задачи из аудита (24.07.2026)

> Источник: `docs/audit/executive-summary-2026-07-24.md`, `docs/audit/technical-audit-2026-07-24.md`, `docs/audit/architectural-audit-2026-07-24.md`.
> Порядок — по убыванию приоритета. Связи с существующими задачами указаны.

### 11.1 P0 — быстрые победы (1-2 дня каждая)

| # | Название | Компонент | Описание |
|---|:---|:---|:---|
| BL-174 | .dockerignore для всех сервисов | инфраструктура | Build context 468 MB вместо ~20-30 MB. Каждый `docker build` копирует .git/, docs/, тесты, web assets, CLAUDE.md. Создать `.dockerignore` в корне: `.git`, `docs/`, `*.md` (кроме requirements), `__pycache__`, `.pytest_cache`, `.claude/`, `.idea/`, `test-results/`, `*.pyc`. Ускорение сборки в 10-20x |
| BL-175 | Docker HEALTHCHECK для кастомных сервисов | инфраструктура | pm-bot, knowledge-engine, idea-pipeline имеют HTTP health endpoints, но не подключены к Docker HEALTHCHECK. Docker/orchestrator не может автоматически перезапустить зависший сервис. Добавить `HEALTHCHECK CMD curl -f http://localhost:<port>/health \|\| exit 1` в каждый Dockerfile. Обновить `depends_on` на `condition: service_healthy` |
| BL-176 | Исправить молчаливое проглатывание ошибок | pm-bot, knowledge-engine, shared | 28 блоков `except Exception:` без алиаса (ошибка теряется) + 17 блоков `except: pass` (полное подавление). Потенциально скрывают production-баги. Очаги: vault_api.py (5), handlers.py (3), health_scorer.py (4), digest/generator.py (4), ingest.py (4), llm_client.py (3). Заменить на `except Exception as e: logger.warning(...)` или `logger.debug(...)` где подавление осознанное |
| BL-177 | Ужесточить mypy до реальной проверки | инфраструктура | Текущая конфигурация: `check_untyped_defs=false`, `ignore_missing_imports=true`, `warn_return_any=false`, CI `continue-on-error: true`. Mypy фактически ничего не ловит. Шаги: (1) `check_untyped_defs = true`, (2) убрать `continue-on-error` из CI, (3) пометить `# type: ignore` только осознанные места. Ожидаются ошибки — фиксировать итеративно |

### 11.2 P1 — среднесрочные (1-2 недели)

| # | Название | Компонент | Описание |
|---|:---|:---|:---|
| BL-178 | Тестовое покрытие idea-pipeline | idea-pipeline | Покрытие 17% (2 тестовых файла на 12 source). Нет тестов для: api.py (5 endpoints), orchestrator.py (pipeline flow), state.py (PipelineStore), auth.py (ApiKeyMiddleware), config.py, models.py, agents/* (3 агента). Минимум: api + orchestrator + state + auth. Довести до 60%+ |
| BL-179 | Устранить прямой импорт idea-pipeline → knowledge-engine | idea-pipeline, shared | `orchestrator.py` содержит lazy-импорты `from knowledge_engine.matcher import find_links`, `from knowledge_engine.vault_index import build_index`, `from knowledge_engine.notifier import send_telegram`. Нарушает изоляцию сервисов. Варианты: (1) вынести `matcher`, `vault_index` в shared/, (2) вызывать через HTTP API knowledge-engine. Предпочтительно вариант 2 — matcher и vault_index специфичны для KE |
| BL-180 | Глобальный exception handler для FastAPI | pm-bot, knowledge-engine, idea-pipeline | Каждый endpoint — индивидуальный try/except. KE отдаёт `str(exc)` в 500 ответах — утечка внутренних деталей (stack traces, пути файлов). Добавить `@app.exception_handler(Exception)` во все 3 сервиса: логировать exc, возвращать sanitized `{"error": "Internal server error", "request_id": ...}`. Связано с BL-176 (обработка ошибок) |
| BL-181 | Версионирование API в idea-pipeline | idea-pipeline | Endpoints используют `/pipeline/...` и `/health` без версии, тогда как pm-bot и KE — `/api/v1/`. Привести к единому стандарту `/api/v1/pipeline/...`. Обновить pipeline_client.py в pm-bot |

### 11.3 P2 — стратегические (при расширении)

| # | Название | Компонент | Описание |
|---|:---|:---|:---|
| BL-182 | Централизация env через Pydantic BaseSettings | shared, pm-bot, knowledge-engine, idea-pipeline | `os.getenv()` вызывается напрямую в 15+ файлах без централизованной валидации. Сервис узнает об отсутствующем ключе только при первом обращении к функции. Создать `shared/config.py` на базе Pydantic BaseSettings: fail-fast валидация при старте, типизация, .env поддержка, defaults. Дублирование `.env` (корень + pm-bot/) — консолидировать |
| BL-183 | API аутентификация (при выходе за локальную сеть) | pm-bot, knowledge-engine | Vault API (59 endpoints) и KE API (29 endpoints) без аутентификации. CORS `allow_origins=["*"]`. Текущая митигация — сетевая (Docker + 192.168.0.6). При расширении доступа (VPN, cloud, multi-user) необходимо: API key middleware или JWT, ограничение CORS до конкретных origins. **Не реализовывать до изменения scope доступа** — для однопользовательской локальной системы текущий trade-off осознанный |
| BL-184 | async HTTP-клиент для межсервисного взаимодействия | pm-bot | ke_client.py и pipeline_client.py используют sync `requests` — блокируют event loop FastAPI при каждом проксированном запросе. Перейти на `httpx.AsyncClient` с connection pooling. Триггер: заметные задержки API при параллельных запросах к KE |
| BL-185 | Rate limiting на HTTP endpoints | pm-bot, knowledge-engine | Только Telegram имеет rate limiter (token bucket). HTTP endpoints без ограничений — один клиент может перегрузить API. Добавить `slowapi` или custom middleware с лимитами per-IP/per-endpoint. Триггер: при расширении доступа за пределы localhost |
| BL-186 | Pre-commit расширение | инфраструктура | Текущий pre-commit: только `ruff --fix`. Добавить: `ruff format` (форматирование), `check-yaml`, `check-json`, `trailing-whitespace`, `end-of-file-fixer`. Опционально: `detect-secrets`, `no-commit-to-branch` (main). Не добавлять mypy в pre-commit — слишком медленный для hook, оставить в CI |
| BL-187 | CD pipeline (автоматический деплой) | инфраструктура | CI есть (lint + typecheck + test), CD отсутствует. Деплой ручной. При увеличении частоты деплоев: добавить workflow для Docker build/push + deploy на целевой сервер (SSH или Docker registry). Триггер: регулярные деплои чаще 1 раза в неделю |

---

## 12. Задачи из аудита (12.08.2026)

> Источник: `docs/TECH-AUDIT-2026-08-12.md` (6 параллельных направлений: архитектура, безопасность, тесты, техдолг, API/инфраструктура, ошибки/логирование).
> Повторно подтверждены из предыдущих аудитов: BL-152, BL-174..BL-185 (14 задач).

### 12.1 P0 — безопасность (немедленно)

| # | Название | Компонент | Описание |
|---|:---|:---|:---|
| BL-213 | Path traversal protection | pm-bot, knowledge-engine, shared | 5 critical точек: (1) `vault_api.py:229` domain param → `wiki_domain_dir()` → `mkdir(parents=True)` вне vault; (2) `vault_api.py:2469` PUT domain-config/{slug} без проверки `..`; (3) `enricher.py:16` filepath без join с vault_path; (4) `decay_engine.py:342,394` абсолютный path обходит vault_root; (5) `digest/generator.py:113` source_path без проверки принадлежности. Fix: валидация domain по regex `^[a-z0-9_-]+$`, filepath через `.resolve()` + `is_relative_to(vault_root)` |
| BL-214 | Input validation + sensitive data в логах | pm-bot, knowledge-engine | (1) `vault_api.py:128` CaptureRequest.text без max_length → бюджетный DoS через LLM. (2) `notifier.py:32` bot_token может утечь в exception message. (3) `calendar_client.py:53` CalDAV-пароль в стектрейсе. Fix: max_length на LLM-bound поля, маскировка URL в exception handlers |
| BL-215 | Docker security hardening | инфраструктура | (1) `docker-compose.yml:13` `ipc: host` — убрать. (2) 3 Dockerfile без `USER` — процессы от root, добавить non-root. (3) Vault mount RW во всех 4 сервисах → `:ro` где запись не нужна. (4) `$JIRA_SYNC_CRON` в cron без валидации → command injection. (5) Дефолтные пароли Langfuse в закоммиченном файле → убрать fallback, требовать .env |

### 12.2 P1 — техдолг (следующий спринт)

| # | Название | Компонент | Описание |
|---|:---|:---|:---|
| BL-216 | Extract shared LLM helpers | shared, pm-bot, knowledge-engine | `_parse_json_response()` дублируется в 12+ местах (claude_client.py обоих компонентов, signal_moderator, idea_extractor, research_runner). `_load_prompt()` дублируется в pm-bot и KE. Вынести в `shared/llm_utils.py` |
| BL-217 | Remove dead code | pm-bot, knowledge-engine, idea-pipeline, shared | (1) `artifact_extractor.py` — orphaned ~400 строк, не подключён к CLI/API. (2) `process_one.py:5` — импорт несуществующей функции. (3) `handlers.py:143` `_split_message()` не вызывается. (4) `vault_paths.py:115-173` — 7 неиспользуемых функций. (5) `models.py:76` ErrorResponse не используется. (6) `llm_client.py:768` deprecated `call_with_fallback()` используется в `reporter.py:346`. (7) `fix_broken_links.py:20` — хардкод абсолютного пути |
| BL-218 | Standardize datetime to UTC-aware | shared, pm-bot, knowledge-engine, idea-pipeline | `datetime.now()` (naive) в 10+ файлах vs `datetime.now(timezone.utc)` в 3. В vault_api.py — оба варианта одновременно. Создать `shared/time_utils.py` с `utc_now()`, заменить все вызовы |
| BL-219 | Extract hardcoded constants | shared, pm-bot, knowledge-engine | (1) `"claude-sonnet-4-6"` в 5+ файлах → `shared/constants.py`. (2) Дефолтная OpenRouter model рассогласована: `"qwen/qwen3-32b"` vs `"qwen/qwen3-next-80b-a3b-instruct:free"`. (3) Decay tier границы (7/21/60 дней) хардкожены → settings.yaml. (4) Token budgets (3000/10000/6000) в context_assembler → settings.yaml. (5) Таймауты 30/60с в KE claude_client.py |
| BL-220 | Fix __import__() + print→logger + logging config | knowledge-engine, shared | (1) 20+ `__import__()` в cli.py — антипаттерн → обычные imports. (2) `print()` вместо logger в 6 файлах. (3) 4 независимых `basicConfig()` с разными форматами → `shared/logging_config.py` |
| BL-221 | Fix HTTP 200 error responses | pm-bot, knowledge-engine | 5 endpoints возвращают ошибки с HTTP 200: test_ollama, test_openrouter, test_caldav, get_today_meetings (vault_api.py), domains_create (api.py). Ключ ошибки непоследователен: `"detail"` vs `"message"`. Fix: корректные HTTP-коды + унифицированный формат |
| BL-222 | Add try/except to _call_claude/_call_ollama | shared | `llm_client.py:353-377` и `:380-423` без try/except. Исключения Anthropic SDK пролетают вверх без логирования на уровне функции |
| BL-223 | Replace deprecated asyncio.get_event_loop() | pm-bot | `daily_alert.py:52` и `enrichment_reminder.py:296` — deprecated Python 3.12. При concurrent-вызовах → RuntimeError. Fix: `asyncio.run()` |
| BL-224 | Add retry + timeout to inter-service HTTP clients | pm-bot | `ke_client.py` (25 функций) и `pipeline_client.py` без retry — перезагрузка KE роняет все запросы. `calendar_client.py` — CalDAV без timeout, зависнет при недоступности |

### 12.3 P2 — качество (плановый рефакторинг)

| # | Название | Компонент | Описание |
|---|:---|:---|:---|
| BL-225 | REST API naming consistency | pm-bot, knowledge-engine | Singular vs plural (`/artifact/` vs `/ideas/`), query vs path param для одного ресурса (project), `/signals/list` — verb suffix. Стандартизировать REST naming |
| BL-226 | API pagination for list endpoints | pm-bot, knowledge-engine | GET /ideas, /tasks, /epics возвращают ВСЕ записи. При росте vault → slow responses / OOM. Добавить `?limit=&offset=` |
| BL-227 | Fix dependency manifests | idea-pipeline, shared, pm-bot | (1) idea-pipeline/requirements.txt — нет `requests`. (2) Нет shared/requirements.txt — зависимости дублируются в 3 файлах. (3) `apscheduler>=3.10.4` без `<4.0.0`. (4) Неиспользуемые: recurring-ical-events, mdit-py-plugins |
| BL-228 | CI: add testpaths + pytest-cov | инфраструктура | idea-pipeline/tests не в testpaths pyproject.toml. shared/tests не запускается в CI. Нет pytest-cov для измерения покрытия. Fix: testpaths, pytest-cov, coverage baseline |
| BL-229 | Tests for untested core modules | shared, pm-bot | frontmatter_utils.py (все компоненты) — 0 тестов. ke_client.py (25 функций) — 0 тестов. vault_api.py (68 endpoints) — 0 integration-тестов. auth.py (idea-pipeline) — security boundary без тестов. Нет @pytest.mark.parametrize во всём проекте |

---

## 13. Сводка

| Статус | Кол-во | Пункты |
|:---|:---|:---|
| ✅ Реализовано | 116 | BL-01..BL-08, BL-11..BL-18, BL-24..BL-29, BL-31..BL-34, BL-40..BL-57, BL-60..BL-61, BL-64, BL-66..BL-69, BL-74..BL-80, BL-101..BL-102, BL-107..BL-113, BL-114..BL-120, BL-122..BL-127, BL-130..BL-135, BL-138, BL-140..BL-141, BL-143, BL-155..BL-156, BL-158..BL-159, BL-166..BL-168, BL-172..BL-173, BL-188..BL-192, BL-194..BL-195, BL-197..BL-203, BL-212, BL-230..BL-232, BL-235 |
| ✅ Баги исправлены | 36 | BL-82..BL-99, BL-103..BL-106, BL-128..BL-129, BL-160, BL-165, BL-193, BUG-027, BUG-028, BL-205, BL-206, BL-207, BL-208, BL-209, BL-210, BL-211 |
| Идея | 69 | BL-09, BL-10 (поглощены BL-118), BL-19..BL-23, BL-30, BL-35..BL-39, BL-58..BL-59, BL-62..BL-63, BL-65, BL-70..BL-73, BL-81, BL-100, BL-136..BL-137, BL-139, BL-148..BL-154, BL-157, BL-163, BL-169..BL-171, BL-174..BL-188, BL-196, BL-204, BL-213..BL-229, BL-233..BL-234 |
| ❌ Удалено | 1 | BL-121 |
| **Итого** | **221** | |
