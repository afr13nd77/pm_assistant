# PM Assistant

## Что это

PM Assistant — программная реализация методологии управления продуктовыми знаниями для продакт-менеджера OTA-компании.

Проект автоматизирует полный цикл жизни идеи: от сырой мысли в Telegram до готового эпика в Jira. Это не просто бот — это работающая система из 4 микросервисов, которая реализует правила, описанные в конфигурации Knowledge Base Agent (CLAUDE.md хранилища знаний проекта).

Основа системы — **файловое хранилище знаний** (Markdown-файлы), управляемое через **Obsidian**. Vault подключен к **Яндекс.Диск** и автоматически синхронизируется с облаком, обеспечивая бэкап, доступность с разных устройств и совместную работу.

Серверная часть — 4 микросервиса (**pm-bot**, **knowledge-engine**, **idea-pipeline**, **ke-cron**), развернутые в **Docker-контейнере** на локальном сервере.

Для обработки естественного языка используется **гибридная LLM-архитектура**: локальный **Ollama** (модель QWEN 3.5) для рутинных задач с автоматическим fallback на **Claude API** для сложных операций (синтез, pipeline, enrichment). Для транскрибаций доступен **OpenRouter** (QWEN3-32B и другие модели) с fallback chain OpenRouter → Ollama → Claude API. Голосовые сообщения транскрибируются локально через **faster-whisper** (модель small, CPU).

Регулярные аналитические задачи (утренний дайджест, ежедневный статус разработки, еженедельный отчёт, анализ рынка и конкурентов) выполняются через **Claude Desktop Cowork** — scheduled tasks, настроенные на работу с vault Obsidian. Ночная обработка очереди raw-файлов — через headless Claude Code.

---

## Архитектура хранилища: модель Карпати

Хранилище спроектировано по модели Андрея Карпати (Andrej Karpathy): **raw -> compile -> wiki**.

### Три слоя

1. **raw/** — неизменяемые оригиналы (append-only). Все, что захвачено (идея из Telegram, транскрипт встречи, тикет из Jira, клиппинг из веба), сохраняется здесь as-is. Файлы никогда не редактируются. Можно перекомпилировать wiki из сырья в любой момент.

   Подпапки: `inbound/ideas/`, `inbound/meeting-notes/`, `inbound/daily-logs/`, `inbound/tasks/`, `inbound/clippings/`, `inbound/misc/`, `competitors/`, `metrics/`.

2. **wiki/** — скомпилированное знание. Живая энциклопедия, организованная по продуктовым доменам. Структурированные заметки с YAML frontmatter, перекрестными ссылками, индексами.

   Верхний уровень: `wiki/domains/`, `wiki/meetings/`, `wiki/daily-logs/`, `wiki/reports/`, `wiki/concepts/`, `wiki/teams/`, `wiki/projects/`, `wiki/INDEX.md`, `wiki/LOG.md`.

3. **templates/** — шаблоны артефактов (idea, epic, userstory, task, bug, ADR), редактируемые без кода и видимые в Obsidian.

### Философия: vault-as-database

Obsidian vault с Markdown-файлами заменяет классическую БД:

- Frontmatter = метаданные (id, status, domain, tags, created, jira_key и т.д.)
- Тело файла = контент
- Файловая система = индекс
- Вся история доступна через git
- Файлы одновременно читаемы человеком (в Obsidian) и машиной (через API)

### Доменная группировка

Каждый домен — автономная единица со своей структурой:

```
wiki/domains/{domain}/
├── ideas/       # идеи с 9 полями и readiness %
├── epics/       # эпики с горизонтами и прогрессом
├── tasks/       # задачи (Jira и внутренние)
├── bugs/        # баги
├── knowledge/   # knowledge-файлы (клиппинги, справочники)
├── index.md     # автогенерируемое оглавление
├── log.md       # журнал изменений
├── decisions.md # архитектурные решения (ADR)
└── glossary.md  # терминология домена
```

Текущие домены: `static-metadata`, `suggester`, `search-engine`, `partner-search-engine`, `general` (кросс-доменные задачи).

### Ingest: raw -> wiki

Процесс обработки файлов из raw/ и их преобразования в структурированные заметки в wiki/. Для каждого типа входящего файла — свой алгоритм:

- `raw/inbound/ideas/` — определить домен — `wiki/domains/{domain}/ideas/{slug}.md`
- `raw/inbound/meeting-notes/` — извлечь action items — задачи, решения — decisions.md
- `raw/inbound/misc/` — классифицировать — concepts/ или teams/ или projects/ или domains/
- `raw/inbound/clippings/` — определить домен — `wiki/domains/{domain}/knowledge/{slug}.md`
- `raw/competitors/` — только запись в LOG.md, отчет по команде

Определение домена — автоматическое по ключевым словам (domain_detection rules в CLAUDE.md). При конфликте — запрос к пользователю. При отсутствии совпадений — домен по умолчанию + warning в LOG.md.

---

## Архитектура системы

Система состоит из 4 слоёв, каждый из которых решает свою задачу.

### 1. Хранилище знаний

Фундамент всей системы — **Obsidian vault** с Markdown-файлами, организованными по модели Карпати (raw -> compile -> wiki). Vault является единственным источником правды: все артефакты (идеи, задачи, эпики, протоколы встреч, отчёты) хранятся как структурированные Markdown-файлы с YAML frontmatter.

Vault подключен к **Яндекс.Диск** и автоматически синхронизируется с облаком. Это обеспечивает:
- Резервное копирование всех данных
- Доступ к хранилищу с любого устройства (рабочий компьютер, ноутбук, телефон)
- Возможность ручного редактирования заметок через Obsidian на любом устройстве с автоматической синхронизацией изменений

### 2. Серверная часть (Docker)

4 микросервиса, развёрнутые в Docker-контейнере на локальном сервере:

- **pm-bot** — Telegram-бот, Vault API (FastAPI) и Web UI сервер. Точка входа для всех взаимодействий пользователя с системой
- **knowledge-engine** — сервис обогащения и синтеза знаний, watchdog на входящие файлы, Jira-интеграция, линтер, индексатор
- **idea-pipeline** — оркестратор проработки идей через цепочку AI-агентов (Analyst -> PM -> Decomposer)
- **ke-cron** — cron-контейнер для периодических задач (синтез, Jira sync, rebuild index, lint, vault health, cowork-context)

Все сервисы работают с одним и тем же Obsidian vault, смонтированным как Docker volume.

### 3. LLM-слой

Гибридная архитектура с двумя провайдерами:

| Провайдер | Модель | Назначение | Когда используется |
|---|---|---|---|
| **Ollama** (локальный) | QWEN 3.5 | Рутинные задачи: классификация, извлечение ключевых слов, простая структуризация | По умолчанию для задач, не требующих глубокого анализа |
| **Claude API** (облачный) | claude-sonnet-4-6 | Сложные задачи: синтез, enrichment, pipeline (анализ + PRD + декомпозиция), еженедельные отчёты | Для задач, требующих глубокого понимания контекста |
| **OpenRouter** (облачный) | QWEN3-32B (и 5 других) | Транскрибации: обработка протоколов встреч | Настраивается в Settings как Transcription Provider |

Стратегия выбора:
- В режиме **Hybrid** (по умолчанию) — система автоматически выбирает провайдера в зависимости от типа задачи. Если Ollama недоступен или возвращает некачественный результат — автоматический fallback на Claude API
- В режиме **Claude** — все запросы через Claude API
- В режиме **Ollama** — все запросы через локальный Ollama
- В настройках **Transcription Provider** — можно выбрать OpenRouter для обработки транскрибаций встреч (fallback: Ollama → Claude API)

Переключение режима — через Web UI (Settings) или переменные окружения.

### 3.1. Speech-to-Text

Голосовые сообщения из Telegram транскрибируются локально через **faster-whisper** (модель `small`, CPU, int8). Автодетекция языка, lazy-загрузка модели при первом голосовом сообщении. Управление: переменная `STT_ENABLED` (по умолчанию включен).

### 4. Регулярные задачи (Claude Desktop Cowork)

Аналитические и отчётные задачи выполняются по расписанию через **Claude Desktop Cowork** — scheduled tasks, в которых Claude Desktop настроен на работу с vault Obsidian как с рабочим контекстом.

| Задача | Расписание | Исполнитель |
|---|---|---|
| Утренний дайджест (morning-digest) | Пн-Пт 08:31 МСК | Cowork scheduled task |
| Ежедневный статус разработки (daily-dev-status-report) | Ежедневно 18:00 МСК | Cowork scheduled task |
| Еженедельный отчёт (weekly-pm-report) | Пятница | Cowork scheduled task |
| Анализ рынка и конкурентов (competitor-analysis) | Раз в 2 недели | Cowork scheduled task |
| Ночная обработка очереди raw (vault-ingest-queue) | Ежедневно 02:00 МСК | Headless Claude Code (Windows Task Scheduler) |

Cowork задачи работают непосредственно с файлами vault через Obsidian, формируя отчёты и дайджесты на основе актуального состояния хранилища. Headless Claude Code используется для ночной батчевой обработки, где важен контроль модели (зафиксирована `claude-sonnet-4-6` через флаг `--model`).

---

## Жизненный цикл идеи

Идея проходит 4 статуса: **Новая -> Проверка гипотезы -> Готова к производству -> Отсев**.

### 9 обязательных полей

**Блок 1: Паспорт идеи** (заполнение = 44% готовности, переход в «Проверку гипотезы»):

1. Проблема / Боль — чью и какую боль решаем
2. Решение — что именно предлагаем
3. Ценность (USP) — чем отличается от текущего
4. Метрика — что изменится в цифрах. Нет метрики = Отсев.

**Блок 2: Посадочный талон** (заполнение = 100% готовности, переход в «Готова к производству»):

5. Сегмент (Кто) — конкретная группа пользователей
6. Job Story — «Когда [ситуация], я хочу [мотивация], чтобы [результат]»
7. In scope — функционал первой версии
8. Out of scope — что сознательно не делаем
9. Ограничения — технические, бизнесовые, регуляторные

### Readiness %

`Готовность = (заполненные поля / 9) * 100%`

- 0-43% — статус «Новая»
- 44-99% — статус «Проверка гипотезы»
- 100% + артефакт валидации — статус «Готова к производству»

### Обратная петля

При создании эпика в frontmatter идеи добавляется `epic_ref: EPIC-XXX`. При закрытии эпика в конец идеи дописывается раздел «Результат» (метрика выросла / не выросла / нет данных). Так идея становится полным кейсом: гипотеза -> что сделали -> что получили.

---

## Три класса задач

В базе знаний сосуществуют три класса задач:

| | Jira-задача | Внутренняя задача | Личный TODO |
|---|---|---|---|
| Маркер | `jira_key: GO-114` | `task_id: TASK-01` | `TODO-NNN` |
| Источник | jira-sync (автоматически) | пайплайн декомпозиции идеи | ручное создание |
| Файл | один файл на задачу | один файл на задачу | один `todo.md` |
| Статусы | 25+ значений из Jira as-is | todo / in-progress / done / cancelled | todo / in-progress / done / cancelled |

Jira-статусы не нормализуются — Jira является источником правды. Внутренние таски имеют зависимости (`depends_on`): задача не может перейти в `in-progress`, пока зависимости не в `done`.

---

## Компоненты

### pm-bot (v1.17.0)

Telegram-бот + Vault API + Web UI сервер. Точка входа для всех взаимодействий.

Функции:

- Telegram-хендлеры: /idea, /jira, /daily, /synthesize, /jira_sync, /jira_import, /jira_create, /pipeline, /domain, /lint, /status, /test_enrichment, /fetch_meetings, текст, голос
- Claude API / Ollama / Hybrid — гибридная LLM-архитектура с fallback (Ollama: Qwen 3.5)
- OpenRouter API для транскрибаций (6 моделей, fallback chain)
- Speech-to-Text (faster-whisper)
- transcript_watcher: локальные `.txt` кладёт в файловую очередь `raw/meeting-queue/pending/` (без локального LLM; обработку выполняет KE-воркер) — BL-145
- Vault API (FastAPI, порт 8000) с in-memory TTL cache (30s)
- Web UI static server (порт 8080)
- APScheduler: weekly report (Mon 09:00), enrichment reminders (daily)
- SQLite: дедупликация enrichment-напоминаний (cooldown 24ч)

### knowledge-engine (v1.15.0)

Сервис обогащения и синтеза знаний.

Функции:

- Enrichment: обогащение идей связями из vault
- Synthesis: кластеризация идей + сводка
- Jira sync (cron каждые 3ч): fetch JQL -> diff state -> write wiki/ + raw/ -> notify
- Jira import: импорт единичного тикета по ключу
- Jira create: создание тикетов из vault
- **Meeting Processing Queue (BL-145)**: трёхфазная обработка протоколов через файловую очередь `raw/meeting-queue/{pending,processing,done,failed}/`:
  - *Fetch* (`fetcher.py`): IMAP fetch -> кладёт сырые транскрипты в `pending/` (без LLM, быстро); дедуп `is_enqueued OR is_processed`
  - *Process* (`processor.py`): воркер берёт юнит по одному -> LLM через fallback chain (`call_detailed`, max_attempts=5) -> `validate_protocol` (frontmatter type/date + H1 + длина) -> classify -> запись в `wiki/meetings/` -> jira sync -> enrich -> `done/`; при сбое retry другим провайдером или `failed/`
  - *Queue* (`queue.py`): атомарные переходы (claim через `os.rename`), `reclaim_stuck`, `status_counts`
  - watchdog-демон `queue_watcher.py` (PollingObserver, near-realtime) + cron `process-queue` /10мин (страховка)
- Meeting protocol enrichment: source_file в frontmatter + wikilink на raw-файл в footer (BL-133)
- Jira key sync для всех типов протоколов (BL-134)
- Vault index: сканирование, in-memory индекс, keyword + tag matching
- Linter: проверка frontmatter, структуры, битых ссылок, валидация статусов идей
- Status migrator: миграция legacy-статусов в канонический словарь (4 статуса)
- Pipeline metrics: ingest ratio, avg lag raw→wiki, raw counts по типам
- Domain manager: scaffold, index, activity log
- Watchdog: auto-enrichment при появлении файлов в raw/inbound/

### idea-pipeline (v1.1.2)

Оркестратор проработки идей через цепочку AI-агентов.

Цепочка: **Analyst -> PM -> Decomposer**

- Analyst: идея + vault context -> анализ
- PM: анализ -> PRD
- Decomposer: PRD -> Epic + Tasks (JSON)

Результат записывается в vault: `Pipeline/<date>-<slug>/` (analysis.md, PRD.md, epic.md, tasks/*.md).

Configurable models per agent через pipeline.yaml. API key аутентификация.

### ke-cron

Cron-контейнер для периодических задач:

- Синтез: ежедневно 09:00
- Meeting fetch (наполнение очереди): каждый час :15
- Process queue (страховка/reclaim): каждые 10 минут (BL-145)
- Jira sync: каждые 3 часа
- Rebuild index: ежедневно 02:00
- Lint: ежедневно 03:00
- Vault health: ежедневно 04:00

### shared (v0.7.0)

Общий модуль, единый источник для pm-bot, knowledge-engine и idea-pipeline.

- llm_client: фабрика LLM-клиентов, маршрутизация по операциям, call (fallback chain), call_detailed (отдаёт provider_record — BL-145), мультимодельные fallback-цепочки с нормализацией шага (BL-155), backoff 429 между openrouter-шагами, call_transcription
- meeting_queue: enqueue-ядро файловой очереди (Unit, make_unit_id, build_meta, enqueue, path-хелперы) — общее для KE-fetcher и pm-bot-watcher (BL-145)
- openrouter_client: HTTP-клиент для OpenRouter API, list_models с live-запросом и TTL-кэшем (BL-156)
- file_writer: file_lock, atomic_write, locked_append
- vault_paths: 25 функций для путей vault
- domain_config: загрузка/сохранение domain-config.yaml
- frontmatter_utils: чтение/запись YAML frontmatter
- settings: загрузка settings.yaml, dot-notation (секция queue — BL-145)

---

## Web UI (v1.25.0)

SPA-дашборд на Vue 3 + vanilla JS. Статические HTML-страницы, данные через Vault API.

| Страница | Назначение |
|---|---|
| overview.html | Command center: system status, idea funnel, KPI-метрики, donut chart, today's queue, activity feed, quick capture |
| ideas.html | Канбан идей: 4 колонки по статусам (Новая / Проверка гипотезы / Готова / Отсев), фильтр по доменам, drag-n-drop, readiness %, capture drawer |
| board.html | Канбан-доска задач: классификация по jira_key, типы из frontmatter (BACKEND, FRONTEND, TESTING, RESEARCH, DESIGN) |
| dashboard.html | Домены, статистика артефактов, Jira sync status (overdue alert >3ч) |
| roadmap.html | Roadmap: эпики с прогрессом, колонки Backlog/Todo/In Progress/Done |
| timeline.html | Таймлайн фич |
| report.html | Просмотр еженедельных отчетов (Markdown -> HTML через marked.js) |
| settings.html | Настройки: тема, refresh mode, LLM Provider (Claude/Ollama/Hybrid), Transcription Provider (Default/OpenRouter), мультимодельные OpenRouter fallback-цепочки с inline model selector, prompts, Jira sync |
| decay.html | Decay state dashboard: bubble scatter, tier distribution, projection, domain bars, forgotten gems |
| about.html | О сервисе: версии компонентов, история изменений |

Dual-theme: MATRIX (dark, glow/neon) и LIGHT (cream, warm). Переключение в settings, хранение серверное.

Refresh mode: auto (board 30s, roadmap 60s) или manual.

Drag-n-drop правила: readiness 100% для перехода в «Готова», warning при < 44% для «Проверка гипотезы».

---

## Потоки данных

1. **Идеи**: Telegram/Web -> handlers -> claude_client.process_idea (->JSON) -> obsidian_writer.write_idea (template-based) -> `raw/inbound/ideas/` + `wiki/domains/<domain>/ideas/` -> knowledge-engine enrich
2. **Транскрипты встреч (локальные)**: .txt -> transcript_watcher -> `raw/meeting-queue/pending/` -> (Process-воркер) -> `wiki/meetings/` (BL-145)
3. **Meeting fetcher (email)**: IMAP email -> fetch -> `raw/meeting-queue/pending/` (Fetch, без LLM) -> watchdog/cron Process-воркер -> LLM -> validate -> `wiki/meetings/` -> done/ (BL-145)
4. **Jira-тикеты**: Telegram /jira -> process_jira_ticket -> `raw/inbound/tasks/` + `wiki/domains/<domain>/tasks/`
5. **Daily-заметки**: Telegram /daily -> process_daily -> `raw/inbound/daily-logs/` + `wiki/daily-logs/`
6. **Jira Sync** (cron 3ч или /jira_sync): fetch JQL -> diff state -> write `wiki/domains/<domain>/tasks/` + `raw/inbound/tasks/` -> notify
7. **Idea Pipeline**: Telegram /pipeline или API -> Analyst -> PM -> Decomposer -> `Pipeline/<date>-<slug>/`
8. **Enrichment Reminders** (daily cron): scan ideas -> filter by readiness < 100% -> SQLite cooldown -> Telegram notify
9. **Synthesis** (cron 09:00 или /synthesize): кластеризация + сводка -> `wiki/reports/synthesis-*.md`

---

## Стек

| Зависимость | Версия | Сервис |
|---|---|---|
| Python | 3.12 | все |
| python-telegram-bot | 21.5 | pm-bot |
| anthropic | >=0.40.0 | pm-bot, knowledge-engine, idea-pipeline |
| requests | >=2.31.0 | shared (openrouter_client) |
| FastAPI | >=0.111.0 | pm-bot, idea-pipeline |
| uvicorn | >=0.30.0 | pm-bot, idea-pipeline |
| watchdog | 4.0.1 / 6.0.0 | pm-bot, knowledge-engine |
| faster-whisper | >=1.0.0 | pm-bot |
| apscheduler | >=3.10.4 | pm-bot |
| python-frontmatter | >=1.1.0 | knowledge-engine, idea-pipeline |
| Vue.js | 3.x (CDN) | web-ui |
| marked.js | 15.x (CDN) | web-ui |
| Docker Compose | v3.9 | инфраструктура |
| Claude модель | claude-sonnet-4-6 | pm-bot, knowledge-engine, idea-pipeline |

---

## Docker-топология

4 контейнера:

| Контейнер | Роль | Порты |
|---|---|---|
| pm-bot | Telegram polling + Vault API + Web UI | 8000 (API), 8080 (Web) |
| knowledge-engine | HTTP API (:8001) + Watchdog на raw/inbound/ (auto-enrichment) + queue-watch на meeting-queue/pending/ (BL-145) | 8001 (API) |
| idea-pipeline | Оркестратор AI-агентов | 8100 |
| ke-cron | Синтез (09:00) + Cowork-context (01:00) + Meeting fetch (:15) + Process queue (/10мин) + Jira sync (каждые 3ч) | — |

---

## Запуск

### Docker (рекомендуется)

```bash
# Запуск
docker compose up --build

# Фоновый режим
docker compose up -d

# Логи
docker compose logs -f pm-bot

# Пересборка
docker compose down && docker compose build --no-cache && docker compose up -d
```

### Локальная разработка

```bash
cd pm-bot
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env  # заполнить переменные
python -m app.main
```

---

## Переменные окружения

| Переменная | Обязательная | Сервис | Описание |
|---|---|---|---|
| BOT_TOKEN | да | pm-bot | Токен Telegram-бота |
| CLAUDE_API_KEY | да | pm-bot, KE, pipeline | Ключ Claude API |
| VAULT_PATH | да | все | Путь к Obsidian vault |
| TRANSCRIPTS_INBOX | да | pm-bot | Папка входящих транскриптов |
| ALLOWED_CHAT_ID | да | pm-bot | Chat ID владельца (пустой = режим первого запуска) |
| PIPELINE_API_URL | да | pm-bot | URL idea-pipeline API |
| JIRA_URL | да | KE | URL Jira-сервера |
| JIRA_TOKEN | да | KE | Personal Access Token |
| OLLAMA_URL | нет | pm-bot, KE | URL Ollama-сервера |
| OLLAMA_MODEL | нет | pm-bot, KE | Модель Ollama (default: qwen3.5:latest) |
| OPENROUTER_API_KEY | нет | pm-bot, KE | Ключ OpenRouter API для транскрибаций |
| STT_ENABLED | нет | pm-bot | Включить STT/Whisper (default: 1) |

Полный список переменных — в index.md.

---

## Performance

In-memory TTL cache (30s) в vault_api.py:

| Endpoint | До оптимизации | После (cached) |
|---|---|---|
| /system/status | 4882 ms | 4 ms |
| /domains | 4891 ms | 7 ms |
| /tasks | 1364 ms | 34 ms |
| /overview/queue | 912 ms | 4 ms |

Теплый кеш при старте сервера — первый запрос пользователя уже из кеша. Invalidation при любой write-операции.

---

## Здоровье хранилища (Vault Health)

Система оценки качества и полноты хранилища знаний. Endpoint: `GET /api/v1/vault/health`.

### Формула

```
score = max(0, min(100, 100 - Σ(count × weight) - coverage_penalty))
```

Грейды:
- **healthy** (≥80) — хранилище в хорошем состоянии
- **warning** (50–79) — есть проблемы, требующие внимания
- **critical** (<50) — серьёзные проблемы со структурой или полнотой

### Метрики

| Метрика | Weight | Что измеряет | Логика |
|---|---|---|---|
| `broken_links` | 3 | Битые `[[wikilinks]]` в wiki/ | Сканирует body (не frontmatter) всех wiki/*.md. Резолвит ссылки 3 уровнями: exact name → suffix match → stem match. Игнорирует: @mentions, шаблоны `{{}}`, URL, вложения, имена людей (2-3 слова с заглавной). Резолвит относительные пути (`../`). Файловый индекс покрывает wiki/ и raw/ |
| `orphan_pages` | 5 | Необработанные raw-файлы | Проверяет `raw/inbound/daily-logs/` и `raw/inbound/meeting-notes/`. Извлекает дату (YYYY-MM-DD или YYYY.MM.DD) из имени raw-файла и ищет wiki-аналог: daily-logs → `wiki/daily-logs/`, meeting-notes → `wiki/meetings/` + `wiki/daily-logs/` (Daily стендапы трансформируются в daily-logs). Остальные типы покрыты другими метриками |
| `dead_ends` | 1 | Артефакты без исходящих связей | Файлы в `wiki/domains/*/ideas,tasks,epics,prds,bugs,userstories/` без единого `[[wikilink]]` в body. Исключает service-файлы (index.md, log.md) и файлы с `jira_key` |
| `stale_drafts` | 1 | Устаревшие черновики | Идеи со статусом «Новая», не обновлявшиеся >30 дней |
| `unsorted_misc` | 0.5 | Неиспользуемые misc-файлы | Файлы в `raw/inbound/misc/`, stem/name которых не упоминается ни в одном `[[wikilink]]` в wiki/. Файлы, на которые есть ссылка — не штрафуются |
| `ingest_backlog` | 0.2 | Очередь необработанного raw | Ideas: совпадение `id:` из frontmatter raw и wiki (fallback на stem). Tasks: совпадение stem |
| `description_coverage` | — | Полнота описаний | Доля артефактов с ≥2 предложениями в body. Penalty: <50% → 10, <70% → 5, ≥70% → 0 |

### Распределение проверок по типам raw/

| Тип raw/inbound/ | Метрика | Стратегия matching |
|---|---|---|
| `ideas/` | `ingest_backlog` | Совпадение `id:` из frontmatter (fallback: stem) с wiki/domains/*/ideas/ |
| `tasks/` | `ingest_backlog` | Совпадение stem с wiki/domains/*/tasks/ |
| `daily-logs/` | `orphan_pages` | Дата из имени файла → wiki/daily-logs/ |
| `meeting-notes/` | `orphan_pages` | Дата из имени файла → wiki/meetings/ + wiki/daily-logs/ |
| `misc/` | `unsorted_misc` | Stem/name в [[wikilinks]] wiki/ |
| `clippings/` | — | Справочный материал, трансформация не ожидается |

### Критерий «обработано» (Definition of Done для ingest)

Raw файл считается обработанным, если выполняется условие для его типа:

| Тип raw/inbound/ | Обработан, когда |
|---|---|
| `ideas/` | В `wiki/domains/*/ideas/` есть файл с тем же `id:` из frontmatter |
| `tasks/` | В `wiki/domains/*/tasks/` есть файл с тем же stem |
| `daily-logs/` | В `wiki/daily-logs/` есть файл с той же датой |
| `meeting-notes/` | В `wiki/meetings/` или `wiki/daily-logs/` есть файл с той же датой |
| `misc/` | Stem или имя файла упоминается в `[[wikilink]]` хотя бы одного wiki-файла |
| `clippings/` | Обработка не требуется (справочный материал) |

### Тренды

API возвращает `trend_7d` и `trend_30d` — история score за 7 и 30 дней. История хранится в `.health-history.json` в корне vault (TTL 90 дней).

### Метрики pipeline (BL-123)

Поверх health score (штрафного) — информационные метрики эффективности pipeline обработки. Не влияют на score.

| Метрика | Тип | Описание |
|---|---|---|
| `ingest_ratio` | float 0-100 | % обработанных raw файлов (processed / raw_total × 100) |
| `avg_lag_hours` | float \| null | Среднее время raw→wiki в часах (по matched парам mtime) |
| `raw_total` | int | Всего .md файлов в raw/inbound/ideas/ + raw/inbound/tasks/ |
| `raw_counts` | dict | Разбивка: `{"ideas": N, "tasks": M}` |
| `matched_pairs` | int | Количество raw-файлов, для которых найдена wiki-копия |

Отображаются в overview.html в секции Pipeline под категориями штрафов. Тренды (trend_7d, trend_30d) — текстовые ↑↓→.

---

## Статистика проекта

- 85 реализованных фичей
- 24 исправленных бага
- 27 идей в бэклоге
- 139 пунктов бэклога всего

Разработка ведется с 07.05.2026. Текущие версии: pm-bot 1.17.0, knowledge-engine 1.15.0, idea-pipeline 1.1.2, web-ui 1.25.0, shared 0.7.0.

---

## Связь с хранилищем знаний

PM Assistant — это программная реализация правил, описанных в CLAUDE.md хранилища `08 project hotels claude`. Хранилище знаний определяет:

- Структуру raw/ и wiki/
- Правила ingest (обработка сырых файлов)
- Domain detection (определение домена по ключевым словам)
- Правила индексации и линтинга
- Интеграцию с Jira

PM Assistant превращает эти правила в работающие сервисы: watchdog вместо ручного /ingest, cron вместо ручного /rebuild-index, API вместо ручного чтения index.md, Web UI вместо навигации по файловой системе.

## Форматы нейминга файлов в vault

### raw/ — исходники

| Тип | Формат | Пример |
|---|---|---|
| Идеи | `IDEA-{NNNN}-{YYYY-MM-DD}_{slug}.md` | `IDEA-0025-2026-06-10_монолит-2.5к.md` |
| Протоколы встреч | `{YYYY-MM-DD} {HHmm} (MSK) {название}.txt` | `2026-05-06 1237 (MSK) SearchOffersByTiles.txt` |
| Дейли-логи | `{YYYY-MM-DD} {HHmm} (MSK) {название}.txt` | `2026-05-04 0959 (MSK) R6 Daily.txt` |

### wiki/ — обработанные артефакты

| Тип | Формат | Пример |
|---|---|---|
| Дейли-саммари | `{YYYY.MM.DD}-{NNN}-Daily-summary.md` | `2026.06.09-142-Daily-summary.md` |
| Встречи | `{YYYY-MM-DD}-{HHmm}-{slug}.md` | `2026-05-06-1237-searchoffersbytiles-логика.md` |
| Идеи | `IDEA-{NNNN}-{YYYY-MM-DD}_{slug}.md` | `IDEA-0025-2026-06-10_монолит-2.5к.md` |
| Задачи (Jira) | `{JIRA-KEY}.md` | `GO-223.md`, `TMPL-15257.md` |
| Баги (Jira) | `{JIRA-KEY}.md` | `AN-12675.md` |
| Эпики | `{JIRA-KEY}.md` или `E-{NN}-{slug}.md` | `E-12-унификация-rules.md` |
| Knowledge | `knowledge-{slug}.md` или `K-{DOMAIN}-{NNNN}.md` | `K-SEARCH-ENGINE-0004.md` |
| Концепции | `C-{NNNN}-{slug}.md` | `C-0003-process-idea-workflow-v1.0.md` |
| Проекты | `{slug}.md` | `r6.md`, `r7.md` |
| Ежедневный отчёт разработки | `{YYYY.MM.DD}-Daily_Dev_Report.md` | `2026.06.09-Daily_Dev_Report.md` |
| Еженедельный отчёт | `{YYYY-MM-DD}-week-{NN}.md` | `2026-06-08-week-24.md` |
| Конкурентный анализ | `{YYYY-MM-DD}-feature-analysis-week{NN}-{NN}.md` | `2026-06-07-feature-analysis-week22-23.md` |
| Синтезы | `synthesis-{YYYY-MM-DD}.md` | `synthesis-2026-05-21.md` |
| Конкуренты (страницы) | `{slug}.md` | `airbnb.md`, `booking-com.md` |

> ⚠️ Форматы в `wiki/reports/` неоднородны — встречаются `YYYY-MM-DD-*`, `YYYY.MM.DD-*` и просто `{slug}.md`. Единого стандарта для отчётов нет.



## pm_assistant — Регулярные задачи

### Настроенные автоматические запуски

#### 1. Ночная обработка очереди raw (vault-ingest-queue)

| Параметр | Значение |
|---|---|
| Расписание | Ежедневно в 02:00 МСК |
| Исполнитель | Headless Claude Code (Windows Task Scheduler) |
| Модель | `claude-sonnet-4-6` (зафиксирована флагом `--model`) |
| Скрипт | `pm_assistant/jobs/vault-ingest-queue/` |

Обрабатывает необработанные raw-файлы батчами по 10–15 штук (с самых свежих):
- `raw/inbound/meeting-notes/`
- `raw/inbound/clippings/`
- `raw/inbound/misc/`
- `raw/inbound/ideas/`

Файлы из `raw/competitors/` — только по команде `/compile-competitor-report`.

Критерий обработки: DoD §6a — в wiki должен существовать артефакт с `source:`, указывающим на raw-файл.

> ⚠️ Cowork-задача `vault-ingest-queue` отключена (нет контроля модели). Активен только headless-джоб.

---

#### 2. Утренний дайджест задач (morning-digest)

| Параметр | Значение |
|---|---|
| Расписание | Пн–Пт в 08:31 МСК |
| Исполнитель | Cowork scheduled task |
| Task ID | `morning-digest` |

Формирует дайджест продуктового бэклога и личных ToDo на текущий день.

---

#### 3. Ежедневный статус разработки (daily-dev-status-report)

| Параметр | Значение |
|---|---|
| Расписание | Ежедневно в 18:00 МСК |
| Исполнитель | Cowork scheduled task |
| Task ID | `daily-dev-status-report` |

Итоговый статус разработки по активным задачам.

---

#### 4. Еженедельный отчёт по результатам разработки *(запланировано)*

| Параметр | Значение |
|---|---|
| Расписание | Еженедельно (пятница) |
| Исполнитель | Cowork scheduled task |
| Task ID | weekly-pm-report |

Агрегированный еженедельный отчёт: закрытые задачи, блокеры, прогресс по эпикам.

---

#### 5. Анализ рынка и конкурентов (competitor-analysis)

| Параметр | Значение |
|---|---|
| Расписание | Раз в 2 недели |
| Исполнитель | Cowork scheduled task |
| Task ID | `competitor-analysis` |

Сбор и анализ данных по конкурентам из `raw/competitors/`. Формирует отчёт в `wiki/domains/search-engine/reports/competitors/`.
