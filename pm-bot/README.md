# PM Bot — автоматизация рабочих заметок

Telegram-бот + Docker, который автоматизирует три потока:
1. **Идеи** из Telegram → структурированные заметки в Obsidian Inbox
2. **Транскрипты** Яндекс Телемост → заметки встреч в Obsidian Meetings
3. **Задачи** из Telegram → черновики Jira-тикетов в Obsidian Tasks/Drafts

---

## Быстрый старт

### 1. Создай Telegram-бота
- Найди @BotFather в Telegram
- Отправь `/newbot`, задай имя и username
- Скопируй BOT_TOKEN

### 2. Получи Claude API ключ
- Зайди на console.anthropic.com
- Создай API key

### 3. Настрой .env
```
cp .env.example .env
```
Открой `.env` и заполни:
- `BOT_TOKEN` — токен от BotFather
- `CLAUDE_API_KEY` — ключ Claude API
- `VAULT_PATH` — путь к папке Obsidian vault, например `C:/Users/Igor/Documents/MyVault`
- `TRANSCRIPTS_INBOX` — папка куда ты сохраняешь транскрипты, например `C:/Users/Igor/Downloads/Telemost`
- `ALLOWED_CHAT_ID` — оставь пустым пока

### 4. Узнай свой Chat ID
```bash
docker compose up
```
Напиши боту `/start` — он ответит твоим Chat ID.
Скопируй число в `ALLOWED_CHAT_ID` в `.env`.

### 5. Перезапусти
```bash
docker compose down
docker compose up -d
```

---

## Использование

**Поток 1 — Идея:**
Просто напиши боту любой текст → заметка появится в `Inbox/`

**Поток 2 — Встреча:**
Скопируй файл транскрипта `.txt` из Яндекс Телемост в папку `TRANSCRIPTS_INBOX` → заметка появится в `Meetings/` автоматически

**Поток 3 — Jira-тикет:**
Напиши боту `/jira`, затем опиши задачу → черновик появится в `Tasks/Drafts/`

---

## Структура папок в Obsidian vault

```
YourVault/
  Inbox/          ← идеи из Telegram
  Meetings/       ← заметки встреч из транскриптов
  Tasks/
    Drafts/       ← черновики Jira-тикетов
```

---

## Настройка промптов

Промпты находятся в `app/prompts/`:
- `idea.txt` — шаблон для идей
- `meeting.txt` — шаблон для встреч
- `jira_ticket.txt` — шаблон для Jira

Можно редактировать под свои нужды. После изменений перезапусти контейнер:
```bash
docker compose restart
```
