# PM Assistant — Changelog

Журнал изменений по всем компонентам монорепо.
Компоненты: **pm-bot**, **knowledge-engine**, **idea-pipeline**, **web-ui**.

---

## 03.10.2026

### BL-237 — LanceDB → ChromaDB, фиксы деплоя (03.10.2026)
- **shared**: `vector_store.py` — замена LanceDB на ChromaDB (PersistentClient, cosine similarity). Причина: LanceDB требует AVX2, CPU i5-2500 (Sandy Bridge) не поддерживает
- **shared**: `embedding_client.py` — дефолт embedding_dim 768 → 1024, fallback OpenAI → OpenRouter
- **shared**: `vector_store.py` — динамический EMBEDDING_DIM из prefs (было захардкожено 768)
- **knowledge-engine**: `cli.py` — флаги `--limit N` и `--fail-fast` для migrate-to-lancedb
- **knowledge-engine**: `migrator.py` — поддержка limit/fail-fast
- **docker**: порт mcp-server 8200 → 8201 (конфликт с family_quest-backend)
- **docker**: pm-bot-data volume примонтирован к KE и ke-cron (ro) для доступа к user-prefs.json
- **деплой**: миграция 1584 файлов в ChromaDB завершена (0 ошибок, 1481 уникальных записей, bge-m3 1024-dim)

---

## 02.10.2026

### BL-237 — LanceDB vector store + MCP server (02.10.2026)
- **shared**: новый модуль `vector_store.py` — обёртка LanceDB embedded (CRUD, hybrid search RRF, FTS index, 23-field PyArrow schema)
- **shared**: новый модуль `embedding_client.py` — embedding fallback chain (Ollama → OpenRouter), batch embed, graceful degradation
- **shared**: `vault_paths.py` — добавлен `vector_store_dir()`, 6 функций llm_wiki_* помечены deprecated
- **knowledge-engine**: `generator.py` — dual-write: VECTOR_STORE_ENABLED=1 пишет дайджесты в LanceDB вместо .md файлов
- **knowledge-engine**: `watcher.py` — DigestHandler регистрируется при VECTOR_STORE_ENABLED=1
- **knowledge-engine**: новый модуль `reindexer.py` — полная переиндексация wiki/ с прогрессом и Telegram-нотификацией
- **knowledge-engine**: новый модуль `migrator.py` — bulk import существующих llm_wiki/ .md файлов в LanceDB (без LLM)
- **knowledge-engine**: `api.py` — POST /reindex, GET /reindex/status, GET /vector/stats, POST /test-embedding
- **knowledge-engine**: `cli.py` — команды `reindex` и `migrate-to-lancedb`
- **pm-bot**: `context_assembler.py` — новый режим lancedb: 3-tier waterfall (ONE-LINERS 3K → CORE 10K → EXTENDED 6K = 19K budget)
- **pm-bot**: `vault_search.py` — hybrid search через LanceDB, fallback на legacy _SearchIndex
- **pm-bot**: `vault_ops.py` — /search endpoint с domain/type фильтрами, backward-compatible + new fields
- **pm-bot**: `user_prefs.py` — 4 новых поля: embedding_fallback, embedding_model_ollama, embedding_model_openai, embedding_dim
- **pm-bot**: `ke_client.py` — proxy методы reindex_start/status, test_embedding, vector_stats
- **pm-bot**: `providers.py` — POST /reindex, GET /reindex/status, POST /test-ollama-embedding, GET /vector/stats
- **web-ui**: `settings.html` — секция VECTOR STORE / EMBEDDINGS (embedding fallback chain, model settings, Test Embedding, Reindex, Index Stats)
- **mcp-server**: новый компонент — FastMCP сервер (SSE + stdio) с 4 tools: search, get_context, list_artifacts, get_artifact
- **docker**: vector-store volume, mcp-server сервис (порт 8201, ro mount), KE/ke-cron rw mount, pm-bot ro mount
- **тесты**: 22 unit (vector_store) + 17 unit (embedding_client) + 8 (reindexer) + 7 (migrator) + 7 (mcp tools) + 8 (providers) + 13 integration = 82 новых теста

---

## 01.10.2026

### BL-236 — Убрать захардкоженные домены из кода (01.10.2026)
- **shared**: удалён `_SEED_DOMAIN_DATA` из `domain_config.py` — OTA-специфичные домены убраны из публичного кода
- **shared**: `seed_from_defaults()` упрощён — при первом запуске создаётся один домен `general` (display_name: "General", color: "#607D8B")
- **shared**: домены из `hardcoded_map` и `existing_domains` создаются с bare slugs (без захардкоженных полей)
- **корень**: добавлен `domain-seed.example.yaml` — пример формата конфигурации доменов
- **тесты**: удалён `TestSeedWithFullData`, добавлены 3 новых теста, всего 83 passed

### Прочее (01.10.2026)
- **README.md**: полная англоязычная версия (primary), русская версия в readme_ru.md
- **assets/**: hero image добавлен в репо
- **.gitignore**: добавлены `BACKLOG.md`, `claude.md`, `context.md`, `claude-opus36.bat`, `docs_private/`
- **.env.example**: нейтрализованы пути (`/path/to/your/...` вместо `C:/Users/...`)
- **GitHub**: создан релиз v1.30.0, CI badge зелёный

---

## 21.09.2026

### BL-152 — Рефакторинг vault_api.py — разбивка на роутеры (21.09.2026)
- **pm-bot**: vault_api.py (5672 строк, 72 эндпоинта) → thin orchestrator (105 строк, 0 эндпоинтов)
- **pm-bot**: 4 хелпер-модуля: vault_cache.py (_VaultCache, _cache, _jira_sync_lock), vault_parsers.py (parse_note, parse_epic_note, _calculate_readiness и др.), vault_scanner.py (_scan_domain_folders, _domain_from_path), vault_search.py (_get_search_index)
- **pm-bot**: 23 APIRouter-модуля в app/routers/ (ai_agent, artifacts, config, decay, decisions, domains, epics, ideas, jira, meetings, playground, prompts, providers, reports, research, settings, signals, system, tasks, today, todos, user_prefs, vault_ops)
- **API-контракт**: все 72 URL, форматы ответов, статус-коды — без изменений
- **Тесты**: guard-тесты (endpoint smoke 72, circular imports, line count ≤200, routers ≥15), mock.patch targets обновлены в 13 тест-файлах
- **Результат**: 716 passed, 9 xfailed, 0 failures

---

## 07.09.2026

### BL-235 — Редактирование business_context через Settings UI (07.09.2026)
- **web-ui**: секция BUSINESS CONTEXT в settings.html — textarea для редактирования описания бизнеса, кнопка SAVE, flash-уведомление, dual-theme CSS (matrix + light)
- **pm-bot**: поле `business_context` в UserPrefs, GET seed из файла `business-context-brief.md`, AI-agent chat читает из prefs с fallback на файл
- **knowledge-engine**: `signal_orchestrator._load_business_context()` и `research_runner._collect_context()` — приоритет user-prefs через HTTP API, fallback на файл
- **Тесты**: 11 новых/обновлённых тестов (5 signal_orchestrator + 6 research_runner)

---

## 03.09.2026

### Улучшено
- **knowledge-engine**: промпт `signal_extract.txt` переработан по результатам анализа паттернов отклонений (31 из 43 сигналов dismissed). Добавлен scope PM (4 категории исключений), обязательный draft_idea, лимит 1-3 сигнала, глагольные заголовки, запрет трендов и реактивных возможностей. Промпт `signal_report_generate.txt`: секция «Рекомендуемые действия» требует конкретный компонент/API, реализуемость за 1-3 месяца.

### BL-197 — Управление промптами через Settings UI (03.09.2026)
- **pm-bot, knowledge-engine, idea-pipeline**: подсекция PROMPTS в Settings UI — просмотр, редактирование, hot-reload и сброс к дефолтам всех 32 промптов (5 pm-bot, 24 KE, 3 pipeline)
- **pm-bot**: pipeline_client.py — HTTP-клиент к idea-pipeline API (prompts + pipeline run/status/resume/list)
- **knowledge-engine**: API endpoints GET/POST /api/v1/prompts, POST /api/v1/prompts/{name}/reset с hot-reload кэша
- **idea-pipeline**: API endpoints GET/POST /api/v1/prompts, POST /api/v1/prompts/{name}/reset, POST /api/v1/reload-agents
- **pm-bot**: агрегирующие endpoints GET /api/v1/prompts/all, POST /api/v1/prompts/{component}/{name}, POST /api/v1/prompts/{component}/{name}/reset
- **pm-bot**: секция PROMPTS в settings.html — accordion-дерево по компонентам, textarea-редактор, badge переменных, individual save/reset
- **Изменено**: промпты убраны из GET/POST /api/v1/settings (breaking change, перенесены в отдельные endpoints)
- **Инфраструктура**: *.txt.default в .gitignore, prompt_registry.py в каждом компоненте
- **Тесты**: 94 новых теста (19 KE + 28 pm-bot + 15 pipeline + 20 pipeline_client + 4 invalidate + 8 reload)

---

## 25.08.2026

### Исправлено
- **BUG-036**: KE теперь получает user-prefs через HTTP API pm-bot вместо прямого чтения файла. Добавлен PM_BOT_API_URL в docker-compose для KE и ke-cron. 6 unit-тестов для HTTP fallback. 179 дублей протоколов удалено из failed/, 5 августовских протоколов возвращены в pending/ для повторной обработки.

---

## 14.08.2026

### BL-232 — Вынос служебных файлов из vault в Docker volumes (14.08.2026)
- Новый shared volume `platform-data` в docker-compose.yml (монтирован в pm-bot, KE, ke-cron)
- `.system-log.db` → PLATFORM_DATA_PATH (shared volume platform-data)
- `.pm-user-prefs.json` → PM_BOT_DATA_PATH (pm-bot-data volume)
- `.jira-sync-state.json` → PLATFORM_DATA_PATH (shared volume platform-data)
- `.health-history.json` → KE_DATA_PATH (ke-data volume)
- `.meeting-fetcher-state.json` → KE_DATA_PATH (ke-data volume) — hotfix
- `.enrichment-reminders.db` → PM_BOT_DATA_PATH (pm-bot-data volume) — hotfix, исправлено расхождение путей с enrichment_db.py
- Миграция при старте: shared/platform_migrate.py (copy, не delete)
- Env vars: PLATFORM_DATA_PATH, PM_BOT_DATA_PATH, KE_DATA_PATH с fallback на VAULT_PATH
- `domain-config.yaml` остаётся в vault (таксономия знаний)

---

## 13.08.2026

### BL-230 — AI-агент в редакторе идеи (13.08.2026)
- Новый режим работы с ИИ в body-editor: тогл, 3-колоночный layout, чат-интерфейс
- Endpoint POST /api/v1/ai-agent/chat с system prompt (бизнес-контекст + текст идеи)
- Quick-action кнопки: усилить проблему, сформулировать гипотезу, добавить KPI, подготовить PRD
- Настройка модели в Settings: секция AI AGENT (Claude / Ollama / OpenRouter)
- Langfuse трейсинг (trace name: ai-agent-chat)
- User-prefs: поля ai_agent_provider, ai_agent_model

### BL-231 — Ресайз колонок в редакторе идеи (13.08.2026)
- Drag-handle между колонками в body-editor (6px, подсветка при hover)
- Ресайз в 2-колоночном (editor + preview) и 3-колоночном (+ AI чат) режимах
- Пропорции сохраняются в user-prefs (editor_col_split_2, editor_col_split_3)
- Двойной клик по handle — сброс к дефолтным пропорциям
- Блокировка выделения текста при drag (user-select: none, pointer-events: none)
- Responsive: handles скрыты на экранах < 1024px

---

## 11.08.2026

### knowledge-engine
- **fix:** BUG-035 — `dispatch_idea()` в `signal_moderator.py` записывал IDEA только в `raw/inbound/ideas/`, без wiki-копии. IDEA не попадала в enrichment, synthesis и UI. Добавлена запись в `wiki/domains/<domain>/ideas/` через `wiki_domain_dir()`
- **fix:** `dispatch_idea()` — добавлена IDEA-NNNN нумерация (id в frontmatter + имя файла). 19 существующих signal-IDEA переименованы (IDEA-0051..IDEA-0069)
- **fix:** `dispatch_idea()` — генерация IDEA через шаблон `templates/idea.md` (9-блочная структура, decay-поля, readiness, tags) вместо минимального хардкода. 19 существующих файлов мигрированы на шаблон

### shared
- **feat:** `max_idea_number()` в `vault_paths.py` — единая функция поиска max IDEA-NNNN номера (вынесена из pm-bot)

### pm-bot
- **fix:** BUG-034 — `_parse_section()` в `today_parsers.py` не парсил plain-line формат дайджеста (без `- ` или `|`). Добавлен attempt 3: каждая непустая строка = item, пропуск bold-subheaders и group-headers
- **fix:** playground.html — `<think>...</think>` блоки reasoning-моделей (Nemotron, Qwen) убираются из ответа на backend (`re.sub` в `playground_chat()`)
- **fix:** playground.html — max_tokens увеличен с 4096 до 8192 (дефолт), добавлен UI-селектор (4096/8192/16384)
- **feat:** playground — Langfuse трейсинг: trace + generation (success/error) с usage-данными, тег `playground`

---

## 08.08.2026

### knowledge-engine
- **fix:** BUG-033 — новый endpoint `POST /api/v1/signals/{signal_id}/approve`: бизнес-логика approve перенесена из pm-bot в KE (dispatch_idea, frontmatter update)

### pm-bot
- **fix:** BUG-033 — endpoint signal approve переделан в proxy через `ke_client.signal_approve()`. Удалён прямой import `knowledge_engine` (crash 500 в Docker). Удалён `_signal_approve_lock`

---

## 07.08.2026

### shared
- **fix:** BL-207 — Langfuse трейсы показывали NULL: `atexit.register(shutdown)` в `langfuse_client.py`, `try/finally` обёртка в `cli.py`, `input=` в `lf.trace()` в `llm_client.py`
- **fix:** BL-208 — OpenRouter `content: null` от reasoning-моделей вызывал crash. `openrouter_client.py`: обработка `None` → пустая строка. `llm_client.py`: пустой ответ → `RuntimeError` для корректного fallback
- **feat:** Разделение группы `signal_triage` → `signal_triage` (signal_score, quality_check, dedup_check) + `signal_deep` (completeness_check). Дефолт для triage: `gpt-oss-20b:free` → openrouter → claude
- **feat:** Операция `digest` вынесена в отдельную группу с дефолтом `ollama → claude` (промпты до 100K tokens, экономия бюджета OpenRouter)

### knowledge-engine
- **fix:** BL-207 — `_safe_span()` в `signal_orchestrator.py` принимает опциональные `input`/`output`

### pm-bot
- **ui:** today.html — блок "Отчёт" перемещён после "Черновик идеи" в попапе сигнала
- **feat:** settings.html — карточки SIGNAL DEEP и DIGEST для настройки fallback-цепочек

---

## 06.08.2026

### pm-bot
- **fix:** BUG-029 — Фокус дня не отображался из-за emoji-префикса в заголовке дайджеста. `today_parsers.py`: `==` → `in` для contains-проверки

### knowledge-engine
- **fix:** BUG-030 — 75% новостей получали score=0 из-за `<think>` блоков в ответах LLM. `signal_moderator.py`: strip `<think>...</think>` перед JSON-парсингом

---

## 05.08.2026

### knowledge-engine 1.24.0
- **feat:** BL-203 Signal-First Pipeline — перестройка News Moderator pipeline
- **feat:** `generate_analysis_report()` — генерация аналитического отчёта по новости через LLM (AgentLoop + QualityGate)
- **feat:** `extract_signals()` — извлечение уникальных сигналов из отчёта через LLM с dedup
- **feat:** `dispatch_signal()` — создание Signal-документов в `raw/inbound/signals/` (JSON) + `wiki/reports/signals/` (MD)
- **feat:** Новые промпты: `signal_report_generate.txt`, `signal_extract.txt`
- **feat:** `_load_relevance_threshold()` — порог скоринга из user-prefs с fallback на config
- **feat:** `QualityGate` расширен: completeness check для аналитических отчётов
- **refactor:** Удалены legacy-функции `analyze_signal()`, `_build_analysis_prompt()` и промпт `signal_analyze.txt`
- **refactor:** Откат BL-202: удалены endpoints signalIdeaDetail/Approve/Dismiss
- **feat:** Миграционный скрипт `migrate_signal_ideas.py` — IDEA со статусом "Сигнал" → "Отсев"
- **test:** 67 тестов signal_moderator, 68 signal_orchestrator, 59 research_runner, 28 signal triage endpoints, 9 migrate_signal_ideas

### pm-bot 1.27.0
- **feat:** BL-203 Signal triage API: GET /api/v1/signals/list, GET /signals/{id}, POST /signals/{id}/approve, POST /signals/{id}/dismiss
- **feat:** today.html: панель Signal triage (фильтры all/pending/approved/dismissed, карточки, approve/dismiss с 409 conflict handling)
- **feat:** settings.html: слайдер SIGNAL MODERATOR (relevance_threshold 1-10)
- **feat:** api.js: signalsList(), signalDetail(), signalApprove(), signalDismiss()
- **refactor:** Откат BL-202 API methods: signalIdeaDetail, signalIdeaApprove, signalIdeaDismiss удалены
- **fix:** vault_api.py: 4 вызова read_frontmatter() в signal endpoints исправлены (tuple unpacking)
- **test:** 28 тестов signal triage endpoints (test_signal_triage_endpoints.py)

### web-ui 1.32.0
- **feat:** BL-203 today.html: Signal triage панель — карточки сигналов с threat level, score, status badges
- **feat:** CSS: секция 18 (BL-203) в style-today.css — 10 новых классов с prefix `today-signal-`
- **feat:** settings.html: секция SIGNAL MODERATOR с range slider

---

## 04.08.2026

### knowledge-engine 1.23.0
- **feat:** BL-201 ItemState расширен: `relevance`, `reason`, `matched_entities`, `source_url` — scoring-данные сохраняются в run JSON для frontend-отображения

### pm-bot 1.26.0
- **feat:** BL-201 Signal Moderator нод в Research Queue UI — активация ghost-нода в полноценный интерактивный нод
- **feat:** Proxy chain для signal endpoints: `ke_client.signal_runs()`, `signal_run_detail()` → `vault_api.py` → `api.js`
- **feat:** Карточки сигналов с reaction-бейджами (SKIP/IDEA/REPORT/ERROR), score/threshold display
- **feat:** Drawer с деталями сигнала: relevance scoring, reason, matched entities, source URL, quality/dedup gates, iterations history
- **feat:** Селектор прогонов (dropdown) для переключения между историческими run-ами
- **feat:** Edge-анимация sm→queue при reports > 0, alert-стиль нода при errors > 0
- **feat:** CSS: 15 новых классов с prefix `rq-signal-` для dual-theme (matrix + light)

### knowledge-engine 1.22.1
- **fix:** BUG-030 outcome=null при повторном запуске research-runner — recovery через `_extract_and_classify` если outcome отсутствует в frontmatter существующего отчёта
- **fix:** BUG-031 ideas count в RunSummary всегда 0 — подсчёт по `reaction == "idea"` вместо подстроки `"ideas"` в filename
- **fix:** BUG-032 convert-news-digest обёрнут в `LoggedProcess("convert-news-digest")` для видимости в system-log
- **fix:** BUG-033 idea_extractor: обрезанный JSON при max_tokens=2000 — увеличен до 4000, добавлен repair truncated JSON (rfind последнего полного объекта)
- **test:** 16 новых тестов (6 research_runner, 6 convert-news-digest, 4 idea_extractor truncation repair)

---

## 03.08.2026

### knowledge-engine 1.21.0
- **feat:** BL-198 Research Outcome — автоматический вердикт LLM после генерации отчёта (idea/insight/not_relevant/error)
- **feat:** `extract_ideas_full()` в idea_extractor — расширенная версия с возвратом no_ideas_reason
- **feat:** `_extract_and_classify()` в research_runner — шаг 8a: extract_ideas → classify → dispatch_idea → frontmatter + JSON
- **feat:** API `_build_reports_list()` — список research-отчётов с frontmatter для UI
- **feat:** Outcome в processed[] API-ответа, массив reports[] в /api/v1/research-queue/status
- **fix:** glob-паттерн `report-*.md` → `*-{slug}*.md` в _match_report() и reports_count (регрессия от переименования)
- **test:** 20 новых тестов (extract_ideas_full, outcome classification, API reports_list, match_report)

### knowledge-engine 1.22.0
- **feat:** BL-199 `_build_extracted_ideas()` — сбор idea-файлов по ideas_refs из отчётов
- **feat:** BL-199 `_parse_idea_body()` — парсинг markdown body идей (problem/solution/rationale)
- **feat:** BL-199 `extracted_ideas[]` в API `/research-queue/status`
- **feat:** BL-199 `ideas_refs` в `_build_reports_list` для обратного маппинга
- **test:** 12 новых тестов (parse_idea_body, build_extracted_ideas, reports_list ideas_refs)

### web-ui 1.31.0
- **feat:** BL-199 extract_ideas нод активен — кликабельный, с бейджем количества идей
- **feat:** BL-199 Карточки идей: domain/priority бейджи, ссылка на исходный отчёт
- **feat:** BL-199 Drawer идеи: проблема, решение, анализ, Obsidian links на идею и отчёт
- **improve:** Ссылка "Открыть в Obsidian" в drawer Processed и Reports заменена на "Открыть отчет" — переход на report.html с автовыбором отчёта
- **improve:** report.html поддерживает URL-параметр `?file=filename` для прямого открытия отчёта
- **improve:** Поиск (search overlay): клик по найденному отчёту переходит на report.html?file= вместо report.html?highlight=

### web-ui 1.30.0
- **feat:** BL-198 Reports нод кликабельный — список research-отчётов с outcome-бейджами
- **feat:** Outcome-бейджи в карточках processed и reports (Идея/Инсайт/Не релевантно/Ошибка)
- **feat:** Расширение drawer: outcome, извлечённые идеи, причина отсутствия идей, Obsidian link для отчётов
- **fix:** Нейминг отчётов `report-{slug}-{date}.md` → `{date}-{slug}.md`
- **fix:** Клик по нодам Processing и extract_ideas теперь закрывает открытый список (раньше игнорировался)

### knowledge-engine 1.20.2
- **fix:** BUG-028 `process_task` сохранял мусорные отчёты (completeness=0) вместо отклонения: reject gate при score < threshold → failed/, полная перегенерация при score < 2, порог из `config.completeness_threshold`
- **test:** 4 новых теста в `test_research_runner.py` (catastrophic regeneration, rejected→failed, partial supplement, score=threshold)

### knowledge-engine 1.20.1
- **fix:** BUG-027 `dispatch_report` записывал домен источника новости (skift.com, TechCrunch) в поле `competitor` research-queue JSON вместо реального конкурента
- **fix:** промпт `signal_analyze.txt` — LLM теперь извлекает `competitor` в `report_brief`; `signal_orchestrator._process_item` передаёт entity из `scoring.matched_entities` как fallback в `_handle_report`/`dispatch_report`
- **test:** 3 новых теста в `test_signal_moderator.py` (competitor из параметра, приоритет LLM report_brief, пустое значение при отсутствии конкурента)

---

## 03.08.2026

### web-ui 1.29.0
- **feat:** BL-195 Research Queue UI — pipeline graph страница `research.html` (388 строк HTML + 585 строк CSS)
- **feat:** Pipeline graph в стиле n8n: 7 узлов (Signal Moderator, Queue, Processing, Processed, Reports, extract_ideas, Failed), SVG edges с dash-offset анимацией
- **feat:** Drawer с деталями задания: topic, questions, scope, signal_source (кликабельная ссылка), completeness badge
- **feat:** Кнопки Run All и Retry, auto-refresh 60s, responsive layout (< 900px вертикальный flow)

### knowledge-engine 1.20.0
- **feat:** BL-195 KE API: 3 endpoint (GET status, POST run, POST retry) + 5 helper-функций + 2 Pydantic-модели
- **feat:** `retry_failed_task()` в research_runner.py — перемещение failed→queue + повторный запуск

### pm-bot 1.21.0
- **feat:** BL-195 ke_client: 3 proxy-функции (research_queue_status/run/retry)
- **feat:** BL-195 vault_api: 3 proxy-endpoint + ResearchRetryProxyRequest
- **feat:** BL-195 api.js: 3 метода (researchStatus, researchRun, researchRetry)
- **feat:** BL-195 components.js: sidebar-ссылка RESEARCH в группе МОНИТОРИНГ

---

## 03.08.2026

### knowledge-engine 1.19.0
- **feat:** BL-194 Research Runner — модуль обработки research-queue (research_runner.py, ~350 строк)
- **feat:** CLI команда `research-run` с параметрами --file, --method, --notify, --dry-run
- **feat:** Cron задача ke-research (08:05 Пн-Пт)
- **feat:** Промпт `research_report.txt` для генерации аналитических отчётов
- **feat:** 48 unit-тестов (test_research_runner.py)

### shared 0.7.4
- **feat:** vault_paths: функции raw_research_queue(), raw_research_queue_processed(), raw_research_queue_failed()
- **feat:** llm_client: маппинг operation research_report → signal_analysis
- **fix:** system_log: добавлен process type `research-runner` в VALID_PROCESS_TYPES (14 типов)

---

## 03.08.2026 — fix: quality_gate._extract_fields crash на reaction=report (BUG-026)

- fix(knowledge-engine): `_extract_fields` проверял наличие ключа `"idea_draft" in analysis` вместо truthiness `analysis.get("idea_draft")`. Для `reaction=report` ключ всегда есть (dataclass __dict__), но значение None → `None.get("title")` → crash.
- test: 4 новых теста в `test_quality_gate.py::TestExtractFieldsBug026` (report_brief, idea_draft, flat fallback, empty fallback)

---

## 03.08.2026 — feat: Signal Chain Settings — UI настройка LLM-цепочек для News Moderator (BL-192)

- feat(shared): `_DEFAULT_FALLBACK` для signal_triage/analysis/escalation → `["openrouter", "claude"]`
- feat(pm-bot): API поддержка signal_*_fallback в GET/PUT /api/v1/user-prefs
  - UserPrefs model: 3 новых поля
  - Валидация, нормализация, дефолты — аналогично capture/transcription/analysis/pipeline
- feat(web-ui): 3 новые группы в Settings → FALLBACK CHAINS
  - SIGNAL TRIAGE (signal_score, quality_check, dedup_check, completeness_check)
  - SIGNAL ANALYSIS (signal_analyze, report_to_ideas, trend_detect)
  - SIGNAL ESCALATION (signal_analyze_escalation)
  - Drag-and-drop, inline OpenRouter model select — повторяет существующий паттерн

---

## 03.08.2026 — feat: News Digest Converter — конвертер daily-news markdown → JSON (BL-191)

- feat(knowledge-engine): `news_digest_converter.py` — парсер daily-news markdown → JSON-дайджест
  - `parse_daily_news()` — regex-парсинг markdown: frontmatter date, items (`**[title](url)** — source`), multiline summary, пропуск italic-блоков
  - `convert_news_digest()` — оркестратор: поиск файла, skip if exists, запись JSON в `raw/inbound/news/{date}-digest.json`
- feat(knowledge-engine): CLI `convert-news-digest` — subparser с `--vault` и `--date` (default: вчера)
- feat(ke-cron): cron job `ke-convert-news` — Пн-Пт 07:55, перед moderate-news (08:00)
- test: 13 тестов (7 parse + 6 convert)

---

## 03.08.2026 — feat: Agent Observability — мониторинг и аналитика агентной цепочки (BL-190)

- feat(knowledge-engine): Langfuse e2e trace для Signal Moderator
  - `_safe_span()` / `_safe_end_span()` — graceful degradation при недоступности Langfuse
  - Trace `signal-moderator/{run_id}` с session_id linkage
  - Spans: item, score, analyze, gate, dispatch — полная иерархия flow
- feat(knowledge-engine): Persistence решений агентов в RunState
  - `iterations_history` — attempt, quality_score, critique, escalated, operation
  - `gate_results` — quality, dedup gates с passed/score/details
  - `reaction` — skip/idea/report per item
  - `completed_at` — точное время завершения прогона
- feat(knowledge-engine): 3 HTTP-endpoints диагностики (AC-13..AC-17)
  - `GET /api/v1/signals/runs` — список прогонов с per-item breakdown
  - `GET /api/v1/signals/runs/{run_id}` — полный RunState прогона
  - `GET /api/v1/signals/stats` — агрегированная статистика (avg quality, escalation rate, top entities)
- feat(knowledge-engine): CLI `signal-status` (AC-18..AC-21)
  - `--last N` — таблица последних N прогонов
  - `--run ID` — per-item detail с iterations и gate results
  - `--format json|table` — выбор формата вывода
- feat(knowledge-engine): LoopIteration расширен полями `escalated`, `critique_text`
- feat(knowledge-engine): RunState backward/forward compatibility через field filtering
- test: 47 новых тестов (6 agent_loop + 15 orchestrator + 14 API + 8 CLI + 4 hotfix)
- fix(api): status override в signals_run_detail — RunState.status → run_status
- fix(knowledge-engine): graceful handling при отсутствии дайджеста — `_auto_detect_digest()` возвращает None вместо crash, `process_digest()` завершается с пустым RunState (BL-189 hotfix)

---

## 02.08.2026 — feat: News Moderator — агентная цепочка анализа новостей (BL-189)

- feat(knowledge-engine): Агентная цепочка автоматического анализа новостей
  - `signal_orchestrator.py` (~440 LOC): оркестратор с persisted RunState (JSON), resume after crash, async report tracking
  - `signal_moderator.py` (~370 LOC): скоринг релевантности, содержательный анализ, dispatch идея/отчёт
  - `signal_memory.py` (~280 LOC): persistent SQLite memory (signals, entity_trends, trend_alerts), weekly trend detection (4 типа: spike, sustained, new_entrant, escalation)
  - `quality_gate.py` (~308 LOC): 4 quality gates — dedup (LLM similarity ≥8), quality check (5 критериев, score<6 → agent loop), report completeness, domain correctness (rule-based)
  - `agent_loop.py` (~171 LOC): retry с critique injection, escalation к Opus-class на последней итерации
  - `idea_extractor.py` (~155 LOC): извлечение идей из research-отчётов
  - 6 промптов: signal_score, signal_analyze, quality_check, dedup_check, completeness_check, report_to_ideas
- feat(shared): 3 новых LLM operation group (`signal_triage`, `signal_analysis`, `signal_escalation`), 8 операций с fallback chains
- feat(shared): 2 новых process type в system_log: `signal-moderator`, `trend-detect`
- feat(shared): 20 параметров moderator в settings.py + settings.yaml
- feat(docker): ke-data volume, cron moderate-news (08:00 Пн-Пт), trend-detect (06:00 Пн)
- feat(knowledge-engine): CLI-команды `moderate-news` и `trend-detect` с --notify
- test: 194 юнит-теста для всех новых модулей
- docs: vault-структура (wiki/signals/, raw/inbound/news/), business-context-brief.md
- fix(docker): `pull: false` в build-секциях — BuildKit не обращается к Docker Hub при наличии локального образа
- fix(knowledge-engine): относительные импорты в signal_orchestrator.py (from app.* → from .*)

---

## 27.07.2026 — refactor: Удаление cron weekly_report

- refactor(pm-bot): Удалён автоматический cron-джоб генерации еженедельного отчёта (scheduler.py). Настройки report_time/report_day убраны из Settings. Ручная генерация через UI (кнопка REGENERATE) по-прежнему доступна.
- feat(web-ui): Auto-refresh блока «Встречи сегодня» на today.html каждые 15 минут (BL-188)

---

## 24.07.2026 — feat: TTL для уведомлений Meeting Fetcher (BL-173)

- feat(knowledge-engine): Автоудаление summary-уведомления Meeting Fetcher через 5 минут
  - `_notify()`: параметр `ttl: int | None` для opt-in автоудаления (backward compatible)
  - `_delete_message()`: callback для `threading.Timer`, вызывает Telegram `deleteMessage` API
  - Константа `_NOTIFY_TTL_SECONDS = 300`
  - Callsite: только summary fetch (`"N писем поставлено в очередь"`)

---

## 24.07.2026 — fix: Visual diff today.html (BL-168)

- fix(web-ui): Разделение визуалов для «Идёт сейчас» (`meeting.current`) и «Следующая» (`meeting.active`) встреч в timeline
  - Новый CSS-класс `.meeting.current` — amber-градиент по аналогии с focus-card
  - `.meeting.active` — фиолетовый border (#D6C8F5) + светлый фон (#FBF9FF)

---

## [pm-bot 1.19.0 / web-ui 1.27.0] — 23.07.2026

### Добавлено
- **BL-172**: Настройка CalDAV в Settings UI
  - Секция «CALENDAR» на settings.html: 4 поля (username, app password, timezone, URL)
  - `POST /api/v1/test-caldav` — проверка подключения к CalDAV-серверу
  - Маскировка пароля CalDAV в GET /user-prefs (sentinel `"••••••••"`)
  - `calendar_client.py`: динамические credentials из user-prefs с fallback на env
  - Инвалидация CalDAV-кэша при сохранении settings
  - `api.testCaldav()` — frontend API метод
  - `conference_url`: извлечение URL конференции из iCal (URL property → location → description)
  - today.html: кликабельная ссылка на конференцию в timeline card и drawer, автолинковка URL в описании

---

## 23.07.2026 — feat: Реорганизация меню + страница TODAY (BL-168)

- feat(web-ui): Реорганизация sidebar-навигации — 4 группы (Рабочий день, Знания, Мониторинг, Система), collapse группы «Система»
- feat(web-ui): Новая страница TODAY — стартовая страница рабочего дня с фокусом дня, дайджестом, TODO, встречами, отчётами и новостями
- feat(pm-bot): CalDAV-интеграция Яндекс Календаря (calendar_client.py) — получение встреч, определение статусов, сопоставление с протоколами
- feat(pm-bot): Парсеры vault-файлов (today_parsers.py) — morning-digest, todo.md, daily-news
- feat(pm-bot): API для TODO CRUD (GET/POST/PATCH /api/v1/todos)
- feat(pm-bot): API для TODAY-данных (GET /api/v1/today/digest, /today/news, /today/meetings)
- feat(pm-bot): DS v2 CSS-токены (--a, --g, --b, --p, --r) в light и matrix темах

### Hotfixes TODAY page (Phase 4.1 live testing)
- fix(web-ui): renderMarkdown — поддержка таблиц (`|`-delimited → `<table class="md-table">`)
- fix(web-ui): renderMarkdown — поддержка заголовков (h3/h4), списков (`- `→`<ul><li>`), пустых строк
- fix(web-ui): Иконки дайджеста — переход с Unicode/emoji на Material Symbols Outlined (единый стиль)
- fix(web-ui): Полный дайджест в попапе — markdown-форматирование, убран `white-space:pre-wrap`
- fix(web-ui): Блок «Последний отчёт» — открытие в попапе вместо редиректа, markdown-рендеринг, min-width 820px
- fix(web-ui): Убрана кнопка «Сохранить как решение» из блока отчёта
- fix(pm-bot): `_extract_report_date` — приоритет: frontmatter `date:` → `created:` → regex имени файла → `0000-00-00` (без mtime)
- fix(pm-bot): `list_reports` — опциональная фильтрация по `?type=` (today использует `weekly-status-report,feature-analysis-report`, reports.html — без фильтра)
- fix(pm-bot): Валидация дат из имён файлов (месяц 1-12, день 1-31)
- fix(web-ui): style-today.css — стили `.md-table`, `.digest-detail h3/h4/ul/li`, `.today-modal.wide`

---

## 22.07.2026 — feat: Pipeline fallback chains (BL-167)

### BL-167: Перевод idea-pipeline на shared/llm_client fallback chains (22.07.2026)
- Pipeline = 4-я группа операций (pipeline_analyst, pipeline_pm, pipeline_decomposer)
- BaseAgent/DecomposerAgent переведены на shared/llm_client.call() с fallback-цепочками
- PipelineClaudeClient удалён (174 строки), _ENV_VAR_MAP удалён из config.py
- Ручные Langfuse trace/span убраны из orchestrator — автоинструментация через call_detailed()
- Settings UI: карточка PIPELINE в секции FALLBACK CHAINS (drag-and-drop цепочка)
- _migrate_legacy_prefs: автоматическая миграция pipeline_fallback для существующих пользователей
- fix: pipeline_fallback добавлен в UserPrefs, _DEFAULT_USER_PREFS, GET/PUT валидацию vault API
- idea-pipeline v1.2.0, shared v0.7.2

---

## 21.07.2026 — feat: Langfuse LLM Observability (BL-166)

### BL-166: Langfuse LLM Observability (21.07.2026)
- Self-hosted Langfuse v2 (Docker: langfuse + langfuse-db, порт 3100)
- Инструментация shared/llm_client.py:call_detailed() — автоматические трассировки для всех LLM-вызовов
- Token usage проброс: Anthropic SDK и OpenRouter -> input_tokens/output_tokens в provider_record
- shared/langfuse_client.py — singleton с graceful degradation
- Sidebar ссылка LLM TRACES -> Langfuse UI
- Langfuse SDK v2.x (совместим с сервером v2)
- idea-pipeline инструментация (T-07, AC-03 blocked — требует BL-167 для полной работы)

---

## 17.07.2026 — fix: _CLOSED_STATUSES сырые значения вместо нормализованных (BUG-025, BL-165)

Задачи со статусом "Отменена" в Jira не распознавались как закрытые при jira-sync: `_CLOSED_STATUSES` содержал сырые русские названия статусов, но проверка выполнялась после `normalize_status()`, который уже преобразовал их в нормализованные значения.

### knowledge-engine 1.15.1
- **fetcher.py**: `_CLOSED_STATUSES` заменён на нормализованные значения (`done`, `deploy`, `staging`, `cancelled`) — 4 элемента вместо 7 сырых. Задачи со статусом "Отменена" теперь корректно помечаются `mark_closed()` в sync state

---

## 14.07.2026 — fix: Доработка epic drawer по прототипу (BUG-024, BL-162)

Исправления расхождений epic drawer с прототипом: отступы, локализация, логика отображения данных.

### web-ui 1.26.4
- **roadmap.html**: локализация drawer (Обзор/Описание/История, Прогресс, Готовность эпика, Основная информация, Задачи Jira и др.)
- **roadmap.html**: секция «Задача эпика в Jira» — показывает jira_key/title/status самого эпика вместо дочернего тикета
- **roadmap.html**: кнопка PUSH_EPIC_TO_JIRA на вкладке Обзор (v-if="!drawerEpic.jira_key"), удалена с вкладки Jira
- **style-light.css**: `.epic-tab-panel { padding: 20px 22px }` — компенсация обнулённого padding .task-drawer-body (BUG-024)
- **style.css**: `.task-drawer { min-width: 780px }` (было 600px)

### BACKLOG.md
- **BL-163** добавлен: Jira sync partial update вместо full rewrite (epic_key затирается при re-sync)

---

## 13.07.2026 — feat: Просмотр тела эпика в drawer roadmap (BL-162)

Кнопка-тогглер SHOW_BODY / SHOW_TICKETS в drawer эпика на roadmap.html. Позволяет прочитать полный markdown body эпика (все секции: архитектура, решения, контекст) без переключения в Obsidian.

### pm-bot 1.18.2
- **vault_api.py**: поле `body` добавлено в ответ `GET /api/v1/epics` (полный markdown без frontmatter)
- **roadmap.html**: `epicViewMode` ref (tickets/body), кнопка-тогглер `.epic-toggle-btn`, `<template v-if>` переключение между тикетами и body, сброс при смене эпика/закрытии drawer
- **style.css**: стили `.epic-toggle-btn` (border, cyan, uppercase)
- **style-light.css**: override hover для light-темы (var(--cyan-bg))

---

## 13.07.2026 — feat: Поиск и фильтрация отчётов (BL-161)

Добавлены поиск по имени/заголовку и фильтрация по типу отчёта на страницу report.html.

### pm-bot 1.18.1
- **vault_api.py**: новая функция `_extract_report_type(text)` — лёгкий парсинг YAML frontmatter для извлечения `type:`, fallback `"other"`. Поле `type` добавлено в ответ `GET /api/v1/reports`
- **report.html**: поисковая строка (v-model, case-insensitive по title/filename) + фильтр-чипы по типу (динамические из уникальных type, с каунтерами, single-select). Computed `filteredReports`/`typeChips`. Watcher автовыбора при фильтрации. Пустое состояние "Ничего не найдено"
- **style-light.css**: override `.report-type-chip.active` (var(--cyan-bg)) и `.report-search input` (var(--bg)) для light-темы
- **tests/test_report_type_extraction.py** (новый): 20 unit-тестов (все типы, кавычки, пустые значения, без frontmatter)

---

## 13.07.2026 — fix: Jira sync не обновляет кастомные vault-файлы (BUG-023, BL-160)

Jira sync не обновлял статус vault-файлов с кастомными именами (E-15-*.md, E-18-*.md), созданных через PM Assistant. Sync искал файлы только по имени `{JIRA_KEY}.md`, игнорируя файлы с `jira_key` в frontmatter.

### knowledge-engine 1.15.1
- **fetcher.py**: новая функция `_find_vault_file_by_jira_key(domain, jira_key, artifact_types)` — fallback-поиск vault-файла по полю `jira_key` в YAML frontmatter
- **fetcher.py** (секция 6 — UPDATED): если `{KEY}.md` не существует → fallback поиск → точечное обновление через `frontmatter_utils.update_frontmatter` (status, synced_at, updated_at) без полного rewrite
- **fetcher.py** (секция 7 — CLOSED): аналогичный fallback перед regex-заменой status
- **fetcher.py** (`import_single_issue`): fallback предотвращает создание дубликатов при повторном импорте
- **tests/test_jira_sync_custom_files.py** (новый): 11 unit-тестов (find, updated fallback, closed fallback, import fallback, regression)

---

## 11.07.2026 — feat: Экспорт markdown-отчётов в PDF (BL-159)

Экспорт wiki-отчётов в PDF с полной стилизацией. Серверный рендеринг через WeasyPrint + markdown-it-py. Шрифт Inter (кириллица + латиница), монохромные emoji (Noto Emoji), таблицы с рамками, цветные заголовки.

### pm-bot 1.18.0
- **pdf_exporter.py** (новый): модуль конвертации markdown → HTML → PDF. Поддержка: frontmatter stripping, wikilinks, GFM-таблицы, blockquotes, code-блоки. Защита от внешних URL (url_fetcher), лимит 1MB
- **vault_api.py**: endpoint `POST /api/v1/reports/{filename}/pdf` — валидация, LoggedProcess, Content-Disposition attachment
- **api.js**: функция `exportPdf()` — fetch + blob download (первый бинарный download в проекте)
- **report.html**: кнопка EXPORT_PDF (yellow, loading/disabled состояния)
- **pdf-export.css** (новый): стили PDF — Inter, Fira Code для code, таблицы с рамками, цветные заголовки h1-h3
- **Dockerfile**: системные зависимости WeasyPrint (libpango, libcairo, fontconfig), шрифты Inter/Fira Code/Noto Emoji в /usr/share/fonts/custom/
- **requirements.txt**: weasyprint>=62.0, markdown-it-py>=3.0.0, mdit-py-plugins>=0.4.0

---

## 09.07.2026 — fix: Jira Import direct key в extended capture terminal (BUG-021, BUG-022)

Исправлена работа поля прямого ввода ключа Jira в расширенном режиме capture terminal на ideas.html.

### web-ui 1.26.1
- **components.js** (capture-terminal):
  - BUG-021: `canImport` теперь учитывает `directKey` — кнопка IMPORT активна при вводе ключа без выбора из списка
  - BUG-021: `importSelected()` парсит `directKey` (поддержка голого ключа SUP-1234 и полного URL), добавляет в очередь импорта, очищает поле после завершения
  - BUG-022: `filteredTickets` фильтрует список задач по введённому ключу (substring match, case-insensitive)
  - Обновлена подсказка footer: "Выбери проект или введи ID"

---

## 06.07.2026 — feat: Фильтрация моделей OpenRouter в Settings и Playground (BL-158) + BUG-020

Searchable dropdown для выбора моделей OpenRouter вместо обычного `<select>`. Текстовый фильтр по вхождению подстроки в имя или id модели (case-insensitive). Решает проблему навигации по большому списку моделей OpenRouter API (сотни позиций).

### web-ui 1.26.0
- **components.js**: новый компонент `searchable-model-select` — кастомный dropdown с текстовым фильтром, autofocus при открытии, закрытие по клику вне, compact-режим для inline в fallback-цепочке
- **settings.html**: замена глобального `<select>` OPENROUTER_MODEL и inline `<select>` в fallback-шагах на `<searchable-model-select>`
- **playground.html**: условный рендеринг — `searchable-model-select` при провайдере OpenRouter, стандартный `<select>` для Claude/Ollama
- **style.css**: CSS model-search-* вынесен из inline `<style>` settings.html и playground.html в общий файл (устранено дублирование)

### pm-bot 1.17.1
- **vault_api.py**: `GET /api/v1/playground/providers` — OpenRouter теперь отдаёт live-список моделей через `list_models()` (TTL-кэш 1ч) вместо хардкода из 3 моделей

### shared 0.7.1
- **openrouter_client.py**: детальное логирование raw-ответа при ошибке парсинга (BUG-020) — `raw_body[:2000]`, model name, response keys. Catch `TypeError` для нестандартных структур. Отдельный catch для невалидного JSON

### BUG-020: OpenRouter Nemotron 3 Ultra parse error
- Nemotron иногда возвращает HTTP 200 без ключа `choices` (нестабильность free-tier). Парсер бросает KeyError, fallback-цепочка переходит к следующей модели. Не баг в коде — нестабильность upstream. Логирование добавлено для диагностики. Статус: OPEN

### Спека: docs/openrouter-model-filter/ (requirements, design, tasks — 4 задачи)

---

## 01.07.2026 — feat: Множественный выбор моделей OpenRouter + динамический список из API (BL-155, BL-156)

Расширение поддержки OpenRouter: live-запрос актуального списка моделей с TTL-кэшем, мультимодельные fallback-цепочки. Пользователь теперь может добавить несколько шагов OpenRouter подряд с разными моделями в одну цепочку.

### shared 0.7.0
- **openrouter_client.py**: `list_models(api_key, ttl_seconds)` — live-запрос к OpenRouter API с in-memory кэшем (TTL 1ч), graceful fallback на хардкод-список при ошибке
- **settings.py**: новый ключ `cache_ttl.openrouter_models_seconds: 3600` (управляет TTL кэша моделей)
- **llm_client.py**: `_normalize_step()`, `_default_model_for()` — нормализация шага цепочки (legacy-строка ↔ объект {provider, model}); `_resolve_chain()` возвращает список объектов вместо строк; backoff 0.7s между смежными openrouter-шагами после 429 (rate limit); расширение `provider_record` с полями `chain`, `used_model`, `used_step_index`; формат ошибки "openrouter:модель" для шагов openrouter в `errors[]`
- **tests**: +50 unit-тестов в test_llm_client.py, test_openrouter.py (T-01..T-05: 0 new failures, 5 pre-existing задокументированы)

### pm-bot 1.17.0
- **app/vault_api.py**: `GET /api/v1/openrouter-models` — отдаёт live-список (schema: {models, source, cached, fetched_at, count}); `PUT /api/v1/user-prefs` — валидирует openrouter-шаги (обязательна непустая model), дедупирует смежные дубли, сохраняет в формате {provider, model}; `GET /api/v1/user-prefs` — нормализует цепочки в объектный формат для UI
- **web/settings.html**: редактор fallback-цепочек теперь поддерживает несколько openrouter-шагов с инлайн-селектором модели, пометка "резервный список" при fallback-источнике, бейдж "OpenRouter: <имя модели>" на карточке шага, клиентская валидация (нельзя сохранить openrouter-шаг без модели)
- **web/system-log.html**: при логировании операций видно какая именно модель OpenRouter использовалась на каждом шаге цепочки и какая упала (поле `used_model`, формат ошибки "openrouter:модель")
- **tests**: +37 unit-тестов в test_openrouter_api.py, test_user_prefs.py (T-06..T-08: 0 new failures)

### Тесты (Phase 4.1 — полный test suite)
- **pytest shared/ -q**: 121 passed, 5 pre-existing failed (не связаны с фичей)
- **pytest pm-bot/ -q**: 455 passed, 12 xfailed (новых регрессий нет)
- **Монорепо (full test suite)**: 1580 passed, 8 pre-existing failed, 0 new failures

---

## 01.07.2026 — feat(knowledge-engine): llm_wiki Cowork Context (BL-151)

Детерминированная генерация `_cowork-session.md` для Claude Cowork — контекстный файл из 5 секций wiki (дейли, открытые задачи, эпики, решения, активность LOG.md). Без LLM.

### knowledge-engine
- **cowork_context.py** (NEW): `generate_cowork_session()` — 5 коллекторов, frontmatter + vault_stats, atomic_write, truncation при >200 задач
- **cli.py**: CLI-команда `cowork-context` (LoggedProcess + regenerate_index + generate_cowork_session)
- **api.py**: `POST /api/v1/cowork-context` — endpoint #29

### shared
- **system_log.py**: новый process type `cowork-context` в VALID_PROCESS_TYPES (13 типов)
- **vault_paths.py**: `llm_wiki_cowork_session()` — путь к `_cowork-session.md`

### pm-bot
- **system-log.html**: option `cowork-context` в dropdown фильтра

### инфраструктура
- **docker-compose.yml**: ke-cron — cron job `0 1 * * *` (cowork-context, ежедневно 01:00)

### тесты
- **test_cowork_context.py** (NEW): 15 unit-тестов (empty vault, sorting, filtering, limits, broken frontmatter, schema)

---

## 01.07.2026 — fix(system-log): fallback errors отображение

- **shared/llm_client.py**: переименован ключ `errors` → `fallback_errors` в details success-записей system_log. Error-path без изменений.
- **web-ui/system-log.html**: fallback_errors рендерятся отдельно — метка "FALLBACK", opacity 0.6. Не смешиваются с реальными ошибками.

---

## 01.07.2026 — Context Compaction Phase 2: Автоматизация (BL-147)

Автоматическая генерация дайджестов при изменении wiki/ + waterfall context assembly для LLM-вызовов. Kill switch через env переменные (DIGEST_ENABLED, DIGEST_CONTEXT_SOURCE) — по default ничего не меняется.

### knowledge-engine 1.14.0
- **watcher.py**: DigestHandler — auto-digest при DIGEST_ENABLED=1, debounce 5s, body_hash check, условная регистрация на все wiki/ директории
- **api.py**: 3 новых эндпоинта — POST /api/v1/digest/generate, POST /api/v1/digest/bulk, GET /api/v1/digest/status

### pm-bot 1.16.0
- **context_assembler.py** (NEW): waterfall сборка контекста из llm_wiki/ — 3 уровня (one-liners ≤3000 tok, core-digests ≤10000 tok, extended-digests ≤6000 tok). Kill switch DIGEST_CONTEXT_SOURCE=wiki (default). Fallback на wiki/ в режиме auto. touch() для core/extended, НЕ для one-liners.
- **claude_client.py**: _get_digest_context() injection в _build_idea_prompt() — digest context подмешивается в промпт перед raw_text
- **reporter.py**: digest context injection в generate_weekly_report() — one-liners добавляются в контекст отчёта
- **ke_client.py**: +3 функции: digest_generate, digest_bulk, digest_status
- **enrich_creative_recall()**: обогащение creative recall one-liner'ами из llm_wiki/ (touch NOT called)
- **requirements.txt**: +tiktoken>=0.7.0

### Тесты
- test_digest_watcher.py: 18 тестов (debounce, should_process, start_watch)
- test_context_assembler.py: 37 тестов (waterfall, tier filter, fallback, creative recall)
- test_digest_context_integration.py: 14 тестов (kill switch, injection, reporter)
- test_api_digest.py: 11 тестов (status, generate, bulk)

---

## 01.07.2026 — Context Compaction Phase 1 (BL-147)

Offline-пайплайн генерации LLM-оптимизированных дайджестов из wiki-артефактов. 3-уровневая структура: one-liner (≤30 токенов), core-digest (200-500 токенов), extended-digest (≤2000 токенов). Digest'ы хранятся в vault/llm_wiki/, зеркалируя структуру wiki/. Интеграция с decay engine (BL-110): tier/relevance из оригиналов wiki/.

### shared 0.5.1
- **vault_paths.py**: 6 новых функций llm_wiki_*() — пути для слоя 1' (llm_wiki_root, llm_wiki_domain_dir, llm_wiki_meetings, llm_wiki_daily_logs, llm_wiki_reports, llm_wiki_index_file)
- **llm_client.py**: операция "digest" добавлена в hybrid routing (Ollama для генерации дайджестов)

### knowledge-engine 1.13.0
- **digest/** (NEW, 6 модулей): пакет генерации дайджестов
  - `generator.py`: generate_digest (единичная генерация + retry с feedback), generate_bulk (массовая с фильтрами), regenerate_index (сортировка по tier priority)
  - `paths.py`: wiki_to_llm_wiki / llm_wiki_to_wiki path mapping, ensure_llm_wiki_structure
  - `templates.py`: detect_type (frontmatter → path → fallback), 15 типов артефактов, required fields
  - `token_counter.py`: tiktoken cl100k_base, count_tokens / count_sections (4 секции)
  - `validator.py`: 6 проверок — token budgets, required fields (regex), source exists, changelog, key-value format (≥70%), dependency warnings
  - `__init__.py`: 11 экспортов
- **prompts/**: digest.txt (base) + 12 type-specific промптов (prd, decision, sprint, meeting, competitor, jira, idea, epic, daily, bug, knowledge, userstory)
- **cli.py**: 5 новых команд — digest, digest-bulk, digest-index, digest-audit, digest-status
- **requirements.txt**: + tiktoken>=0.7.0

### Тесты
- `test_digest.py`: 39 unit-тестов (paths, token_counter, templates, validator, generator). 0 new failures.
- Pre-existing: 3 failure в test_jira_search.py (JQL quoting), не связаны с BL-147.

---

## 30.06.2026 — BUG-019: enrich NoneType на пустом frontmatter tags

### knowledge-engine 1.12.1
- **enricher.py / vault_index.py / matcher.py**: фикс `'NoneType' object is not iterable` — frontmatter `tags:` пустой → PyYAML `None` → `metadata.get("tags", [])` возвращал `None` (ключ есть, дефолт не применяется) → итерация None в `vault_index.search`. Защита `or []` в 3 точках (enricher.py:44, vault_index.py:136 латентная, matcher.find_links). Затрагивало enrichment всех протоколов встреч (non-fatal — секция связей молча пропускалась). Обнаружен на e2e BL-145. Регресс-тест `test_enricher_none_tags.py` (7 кейсов).

---

## 30.06.2026 — Meeting Processing Queue (BL-145)

Рефакторинг обработки протоколов встреч: синхронный `fetch_new_meetings` разрезан на три независимые фазы, связанные файловой очередью `raw/meeting-queue/{pending,processing,done,failed}/`. Получение транскриптов (IMAP + локальный watcher) развязано с тяжёлым LLM-этапом.

### shared 0.4.0
- **meeting_queue.py** (NEW): enqueue-ядро файловой очереди — `Unit`, `make_unit_id`, `build_meta`, `enqueue` (атомарная запись `.meta.json`→`.txt`, idempotent), path-хелперы. Доступно обоим контейнерам (KE + pm-bot линкуют shared/).
- **llm_client.py**: `call_detailed()` (additive) — возвращает `(text, provider_record)` с перечнем испробованных провайдеров и сработавшим; `call()` стал тонкой обёрткой (поведение неизменно, 21 тест зелёный).
- **settings.yaml / settings.py**: секция `queue` (max_attempts=5, stuck_threshold_seconds=1800, process_timeout=180, batch_limit=0); `timeouts.fetch_meetings` 600→120 (LLM ушёл из пути Fetch).

### knowledge-engine 1.12.0
- **queue.py** (NEW): `MeetingQueue` — claim/claim_next (атомарный `os.rename`, защита от гонки cron↔watchdog), complete/fail/requeue, reclaim_stuck (восстановление застрявших), status_counts. Повреждённый meta → карантин в `failed/`.
- **processor.py** (NEW): Process-воркер — `process_one`/`process_pending`; LLM через `call_detailed` (retry по fallback-цепочке, max_attempts=5), `validate_protocol` (frontmatter + обязательные поля + длина≥200) ДО записи в wiki; миграция write→jira→enrich→LOG из старого fetcher (non-fatal post-processing).
- **queue_watcher.py** (NEW): watchdog-демон на `pending/` (near-realtime). Слушает `on_created` И `on_moved` (т.к. `atomic_write` даёт событие move, не create).
- **fetcher.py**: `fetch_new_meetings` теперь только наполняет очередь (без LLM); дедуп `is_enqueued OR is_processed`; совместимый ответ (AC-09).
- **state.py**: секция `enqueued` (постоянный дедуп-маркер) + back-compat миграция.
- **cli.py**: команды `process-queue`, `queue-watch`, `queue-status`.
- **api.py**: `GET /api/v1/meeting-queue/status` (контракт наблюдаемости для BL-144), `POST /api/v1/process-queue`.

### pm-bot 1.15.0
- **transcript_watcher.py**: переведён на очередь — кладёт `.txt` в `pending/` (source=local) через `shared.meeting_queue.enqueue`, без локального LLM; убрана избыточная копия в `raw/inbound/meeting-notes`.
- **handlers.py**: `handle_fetch_meetings` — текст «поставлено в очередь»; фикс KeyError на устаревших ключах `details` (`file`/`type` → `subject`/`source` после рефактора).

### инфраструктура 1.1.0
- **docker-compose.yml**: KE-контейнер получает процесс `queue-watch` (watchdog); ke-cron — строка `process-queue` каждые 10 мин (страховка/reclaim).

### Документация
- **ADR-005** (NEW): file-based meeting queue. requirements/design/tasks в `docs/meeting-processing-queue/`.

### Заметки
- Полный test suite: 0 новых падений (9 pre-existing — чужие модули). ≈121 новый тест зелёный.
- **e2e пройден на живом Docker (30.06.2026)**: юнит прошёл pending → polling watchdog → LLM(ollama) → валидация → `wiki/meetings/...` → done.
- E2E + реализация поймали 4 интеграционных бага (исправлены): watchdog `on_created`→ нужен `on_moved` (atomic_write даёт move); KeyError в Telegram-хендлере на устаревших ключах `details`; нативный `Observer` не получает inotify на bind-mount Windows→Linux → `PollingObserver(timeout=5)`; `validate_protocol` требовал несуществующее frontmatter-поле `title` → `REQUIRED_FM=('type','date')` + проверка H1 (иначе каждый протокол падал бы в `failed/`).
- Подтверждено работающим в проде: cron-страховка `process-queue`, AC-05 (failed/ + сохранение `.txt`), AC-04 (`provider_history`: openrouter 429 → fallback ollama).
- Известное (не блокер): `enrich()` на протоколе кидает `'NoneType' object is not iterable` (non-fatal, протокол создаётся) — кандидат на отдельный багфикс.

---

## 30.06.2026 — Process Catalog + Playground UX

### web-ui 1.25.0
- **processes.html** (NEW): каталог 25 системных процессов (бизнес + технические) с карточками-ссылками
- **process.html** (NEW): детальная презентация процесса — hero, описание, триггер, визуальный поток, компоненты, навигация ◄►
- **about.html**: ссылка «Каталог процессов» в меню About
- **style.css**: общие стили `.toggle-btn`, `.field-select` вынесены из settings.html для переиспользования (playground fix)
- **playground.html**: кнопки провайдеров и select моделей теперь стилизованы под активную тему

### shared
- **openrouter_client.py**: добавлена модель `openrouter/owl-alpha` в AVAILABLE_MODELS

---

## 30.06.2026 — Dashboard Health + Email Fetch + UX fixes (BL-136, BL-148)

### pm-bot 1.14.0
- **vault_api.py**: `POST /api/v1/fetch-meetings` — proxy endpoint к KE для ручного запуска обработки email-транскрибаций (BL-148)
- **api.js**: `api.fetchMeetings()` с Content-Type header (BL-148)

### web-ui 1.24.0
- **dashboard.html**: карточка Vault Health рядом с Jira Sync в формате domain-card, спиннер загрузки, попап breakdown с иконками и Pipeline Metrics (BL-136)
- **settings.html**: секция EMAIL_FETCH с кнопкой FETCH NOW + индикатор статуса (BL-148)
- **components.js**: fix — кнопка EDIT BODY невидима в Matrix теме → добавлен `cmd-btn-cyan`
- **dashboard.html**: fix — попап health чёрный в Light теме → `var(--card)` вместо хардкода rgba
- **style.css, style-matrix.css, style-light.css**: все шрифты (Material Symbols, Share Tech Mono, JetBrains Mono, Inter) загружаются локально из `vendor/fonts/` вместо Google Fonts CDN
- **vendor/fonts/**: 9 файлов шрифтов для локальной загрузки

---

## 29.06.2026 — Vault Health: исправление broken links + YAML injection fix

### knowledge-engine 1.11.1
- **linter.py**: 3 бага wikilink-resolve: pipe order `[[target|display]]` вместо инвертированного, индексация `.txt` файлов в raw/, нормализация escaped pipe `\|` в markdown-таблицах. Broken links: 54 → 0
- **linter.py**: расширен фильтр допустимых расширений `.md` + `.txt` для raw source links
- **fetcher.py**: `_inject_source_file()` — квотирование `raw_rel_path` при наличии YAML-спецсимволов (`:`, `#`, `[`, `]`). Корневая причина: пути с двоеточиями (`09:32`, `R6 :: Daily`) ломали YAML frontmatter → enrich() падал → email блокировался после 3 попыток
- **Тесты**: обновлены под правильный pipe order в wikilinks

### pm-bot 1.13.1
- **settings.yaml**: timeout `fetch_meetings` увеличен 180s → 600s для обработки нескольких протоколов

### Vault data
- Импортированы 24 Jira-тикета (GO-*, PLATFORM-*, TMPL-*) через API для устранения broken links из daily-logs
- Исправлены 34 битых wikilinks в 10 vault-файлах (удалены ссылки на несуществующие отчёты, исправлены имена идей, обновлены пути доменов)
- Сброшен state 2 failed-протоколов (22.06 и 29.06) в `.meeting-fetcher-state.json`
- Vault health score: 0 → 11

---

## 29.06.2026 — Decision Journal (BL-24)

### pm-bot 1.13.0
- **vault_api.py**: `GET /api/v1/decisions` — агрегация решений из wiki/meetings/*.md с фильтрацией по домену, тексту, дате. On-the-fly парсинг секции `## Решения`, TTL-кэш 30с (BL-24, T-01)
- **vault_api.py**: `GET /api/v1/meetings/{filename}` — просмотр одного протокола по имени файла, валидация безопасности (BL-24)
- **vault_api.py**: 6 вспомогательных функций: `_parse_decision_bullets`, `_is_empty_decisions`, `_detect_domain_for_decision`, `_load_domain_display_map`, `_normalize_participants`, `_decision_matches_query`

### web-ui 1.23.0
- **decisions.html**: страница Decision Journal — карточки решений, метрики (TOTAL/DOMAINS/THIS_WEEK), поиск с подсветкой, фильтры домен/дата, expand с контекстом/action items/блокерами, кнопка OPEN PROTOCOL (BL-24, T-04)
- **meeting.html**: страница просмотра протокола встречи — markdown render через marked.js, кнопка НАЗАД (BL-24)
- **api.js**: методы `api.decisions(params)` и `api.meetingByFilename(filename)` (BL-24, T-02)
- **components.js**: пункт DECISIONS в sidebar (icon: gavel) (BL-24, T-03)
- **overview.html**: виджет RECENT DECISIONS — 5 последних решений, badge домена, ссылка ALL → (BL-24, T-05)

---

## 18.06.2026 — Багфиксы BL-133, BL-134

### knowledge-engine 1.10.1
- **jira_key_sync.py**: `patch_jira_links()` — замена exact match (`==`) на startswith + word boundary. Теперь патчит Jira-ключи с комментариями: `- GO-153 (описание)` → `- [[.../GO-153|GO-153]] (описание)` (BUG-016)
- **fetcher.py**: `_inject_source_file()` — fallback при отсутствии footer паттерна: append `---` + wikilink в конец протокола (BUG-017)
- **Тесты**: `test_no_footer_no_wikilink` → `test_no_footer_appends_wikilink` — обновлён под новое поведение

---

## 17.06.2026 — Meeting Protocol Enrichment (BL-133, BL-134) + OpenRouter (BL-138)

### knowledge-engine 1.10.0
- **fetcher.py**: `_inject_source_file()` — инжекция `source_file:` в frontmatter + wikilink `[[raw/...|исходный файл]]` в footer протокола (BL-133)
- **fetcher.py**: Jira sync теперь работает для ВСЕХ типов протоколов (sync, review, planning, other), не только daily (BL-134)
- **jira_key_sync.py**: переименование `sync_daily_jira_keys` → `sync_jira_keys`, `patch_daily_links` → `patch_jira_links` + backward-compatible alias (BL-134)
- **claude_client.py**: операции meeting/meeting_protocol используют `call_transcription()` вместо `call_with_fallback()` (BL-138)
- **Тесты**: 25 unit-тестов (test_meeting_enrich.py: inject source file, jira key aliases, module API)

### shared 0.2.0
- **openrouter_client.py**: HTTP-клиент для OpenRouter API (OpenAI Chat Completions формат). 6 моделей: Qwen3 32B/30B-A3B/235B-A22B, Gemini 2.5 Flash, DeepSeek V3, Llama 4 Maverick (BL-138)
- **llm_client.py**: `call_transcription()` — выбор провайдера для транскрибаций. Fallback chain: OpenRouter → Ollama → Claude API (BL-138)
- **Тесты**: 14 unit-тестов (test_openrouter.py: call, test_connection, models; test_llm_transcription.py: fallback chain)

### pm-bot 1.11.0
- **vault_api.py**: 3 новых endpoint'а — GET /openrouter-key-status, GET /openrouter-models, POST /test-openrouter (BL-138)
- **vault_api.py**: UserPrefs расширен полями `transcription_provider`, `openrouter_model` с валидацией (BL-138)
- **claude_client.py**: process_meeting() использует `call_transcription()` (BL-138)
- **api.js**: методы testOpenRouter(), openrouterKeyStatus(), openrouterModels() (BL-138)
- **Тесты**: 20 unit-тестов (test_openrouter_api.py: key status, models, test connection, user prefs)

### web-ui 1.20.0
- **settings.html**: секция TRANSCRIPTION PROVIDER — toggle DEFAULT/OPENROUTER, API key status indicator, model dropdown, TEST CONNECTION (BL-138)

### инфраструктура
- **docker-compose.yml**: OPENROUTER_API_KEY передаётся в pm-bot и knowledge-engine (BL-138)
- **.env.example**: OPENROUTER_API_KEY (optional) (BL-138)

---

## 17.06.2026 — Capture Terminal Redesign (BL-137)

### knowledge-engine 1.9.1
- **API**: GET /api/v1/jira-search — поиск тикетов по проекту с фильтрами (type, status, max_results)
- **_map_jira_issue()**: маппинг Jira issue → компактный JSON (key, summary, type, status, assignee, labels, priority, url)
- **client.search()**: параметр `limit` для ограничения общего количества результатов (не только размер страницы)
- **Фиксы**: JQL quoting для зарезервированных слов (GO, OR и т.д.), rstrip('/') в Jira URL
- **Тесты**: 7 тестов для limit-пагинации, 7 тестов для jira-search endpoint

### pm-bot 1.10.1
- **ke_client**: jira_search() — HTTP-клиент к KE jira-search API
- **vault_api**: GET /api/v1/jira/search — proxy endpoint с валидацией project key

### web-ui 1.19.0
- **capture-terminal** (components.js): новый Vue 3 компонент с двумя режимами:
  - **Simple**: классический chat-style терминал (message bubbles) — без изменений
  - **Extended**: card-based UI с type chips (Идея/Задача/Встреча), live preview, Jira Import
- **Jira Import**: выбор проекта (dropdown с recent), фильтры по типу/статусу, мультиселект тикетов, batch import
- **Settings**: toggle SIMPLE / EXTENDED (localStorage + server prefs)
- **Toast уведомления**: ct-toast success/error с именем файла и автоисчезновением
- **CSS**: ~670 строк ct-* стилей (style.css), light-theme overrides (style-light.css)
- **Tabler Icons CDN**: подключён на board.html, ideas.html, overview.html
- **Интеграция**: board.html (drawer), ideas.html (drawer), overview.html (inline) — замена inline HTML на компонент
- **Багфикс**: editable-field domain dropdown — d.slug → d.name, placeholder option, guard против undefined value
- **Тесты**: 212 новых тестов для capture-terminal

---

## 15.06.2026 — Decay State Dashboard (BL-132)

### knowledge-engine 1.9.0
- **snapshot_vault()**: read-only снимок всех артефактов с decay-данными (tier, relevance, days_since_access, access_count, domain, type)
- **API**: GET /api/v1/decay/snapshot — полный JSON snapshot (922 артефакта, <3с)
- **Тесты**: 6 unit-тестов для snapshot_vault (empty, basic, core, no-frontmatter, thresholds, domain extraction)

### pm-bot 1.10.0
- **ke_client**: decay_snapshot() — HTTP-клиент к KE API
- **vault_api**: GET /api/v1/decay/snapshot — proxy endpoint

### web-ui 1.16.0
- **decay.html** + **decay.js**: интерактивный дашборд состояния базы знаний (Chart.js 4.x CDN)
  - Metrics strip: 4 KPI (всего, active+warm, cold+archive, vault health %)
  - Decay landscape: bubble scatter (X=дней с обращения, Y=обращений, размер=relevance, цвет=tier)
  - Tier distribution: donut с центральным счётчиком + легенда
  - Проекция без активности: слайдер 0..30 дней, клиентский пересчёт тиров с дельтами
  - Здоровье по доменам: stacked horizontal bars (active/warm/cold/archive)
  - Forgotten gems: top-5 карточек cold/archive по access_count
- **Sidebar**: ссылка DECAY (иконка psychology) между TIMELINE и SETTINGS
- **CSS**: tier-переменные (--tier-active..--tier-core) + decay-стили в обеих темах
- **api.js**: метод api.decaySnapshot()

---

## 14.06.2026 — Decay Engine (BL-110, BL-111, BL-112, BL-113)

### knowledge-engine 1.9.0
- **Decay Engine** (Эббингауз): непрерывная шкала актуальности `relevance: 0.0-1.0`
  - Формула: `strength = 1 + ln(access_count)`, `relevance = max(floor, 1.0 - (rate/strength) × days)`
  - Domain-specific rates из `decay.yaml` (idea ~50д, prd ~42д, daily ~25д)
- **Tier system**: 5 tier'ов (core → active → warm → cold → archive), пороги 7/21/60 дней
- **Touch**: инкремент access_count + refresh last_accessed + promote tier при обращении
  - Интеграция в enricher.py — автоматический touch при enrichment
- **Creative recall**: `get_creative()` — случайная выборка из cold/archive tier
- **CLI**: `decay-recalc`, `decay-init`, `creative`
- **API**: POST /decay/recalc, POST /decay/touch, POST /decay/set-tier, GET /creative
- **Health scorer**: метрика `decay_stale` (файлы с relevance < 0.3)
- **Cron**: decay-recalc ежедневно в 05:00
- **decay-init миграция**: 922 файла, 99 пропущено

### pm-bot 1.10.0
- **ke_client**: touch(), set_tier(), get_creative()
- **vault_api**: прокси-эндпоинты decay/touch, decay/set-tier, ideas/creative
- **Telegram**: /creative — случайные забытые идеи
- **Web UI**:
  - overview.html — панель "Забытые идеи" (creative recall)
  - ideas.html — фильтр по tier (табы Все/Active/Warm/Cold/Archive/Core + AND-логика с domain)
  - ideas.html + board.html — кнопка "Закрепить" (pin/unpin → set-tier core/active)
  - style-matrix.css + style-light.css — стили для tier tabs, creative panel, pin button

---

## 14.06.2026 — CI green: mypy + ruff (29 файлов)

### BL-131: Зелёный CI — устранение всех ошибок типизации и линта
- **mypy**: 253 ошибки в 16 файлах устранены
  - `knowledge-engine`: type narrowing для YAML/JSON данных (dict union → dict[str, Any]), Optional params, fcntl type:ignore
  - `pm-bot`: assert-narrowing для nullable Update properties (182 ошибки в handlers.py), Any type fix, variable scope fix
  - `idea-pipeline`: orchestrator null guards (pipeline_run → None check), TextBlock isinstance check, frontmatter.Post handler arg
- **ruff**: 26 lint-ошибок устранены (unused imports, undefined names, complex imports)
- **Тесты**: check_unsorted_misc обновлены под wikilink-логику (BL-118), все 30+ тестов pass
- **GitHub Actions CI**: lint + typecheck + test matrix зелёные
- **Pre-commit hook**: ruff --fix срабатывает автоматически
- Затронуты компоненты: pm-bot, knowledge-engine, idea-pipeline, shared (29 файлов изменено)

---

## 14.06.2026 — pm-bot 1.9.0, knowledge-engine 1.8.0, idea-pipeline 1.1.2

### BL-126 + BL-130: Дедупликация + декаплинг (closed)
- **shared/** модуль (6 файлов, 1283 строки): `llm_client.py`, `file_writer.py`, `vault_paths.py`, `domain_config.py`, `frontmatter_utils.py`, `settings.py`
- `settings.yaml` — централизованная конфигурация runtime-параметров (timeouts, cooldowns, cache_ttl, rate_limits, paths, ports)
- `shared/settings.py` — загрузка YAML с deep merge, dot-notation доступ, singleton, 14 unit-тестов
- **KE HTTP API** (`knowledge-engine/app/api.py`, 618 строк) — 18 эндпоинтов (FastAPI), CLI `serve` команда
- `docker-compose.yml`: KE запускает `serve` + `watch` параллельно
- **Декаплинг pm-bot**: `ke_client.py` (233 строки, 18 HTTP-функций) заменяет 21 subprocess.run вызов
- pm-bot Dockerfile: удалены COPY knowledge-engine, pip install KE requirements, PYTHONPATH для KE
- `KE_API_URL=http://knowledge-engine:8001` в environment pm-bot
- **Rate limiter**: `rate_limiter.py` (TelegramRateLimiter, token bucket, params из settings)
- Интегрирован в `enrichment_reminder.py`, `scheduler.py`, `daily_alert.py`, `transcript_watcher.py`
- **SQLite volume**: `pm-bot-data:/data`, DB_PATH из settings, `mkdir` в `init_db()`
- Импорты переключены: 9 файлов pm-bot (22 замены), 15 файлов KE (53 замены), 3 файла idea-pipeline (4 замены)
- Удалено 10 дубликатов: 4 из pm-bot, 5 из KE, 1 из idea-pipeline (-2298 строк)
- Баланс: +1283 shared, +618 api.py, +233 ke_client, +114 settings.py, +80 rate_limiter, -2298 дубликатов = нетто ~+30 строк

---

## 13.06.2026 — pm-bot 1.8.1, knowledge-engine 1.7.1, idea-pipeline 1.1.1

### BL-124: Ревизия домена general (closed)
- `domain_mover.py` — модуль переноса файлов между доменами (432 строки, 6 функций)
- CLI: `move-artifact`, `batch-reclassify`, `audit-domain` — 3 команды в cli.py
- 14 unit-тестов (477 строк), все проходят
- Batch execution выполнен: 156 файлов → 1 перенесён (AN-13348.md → search-engine/bugs), 7 дубликатов удалены из general, 148 unmatched (корректно в general)
- Удалённые дубликаты: GO-263, GO-273, VUECLIENT-3350, VUECLIENT-3427 (search-engine), GO-315, GO-58, PLATFORM-10475 (suggester)
- Итог general: 148 файлов (tasks 113, bugs 27, ideas 3, knowledge 2, epics 1, userstories 2)

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

### BL-125: Координация писателей в vault
- `file_lock()` context manager на основе `fcntl.flock()` (LOCK_EX + timeout loop)
- Windows fallback (no-op с warning для локальной разработки)
- `locked_append()` — append строки под file lock для LOG.md/log.md
- `append_section()` обёрнута в `file_lock()` (pm-bot + knowledge-engine)
- `obsidian_writer.py`: 3 fix points — `_update_artifact_index`, `_append_artifact_log` (create + append), `_append_wiki_root_log`
- `ingest.py`: `_append_root_log()` → `locked_append()` (вместо read-then-rewrite)
- `domain_manager.py`: `update_domain_index()` под `file_lock`, `append_domain_log()` → `locked_append()`
- `idea-pipeline/state.py`: `save_state_file()` → `atomic_write()` (защита от partial write)
- `idea-pipeline/vault_writer.py`: `save_state()` → `atomic_write()` (уже имел inline версию)
- `.gitignore`: `*.lock` для исключения lock-файлов
- 17 unit-тестов (14 pass + 3 skip на Windows: timeout, concurrent append, concurrent section)

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
