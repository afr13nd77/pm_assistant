# PM Assistant — Changelog

Журнал изменений по всем компонентам монорепо.
Компоненты: **pm-bot**, **knowledge-engine**, **idea-pipeline**, **web-ui**.

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
