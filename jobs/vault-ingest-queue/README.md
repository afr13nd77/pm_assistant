# vault-ingest-queue (BL-118)

Ночная обработка очереди необработанных raw-файлов vault по `ingest_dod` (CLAUDE.md §6a).
Исполнитель — **headless Claude Code**, модель закреплена флагом `--model claude-sonnet-4-6`.

## Состав

- `vault-ingest-queue.prompt.md` — промпт прогона (самодостаточный)
- `vault-ingest-queue.ps1` — раннер: читает промпт, запускает `claude -p` из корня vault, пишет лог в `logs/`
- `logs/` — журналы прогонов (ротация: 30 последних)

## Требования

- Claude Code CLI в PATH (`claude --version`)
- Выполненный `claude login` под пользователем, от которого идёт запуск

## Регистрация в Windows Task Scheduler (ежедневно 02:00)

```bat
schtasks /Create /TN "vault-ingest-queue" /SC DAILY /ST 02:00 ^
  /TR "powershell -NoProfile -ExecutionPolicy Bypass -File \"I:\ai_projects\pm_assistant\jobs\vault-ingest-queue\vault-ingest-queue.ps1\""
```

Проверка вручную:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "I:\ai_projects\pm_assistant\jobs\vault-ingest-queue\vault-ingest-queue.ps1"
```

## Примечания

- Запуск из корня vault → срабатывают хуки SessionStart / Stop, прогон учитывается Token Logger.
- `--permission-mode acceptEdits` + allowlist read-only bash: файловые правки автоодобряются, произвольные команды — нет.
- Бывшая Cowork-задача `vault-ingest-queue` отключена 10.06.2026 (запускалась не на той модели).
- Контроль качества: первые батчи проверять глазами (разметка доменов, source-ссылки, записи в LOG.md).
