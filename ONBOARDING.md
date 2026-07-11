# PM Assistant -- Onboarding

## 1. Что такое PM Assistant

PM Assistant -- система автоматизации рабочих заметок продакт-менеджера OTA-компании. Система состоит из 4 Docker-контейнеров: Telegram-бот, сервис обогащения знаний, конвейер проработки идей и cron-планировщик. PM Assistant автоматизирует полный цикл жизни идеи: от сырой мысли в Telegram до готового эпика в Jira.

Хранилище знаний построено по модели Андрея Карпати (Andrej Karpathy): **raw -> compile -> wiki**. Слой `raw/` содержит неизменяемые оригиналы (append-only) -- все, что захвачено (идея, транскрипт, тикет, клиппинг), сохраняется as-is. Слой `wiki/` -- скомпилированное знание: структурированные заметки с YAML frontmatter, перекрестными ссылками и индексами, организованные по продуктовым доменам. Слой `templates/` -- шаблоны артефактов (idea, epic, userstory, task, bug, ADR).

Философия проекта -- **vault-as-database**: Obsidian vault с Markdown-файлами заменяет классическую БД. Frontmatter = метаданные, тело файла = контент, файловая система = индекс. Файлы одновременно читаемы человеком (в Obsidian) и машиной (через API). Единственный источник правды -- vault.

---

## 2. Архитектура

### 2.1. Контейнеры

Система развернута в 4 Docker-контейнерах:

| Контейнер | Роль | Порты | Команда запуска |
|---|---|---|---|
| **pm-bot** | Telegram polling + Vault API + Web UI сервер | 8000 (FastAPI), 8080 (Web UI) | `python -m http.server 8080 --directory /web & python -m app.main` |
| **knowledge-engine** | HTTP API + Watchdog на Inbox/ для auto-enrichment | 8001 (FastAPI) | `python -m knowledge_engine serve & python -m knowledge_engine watch` |
| **idea-pipeline** | Orchestrator: Analyst -> PM -> Decomposer | 8100 (FastAPI) | `python -m idea_pipeline serve` |
| **ke-cron** | 6 cron-задач (синтез, Jira sync, fetch-meetings, rebuild-index, lint, health) | -- | `crond` |

Все контейнеры используют один и тот же Obsidian vault, смонтированный как Docker volume (`/vault`). Файл `settings.yaml` монтируется read-only во все контейнеры.

### 2.2. Потоки данных

Система обрабатывает 9 потоков:

1. **Идеи**: Telegram/Web capture -> claude_client.process_idea (JSON) -> obsidian_writer.write_idea (template-based) -> `raw/inbound/ideas/` + `wiki/domains/<domain>/ideas/` -> knowledge-engine enrich
2. **Транскрипты**: `.txt` -> transcript_watcher -> process_meeting -> `raw/inbound/meeting-notes/` + `wiki/meetings/`
3. **Meeting fetcher**: IMAP email -> fetch -> classify -> `raw/inbound/meeting-notes/` + `wiki/meetings/` -> enrich -> notify
4. **Jira-тикеты**: Telegram `/jira` -> process_jira_ticket -> `raw/inbound/tasks/` + `wiki/domains/<domain>/tasks/`
5. **Daily-заметки**: Telegram `/daily` -> process_daily -> `raw/inbound/daily-logs/` + `wiki/daily-logs/`
6. **Jira Sync** (cron каждые 3ч или `/jira_sync`): fetch JQL -> diff state -> write `wiki/domains/<domain>/tasks/` + `raw/inbound/tasks/` -> Telegram notify
7. **Idea Pipeline** (Telegram `/pipeline` или API): Analyst -> PM -> Decomposer -> `Pipeline/<date>-<slug>/` (analysis.md, PRD.md, epic.md, tasks/*.md)
8. **Enrichment Reminders** (daily cron): scan ideas -> filter by readiness < 100% -> SQLite cooldown -> Telegram notify
9. **Synthesis** (cron 09:00 или `/synthesize`): кластеризация + сводка -> `wiki/reports/synthesis-*.md`

### 2.3. LLM-слой

Гибридная архитектура с двумя провайдерами:

| Провайдер | Модель | Назначение |
|---|---|---|
| **Ollama** (локальный) | QWEN 3.5 | Рутинные задачи: классификация, извлечение ключевых слов, простая структуризация |
| **Claude API** (облачный) | claude-sonnet-4-6 | Сложные задачи: синтез, enrichment, pipeline, еженедельные отчеты |

Три режима работы:
- **Hybrid** (по умолчанию) -- автоматический выбор провайдера по типу задачи. Если Ollama недоступен -- fallback на Claude API.
- **Claude** -- все запросы через Claude API.
- **Ollama** -- все запросы через локальный Ollama.

Переключение режима -- через Web UI (Settings -> LLM Provider) или переменные окружения.

Голосовые сообщения транскрибируются локально через **faster-whisper** (модель `small`, CPU, int8). Управление: переменная `STT_ENABLED` (по умолчанию включен).

### 2.4. Web UI

9 страниц статического SPA на Vue 3 + vanilla JS. Данные получают из Vault API (FastAPI, порт 8000) через `api.js`.

| Страница | Назначение |
|---|---|
| overview.html | Command center: system status, idea funnel, KPI, activity feed, quick capture |
| ideas.html | Канбан идей: 4 колонки по статусам, фильтр по доменам, drag-n-drop, readiness %, capture drawer |
| board.html | Канбан-доска задач (auto-refresh 30s / manual) |
| dashboard.html | Домены, статистика артефактов, Jira sync status |
| roadmap.html | Roadmap с эпиками и прогрессом (auto-refresh 60s / manual) |
| timeline.html | Таймлайн фич |
| report.html | Просмотр еженедельных отчетов (Markdown -> HTML через marked.js) |
| settings.html | Настройки: тема, refresh mode, LLM Provider, prompts, Jira sync |
| about.html | О сервисе: версии компонентов, история изменений |

Dual-theme: **MATRIX** (dark, glow/neon) и **LIGHT** (cream, warm). Переключение в settings, хранение серверное (`.pm-user-prefs.json` в vault).

### 2.5. Доменная структура vault

Знания организованы по 5 продуктовым доменам:

```
wiki/domains/
├── static-metadata/
├── suggester/
├── search-engine/
├── partner-search-engine/
└── general/
```

Каждый домен содержит подпапки: `ideas/`, `epics/`, `tasks/`, `bugs/`, `knowledge/`, а также служебные файлы `index.md`, `log.md`, `decisions.md`, `glossary.md`.

Конфигурация доменов (display_name, description, color, jira_labels, tags, keywords) хранится в файле `domain-config.yaml` в корне vault.

---

## 3. Развертывание с нуля

### Требования

- Docker Desktop (4GB RAM минимум)
- Git
- Аккаунт Telegram для создания бота
- Ключ Claude API (console.anthropic.com)
- Personal Access Token для Jira (если нужна Jira-интеграция)

### Шаг 1. Клонирование репозитория

```bash
git clone https://github.com/afr13nd77/pm_assistant.git
cd pm_assistant
```

### Шаг 2. Настройка переменных окружения

```bash
cp .env.example .env
```

Открыть `.env` и заполнить обязательные переменные (см. раздел 4).

Минимальный набор для первого запуска:

```
BOT_TOKEN=<токен от @BotFather>
CLAUDE_API_KEY=<ключ с console.anthropic.com>
VAULT_PATH=C:/Users/YourName/Documents/ObsidianVault
TRANSCRIPTS_INBOX=C:/Users/YourName/Downloads/Telemost
ALLOWED_CHAT_ID=
JIRA_URL=https://your-jira-server.com
JIRA_TOKEN=<Personal Access Token>
PIPELINE_API_URL=http://idea-pipeline:8100
```

Путь `VAULT_PATH` на Windows указывать с прямыми слешами: `C:/Users/...`.

### Шаг 3. Создание структуры vault

Если vault уже существует и содержит нужные папки -- пропустить этот шаг.

Для нового vault создать структуру:

```
raw/
├── inbound/
│   ├── ideas/
│   ├── meeting-notes/
│   ├── daily-logs/
│   ├── tasks/
│   ├── clippings/
│   └── misc/
├── competitors/
└── metrics/

wiki/
├── domains/
│   ├── static-metadata/
│   │   ├── ideas/
│   │   ├── epics/
│   │   ├── tasks/
│   │   ├── bugs/
│   │   └── knowledge/
│   ├── suggester/
│   │   ├── ideas/
│   │   ├── epics/
│   │   ├── tasks/
│   │   ├── bugs/
│   │   └── knowledge/
│   ├── search-engine/
│   │   ├── ideas/
│   │   ├── epics/
│   │   ├── tasks/
│   │   ├── bugs/
│   │   └── knowledge/
│   ├── partner-search-engine/
│   │   ├── ideas/
│   │   ├── epics/
│   │   ├── tasks/
│   │   ├── bugs/
│   │   └── knowledge/
│   └── general/
│       ├── ideas/
│       ├── epics/
│       ├── tasks/
│       ├── bugs/
│       └── knowledge/
├── meetings/
├── daily-logs/
├── reports/
├── concepts/
├── teams/
└── projects/

templates/
```

### Шаг 4. Сборка и запуск

```bash
docker compose up --build
```

Первая сборка занимает 3-5 минут (скачивание зависимостей, модели Whisper).

Для фонового запуска:

```bash
docker compose up -d
```

### Шаг 5. Проверка работоспособности

1. **Telegram-бот**: отправить `/start` боту в Telegram. Бот должен ответить приветствием.
2. **Web UI**: открыть `http://localhost:8080` (или `http://<server-ip>:8080`). Должна загрузиться страница overview.
3. **KE API**: выполнить `curl http://localhost:8001/health` -- ответ `{"status": "ok"}`.

### Шаг 6. Получение ALLOWED_CHAT_ID

Если `ALLOWED_CHAT_ID` оставлен пустым:

1. Отправить `/start` боту в Telegram.
2. Бот ответит вашим Chat ID.
3. Скопировать число в `.env`: `ALLOWED_CHAT_ID=123456789`.
4. Перезапустить контейнеры:

```bash
docker compose down
docker compose up -d
```

---

## 4. Переменные окружения

Файл `.env` в корне проекта. Шаблон: `.env.example`.

| Переменная | Обязательная | Сервис | Описание | Где получить |
|---|---|---|---|---|
| `BOT_TOKEN` | да | pm-bot | Токен Telegram-бота | @BotFather в Telegram |
| `CLAUDE_API_KEY` | да | все | Ключ Claude API | console.anthropic.com |
| `VAULT_PATH` | да | все | Путь к Obsidian vault (прямые слеши на Windows) | Локальный путь |
| `TRANSCRIPTS_INBOX` | да | pm-bot | Папка транскриптов Яндекс Телемост | Локальный путь |
| `ALLOWED_CHAT_ID` | да | pm-bot | Chat ID владельца бота (пустой = режим первого запуска) | Отправить /start боту |
| `JIRA_URL` | да | knowledge-engine | URL Jira-сервера | Адрес Jira |
| `JIRA_TOKEN` | да | knowledge-engine | Personal Access Token (Bearer auth) | Настройки Jira -> PAT |
| `PIPELINE_API_URL` | да | pm-bot | URL idea-pipeline API | `http://idea-pipeline:8100` |
| `JIRA_SYNC_CRON` | нет | ke-cron | Расписание Jira sync (cron-выражение) | Default: `0 */3 * * *` |
| `KE_SYNTHESIS_CRON` | нет | ke-cron | Расписание синтеза | Default: `0 9 * * *` |
| `KE_MIN_IDEAS_FOR_SYNTHESIS` | нет | ke-cron | Минимум идей для запуска синтеза | Default: `1` |
| `STT_ENABLED` | нет | pm-bot | Включить Speech-to-Text (Whisper) | Default: `1` |
| `OLLAMA_URL` | нет | pm-bot, KE | URL Ollama-сервера | Настраивается через Web UI |
| `OLLAMA_MODEL` | нет | pm-bot, KE | Модель Ollama | Default: `qwen3.5:latest` |
| `ENRICHMENT_REMINDER_HOUR` | нет | pm-bot | Час проверки enrichment | Default: `10` |
| `ENRICHMENT_COOLDOWN_HOURS` | нет | pm-bot | Cooldown между напоминаниями (часы) | Default: `24` |
| `ENRICHMENT_HOST_URL` | нет | pm-bot | Базовый URL для ссылок в напоминаниях | Default: `http://localhost:8080` |
| `DAILY_ALERT_HOUR` | нет | pm-bot | Час проверки наличия Daily-протокола | Default: `18` |
| `KE_API_URL` | нет | pm-bot | URL KE HTTP API | Default: `http://knowledge-engine:8001` |
| `DB_PATH` | нет | pm-bot | Путь к SQLite БД внутри контейнера | Default: `/data` |
| `PIPELINE_API_KEY` | нет | pm-bot, pipeline | API key для аутентификации pipeline | Произвольная строка |
| `PIPELINE_HOST` | нет | pipeline | Bind host | Default: `0.0.0.0` |
| `PIPELINE_PORT` | нет | pipeline | Bind port | Default: `8100` |

---

## 5. Конфигурация runtime (settings.yaml)

Файл `settings.yaml` в корне проекта. Монтируется read-only во все контейнеры (`./settings.yaml:/app/settings.yaml:ro`). Все значения имеют дефолты в `shared/settings.py` -- файл опционален.

```yaml
timeouts:
  enrich: 30          # таймаут обогащения (сек)
  synthesize: 120     # таймаут синтеза
  fetch_meetings: 180 # таймаут импорта встреч
  jira_sync: 120      # таймаут Jira sync
  jira_import: 60     # таймаут импорта одного тикета
  jira_create: 120    # таймаут создания тикета
  health: 60          # таймаут health check
  default: 60         # таймаут по умолчанию

cooldowns:
  enrichment_reminder_hours: 24    # минимум часов между напоминаниями
  health_history_days: 90          # хранение истории health score
  enrichment_cleanup_days: 90      # очистка старых записей enrichment

cache_ttl:
  vault_api_seconds: 30     # TTL кеша Vault API
  jira_cache_seconds: 300   # TTL кеша Jira
  domains_cache_seconds: 60 # TTL кеша доменов

rate_limits:
  telegram_messages_per_second: 1    # лимит сообщений Telegram
  telegram_retry_after_default: 5    # retry при rate limit (сек)
  telegram_max_queue_size: 50        # размер очереди сообщений

paths:
  db_dir: /data    # директория SQLite

ports:
  ke_api: 8001     # порт KE API
```

Для изменения: отредактировать `settings.yaml` и перезапустить контейнеры (`docker compose restart`).

---

## 6. Cron-задачи

### 6.1. ke-cron контейнер

6 задач, выполняемых по расписанию внутри контейнера `ke-cron`:

| Задача | Расписание | Команда | Описание |
|---|---|---|---|
| Синтез | 09:00 ежедневно | `knowledge_engine synthesize --notify` | Кластеризация идей + сводка |
| Jira sync | Каждые 3 часа | `knowledge_engine jira-sync --notify` | Синхронизация тикетов из Jira |
| Fetch meetings | Каждый час (:15) | `knowledge_engine fetch-meetings --notify` | Импорт транскриптов из email |
| Rebuild index | 02:00 ежедневно | `knowledge_engine rebuild-index` | Пересборка индекса vault |
| Lint | 03:00 ежедневно | `knowledge_engine lint` | Проверка frontmatter, структуры, ссылок |
| Health | 04:00 ежедневно | `knowledge_engine health --save` | Расчет vault health score |

Расписание Jira sync настраивается переменной `JIRA_SYNC_CRON` (default: `0 */3 * * *`).
Логи cron: `docker compose logs -f ke-cron`.

### 6.2. Cowork scheduled tasks (Claude Desktop)

Аналитические задачи, выполняемые через Claude Desktop Cowork:

| Задача | Расписание | Описание |
|---|---|---|
| morning-digest | Пн--Пт 08:31 МСК | Дайджест продуктового бэклога и ToDo |
| daily-dev-status-report | Ежедневно 18:00 МСК | Итоговый статус разработки |
| weekly-pm-report | Еженедельно (пятница) | Отчет: закрытые задачи, блокеры, прогресс по эпикам |
| competitor-analysis | Раз в 2 недели | Анализ рынка и конкурентов |

### 6.3. Headless Claude Code

| Задача | Расписание | Исполнитель | Описание |
|---|---|---|---|
| vault-ingest-queue | 02:00 ежедневно | Windows Task Scheduler | Обработка очереди raw-файлов батчами |

---

## 7. Бэкап и восстановление

### 7.1. Что бэкапить

| Компонент | Тип | Критичность | Расположение |
|---|---|---|---|
| Vault (Markdown-файлы) | Файлы | Высокая | `VAULT_PATH` |
| SQLite БД | Volume | Средняя | Docker volume `pm-bot-data` |
| `.env` | Файл | Высокая | Корень проекта |
| `settings.yaml` | Файл | Средняя | Корень проекта |
| `domain-config.yaml` | Файл | Средняя | Корень vault |
| `pipeline.yaml` | Файл | Низкая | `idea-pipeline/pipeline.yaml` |

### 7.2. Важные файлы в vault

Эти файлы создаются и обновляются автоматически, потеря потребует восстановления:

- `.health-history.json` -- история vault health score (90 дней)
- `.jira-sync-state.json` -- состояние синхронизации с Jira
- `.pm-user-prefs.json` -- пользовательские настройки Web UI (тема, refresh mode)
- `domain-config.yaml` -- конфигурация доменов
- `templates/idea.md` -- шаблон идеи

### 7.3. Методы бэкапа

**Vault backup**:
- Яндекс.Диск -- автоматическая синхронизация (основной метод)
- Git -- рекомендуется для версионирования

**SQLite backup**:

```bash
docker cp pm-bot:/data/ ./backup/
```

### 7.4. Восстановление

```bash
# 1. Остановить контейнеры
docker compose down

# 2. Восстановить vault из бэкапа
# (скопировать файлы в VAULT_PATH)

# 3. Восстановить SQLite (если нужно)
docker cp ./backup/data/ pm-bot:/data/

# 4. Проверить .env и settings.yaml

# 5. Запустить
docker compose up -d

# 6. Проверить health
curl http://localhost:8001/health
```

---

## 8. Troubleshooting

| Симптом | Причина | Решение |
|---|---|---|
| Бот не отвечает в Telegram | Неверный `BOT_TOKEN` или `ALLOWED_CHAT_ID` | Проверить `.env`. Логи: `docker compose logs -f pm-bot` |
| Web UI не загружается | Контейнер pm-bot не запущен или порт 8080 занят | `docker compose ps` для проверки статуса. Проверить порт: `netstat -an \| findstr 8080` |
| Jira sync не работает | Неверный `JIRA_URL` или `JIRA_TOKEN` | Проверить `.env`. Логи: `docker compose logs -f ke-cron`. Тест: `/jira_sync` в Telegram |
| Health score низкий | Накопились необработанные raw-файлы, битые ссылки | `docker compose exec knowledge-engine python -m knowledge_engine health --json` для диагностики |
| Enrichment не срабатывает | Watchdog в knowledge-engine не работает | Проверить, что контейнер knowledge-engine запущен. Логи: `docker compose logs -f knowledge-engine` |
| Pipeline зависает | Исчерпан лимит Claude API или ошибка ключа | Проверить `CLAUDE_API_KEY` и лимиты на console.anthropic.com. Логи: `docker compose logs -f idea-pipeline` |
| STT/Whisper crash | Несовместимая CPU-инструкция | В docker-compose.yml уже установлено `CT2_FORCE_CPU_ISA=GENERIC`. Проверить `shm_size: 512m` |
| Docker disk full | Docker Desktop достиг лимита диска (29-30GB) | `docker system prune` для очистки. Увеличить лимит в Docker Desktop Settings -> Resources |
| Кеш vault_api устарел | Данные Web UI не обновляются 30+ секунд | Перезапустить pm-bot: `docker compose restart pm-bot`. Кеш автоматически сбрасывается через 30с TTL |
| Контейнер перезапускается в цикле | Ошибка в `.env` или недоступный volume | `docker compose logs -f <service>` для диагностики. Проверить все пути в `.env` |
| Web UI не применяет тему | Некорректный `.pm-user-prefs.json` в vault | Удалить `.pm-user-prefs.json` из vault и перезапустить pm-bot. Тема вернется к дефолту (MATRIX) |
| Ollama недоступен | Ollama-сервер не запущен или неверный `OLLAMA_URL` | Проверить `OLLAMA_URL`. Fallback на Claude API происходит автоматически. Тест: Settings -> LLM Provider -> Test Connection |
| Транскрипт не обрабатывается | Файл не `.txt` или watcher не отслеживает папку | Проверить `TRANSCRIPTS_INBOX` в `.env`. Файл должен иметь расширение `.txt`. Логи: `docker compose logs -f pm-bot \| grep watcher` |

---

## 9. Команды

### 9.1. Docker-команды

| Действие | Команда |
|---|---|
| Запуск (с пересборкой) | `docker compose up --build` |
| Запуск фоном | `docker compose up -d` |
| Остановка | `docker compose down` |
| Логи pm-bot | `docker compose logs -f pm-bot` |
| Логи knowledge-engine | `docker compose logs -f knowledge-engine` |
| Логи ke-cron | `docker compose logs -f ke-cron` |
| Логи idea-pipeline | `docker compose logs -f idea-pipeline` |
| Пересборка без кеша | `docker compose down && docker compose build --no-cache && docker compose up -d` |
| Статус контейнеров | `docker compose ps` |

### 9.2. Тесты, линтер, типы

| Действие | Команда | Откуда |
|---|---|---|
| Линтер | `ruff check pm-bot/app/ knowledge-engine/app/ idea-pipeline/app/` | pm_assistant/ |
| Линтер (автофикс) | `ruff check --fix pm-bot/app/ knowledge-engine/app/ idea-pipeline/app/` | pm_assistant/ |
| Типы (KE) | `mypy knowledge-engine/app/ --config-file pyproject.toml` | pm_assistant/ |
| Типы (pm-bot) | `mypy pm-bot/app/ --config-file pyproject.toml` | pm_assistant/ |
| Тесты KE | `PYTHONPATH=knowledge-engine pytest knowledge-engine/tests/` | pm_assistant/ |
| Тесты pm-bot | `PYTHONPATH=pm-bot:knowledge-engine pytest pm-bot/tests/` | pm_assistant/ |
| Тесты pipeline | `PYTHONPATH=idea-pipeline:knowledge-engine pytest idea-pipeline/tests/` | pm_assistant/ |
| Тесты Web UI | `node pm-bot/web/tests/test-report-node.js` | pm_assistant/ |

### 9.3. CLI knowledge-engine (внутри контейнера)

```bash
docker compose exec knowledge-engine python -m knowledge_engine <command>
```

| Команда | Описание |
|---|---|
| `enrich <path>` | Обогатить файл связями из vault |
| `synthesize` | Запустить синтез |
| `jira-sync --notify` | Синхронизация с Jira + уведомление в Telegram |
| `jira-sync --dry-run` | Пробная синхронизация (без записи) |
| `jira-import <ISSUE-KEY>` | Импорт одного тикета |
| `index` | Пересборка индекса vault |
| `lint` | Проверка vault |
| `status` | Статус сервиса |
| `health --json` | Health score в JSON |

### 9.4. Telegram-команды бота

| Команда | Описание |
|---|---|
| `/start` | Приветствие, показ Chat ID (при первом запуске) |
| `/idea <текст>` | Создать идею из текста |
| `/jira <текст>` | Создать черновик Jira-тикета |
| `/daily <текст>` | Создать daily-протокол |
| `/synthesize` | Запустить синтез идей |
| `/jira_sync` | Запустить синхронизацию с Jira |
| `/jira_import <KEY>` | Импортировать тикет по ключу |
| `/jira_create` | Создать тикет в Jira из vault |
| `/pipeline <текст>` | Запустить idea-pipeline (Analyst -> PM -> Decomposer) |
| `/domain` | Управление доменами |
| `/lint` | Запустить линтер vault |
| `/status` | Статус системы |
| `/test_enrichment` | Тестовый запуск enrichment-напоминаний |
| `/progress` | Ежедневный отчет о ходе проекта |

Текстовое сообщение без команды обрабатывается как идея. Голосовое сообщение транскрибируется (Whisper) и обрабатывается как идея.

---

## 10. Ссылки

| Ресурс | URL |
|---|---|
| GitHub | https://github.com/afr13nd77/pm_assistant |
| Vault API | http://192.168.0.6:8000 |
| Web UI | http://192.168.0.6:8080 |
| KE API | http://192.168.0.6:8001 (health: `/health`) |
| Pipeline API | http://192.168.0.6:8100 |
| Структура проекта | `index.md` |
| Бэклог | `BACKLOG.md` |
| Журнал изменений | `CHANGELOG.md` |
| Спеки и документация | `docs/` |
