# PM Bot — CLAUDE.md

Инструкции для Claude Code при работе с этим проектом.

## Что это за проект

Telegram-бот для автоматизации рабочих заметок продакт-менеджера OTA-компании.
Бот принимает сообщения → обрабатывает через Claude API → пишет структурированные `.md` файлы в Obsidian vault.

Три потока:
1. **Идеи** — текст из Telegram → `Inbox/` в Obsidian
2. **Транскрипты встреч** — `.txt` из Яндекс Телемост → `Meetings/` в Obsidian
3. **Jira-тикеты** — описание задачи → черновик в `Tasks/Drafts/` в Obsidian

## Стек

- Python 3.12
- `python-telegram-bot==21.5` — Telegram polling
- `anthropic>=0.40.0` — Claude API (модель `claude-sonnet-4-20250514`)
- `watchdog==4.0.1` — слежение за папкой транскриптов
- `python-dotenv==1.0.1` — конфигурация через `.env`
- Docker + docker-compose для запуска

## Структура проекта

  См. [index.md](index.md) — актуальная структура монорепо, стек, Docker-топология, команды.


## Переменные окружения

| Переменная | Описание |
|---|---|
| `BOT_TOKEN` | Токен Telegram-бота от @BotFather |
| `CLAUDE_API_KEY` | Ключ Claude API (console.anthropic.com) |
| `VAULT_PATH` | Абсолютный путь к Obsidian vault на хосте |
| `TRANSCRIPTS_INBOX` | Папка для входящих транскриптов Яндекс Телемост |
| `ALLOWED_CHAT_ID` | Telegram chat_id владельца бота (защита от чужих) |

## Локальная отладка (без Docker)

```bash
cd pm-bot
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
cp .env.example .env         # заполни .env
python -m app.main
```

Для отладки отдельных модулей:
```bash
# Проверить claude_client
python -c "from app.claude_client import process_idea; print(process_idea('тест идеи'))"

# Проверить obsidian_writer (создаст файл в VAULT_PATH)
python -c "from app.obsidian_writer import write_idea; write_idea('# Test', 'тест')"
```

## Docker

```bash
# Сборка и запуск
docker compose up --build

# Фоновый режим
docker compose up -d

# Пересборка без кэша (после изменений requirements.txt)
docker compose down
docker compose build --no-cache
docker compose up -d

# Логи
docker compose logs -f pm-bot
```

## Volumes в Docker

| Контейнер | Хост |
|---|---|
| `/vault` | `VAULT_PATH` из `.env` |
| `/transcripts/inbox` | `TRANSCRIPTS_INBOX` из `.env` |

Код монтируется внутрь при сборке — для изменений кода нужен `docker compose build`.

## Логика работы

### Telegram-хендлеры (handlers.py)

- Любой текст → режим `idea` (по умолчанию)
- `/idea` + текст → явный режим идеи
- `/jira` + текст → режим генерации тикета
- `/start` → если `ALLOWED_CHAT_ID` не задан, выводит chat_id пользователя

### Защита доступа

Бот принимает сообщения только от `ALLOWED_CHAT_ID`. Если переменная не задана (значение `0`), бот работает в режиме первого запуска — выводит chat_id и блокирует все действия.

### Transcript watcher (transcript_watcher.py)

Watchdog следит за `/transcripts/inbox`. При появлении `.txt` файла:
1. Читает файл
2. Отправляет в `process_meeting()`
3. Пишет заметку в `/vault/Meetings/`
4. Переименовывает оригинал, добавляя суффикс `.processed`
5. Отправляет уведомление в Telegram

### Именование файлов в vault

- Идеи: `YYYY-MM-DD-<первые 30 символов текста>.md`
- Встречи: `YYYY-MM-DD-<имя файла транскрипта>.md`
- Jira-черновики: `YYYY-MM-DD-jira-01.md`, `...-02.md` и т.д.

## Промпты

Все промпты в `app/prompts/*.txt`. Это plain text — можно редактировать без перезапуска Docker (при локальной отладке). В Docker нужен `docker compose restart`.

Промпт + разделитель `---` + пользовательский текст передаются как одно `user` сообщение.

## Известные проблемы

- `anthropic==0.34.0` конфликтует с `httpx` → используй `anthropic>=0.40.0`
- На Windows пути в `VAULT_PATH` указывать с прямыми слешами: `C:/Users/...`
- Watchdog на Windows требует `pip install watchdog[inotify]` для некоторых конфигураций — если watcher не срабатывает, попробуй этот вариант

## Domain-правила

Все домены определены в `domain-config.yaml` (в корне vault). Файл содержит display_name, description, color, jira_labels, tags, keywords, prompt_hint для каждого домена. Читается через `domain_config.load()` с mtime-кешем. Используется для:
- LLM-промпта идей (динамическая инжекция через `_build_idea_prompt`)
- Валидации доменов (`_get_valid_domains` с fallback на хардкод)
- Keyword-detection в `artifact_extractor` и `ingest` (merged maps: config extends hardcoded)

## Что не реализовано (backlog)

- [ ] Автосинхронизация Obsidian vault через облако

Актуальный бэклог: см. [BACKLOG.md](BACKLOG.md)
