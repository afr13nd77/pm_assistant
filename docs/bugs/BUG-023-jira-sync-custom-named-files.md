# BUG-023: Jira sync не обновляет статус vault-файлов с кастомными именами

## Severity: major

## Что сломано (observed behavior)

При синхронизации с Jira (`sync()`) статусы эпиков, созданных через PM Assistant
(с именами вида `E-15-retry-logic-import-phases.md`), **не обновляются**,
хотя статус в Jira изменился.

Sync state (`.jira-sync-state.json`) содержит корректный статус из Jira,
но vault-файл остаётся с устаревшим `status: бэклог`.

**Воспроизведено на:**
- E-15 (`jira_key: TMPL-16260`) — Jira status "Ready for development", vault status "бэклог"
- E-18 (`jira_key: TMPL-16285`) — Jira status "Создано", vault status "бэклог"

Синк от 13.07.2026 10:36 — state обновлён, файлы нет.

## Что должно происходить (expected behavior)

При `sync()` система должна:
1. Обнаружить, что `TMPL-16260.md` не существует
2. Найти файл `E-15-retry-logic-import-phases.md` по полю `jira_key: TMPL-16260` в frontmatter
3. Обновить `status` в этом файле на нормализованный статус из Jira

## Шаги воспроизведения

1. Создать эпик в vault с именем `E-XX-<slug>.md`
2. Вызвать `create_and_sync` → эпик попадает в Jira, `jira_key` записывается в frontmatter
3. Изменить статус задачи в Jira
4. Дождаться `sync()` (cron каждые 3 часа или ручной `/jira_sync`)
5. Проверить файл эпика → **статус не изменился**

## Окружение

- PM Assistant v1.17.1 / KE v1.15.0
- Docker on Windows, volume mount
- Vault path: `I:\Work\Sutochno_ru\08 project hotels claude\`

## Root Cause

### Проблема в `fetcher.py`: жёсткая привязка к конвенции `{JIRA_KEY}.md`

Три места в коде конструируют путь к файлу как `f"{key}.md"` без fallback-поиска:

**1. Секция 6 — UPDATED issues** (`fetcher.py:277`):
```python
wiki_path = wiki_dir / f"{key}.md"  # → TMPL-16260.md — не существует
```
Если файл не найден, создаёт **новый** `TMPL-16260.md` вместо обновления существующего `E-15-*.md`.

**2. Секция 7 — CLOSED issues** (`fetcher.py:395`):
```python
wiki_path = wiki_dir / f"{key}.md"  # → TMPL-16260.md — не существует
if wiki_path.exists():              # False → пропуск
```
Файл не найден → `updated_any_wiki = False` → обновление пропущено молча.

**3. `import_single_issue`** (`fetcher.py:539`):
```python
wiki_path = wiki_dir / f"{key}.md"
is_update = wiki_path.exists()      # False для кастомных имён
```
При повторном импорте создаст дубликат вместо обновления существующего файла.

### Вспомогательная проблема: `_find_vault_file` не используется в `sync()`

Функция `_find_vault_file` (строка 597) уже реализует поиск по имени файла
в директориях tasks/epics, но:
- Она тоже ищет по **имени файла**, а не по `jira_key` в frontmatter
- Используется только в `create_and_sync`, не в `sync()`

### Вторичный фактор: issues не попадают в JQL

JQL `(labels in (r6) and labels not in (backlog)) and project not in ("Задачи беклога Суточно.ру")`
не возвращает TMPL-16260 и TMPL-16285 (вероятно, проект TMPL исключён фильтром).
Из-за этого issues идут через closed-flow, но проблема с файлами остаётся та же.

## Дизайн исправления

### Новая функция `_find_vault_file_by_jira_key`

Добавить в `fetcher.py` функцию поиска vault-файла по `jira_key` в frontmatter:

```
def _find_vault_file_by_jira_key(
    domain: str,
    jira_key: str,
    artifact_types: Iterable[str] = ("epics", "tasks"),
) -> Path | None:
```

Логика:
1. Для каждого `artifact_type` в списке:
   - `wiki_dir = vault_paths.wiki_domain_dir(domain, art_type)`
   - Перебрать `*.md` файлы в директории
   - Прочитать frontmatter каждого файла (`frontmatter_utils.read_frontmatter`)
   - Если `jira_key` совпадает → вернуть путь
2. Если не найден ни в одном → вернуть `None`

### Изменения в `sync()`

**Секция 6 — UPDATED** (строка 275-285):

```
# 6a. Read existing wiki file if present, then update
wiki_dir = vault_paths.wiki_domain_dir(domain, art_type)
wiki_path = wiki_dir / f"{key}.md"

# Fallback: поиск по jira_key в frontmatter
if not wiki_path.exists():
    found = _find_vault_file_by_jira_key(domain, key, {art_type, "tasks", "epics"})
    if found:
        wiki_path = found
        logger.info("sync: found existing file by jira_key: %s", wiki_path)
```

При этом для UPDATED не делать полный `to_markdown` rewrite, а обновлять
только frontmatter-поля (`status`, `synced_at`, `updated_at`) через regex/frontmatter_utils,
сохраняя пользовательский контент файла.

**Секция 7 — CLOSED** (строка 392-407):

```
updated_any_wiki = False
search_types = {art_type, "tasks", "epics"}
for try_art in search_types:
    wiki_dir = vault_paths.wiki_domain_dir(domain, try_art)
    wiki_path = wiki_dir / f"{key}.md"

    # Fallback: поиск по jira_key
    if not wiki_path.exists():
        found = _find_vault_file_by_jira_key(domain, key, (try_art,))
        if found:
            wiki_path = found

    if wiki_path.exists():
        # ... существующая логика обновления status через regex
```

**`import_single_issue`** (строка 538-545):

Аналогичный fallback перед проверкой `is_update = wiki_path.exists()`.

### Оптимизация производительности

Полный скан frontmatter дорогой. Для минимизации:
- Сканировать только директории конкретного домена (не весь vault)
- Прекращать поиск при первом совпадении
- Логировать количество просканированных файлов для мониторинга

### Обновление `update_frontmatter` для кастомных файлов

Текущий `update_frontmatter` делает полный rewrite через `to_markdown()` —
это уничтожает пользовательский контент (goals, scope, AC, decisions).

Для файлов, найденных через fallback, обновлять только:
- `status` — нормализованный статус из Jira
- `synced_at` — текущий timestamp
- `updated_at` — timestamp из Jira (если доступен)

Использовать `frontmatter_utils.update_frontmatter(path, updates)` вместо
полного rewrite.

## Acceptance Criteria

```
AC-01:
  GIVEN: эпик E-15-retry-logic-import-phases.md с jira_key: TMPL-16260
  WHEN: sync() запускается и Jira возвращает статус "Ready for development"
  THEN: файл E-15-*.md обновляется: status: todo, synced_at обновлён

AC-02:
  GIVEN: задача с кастомным именем и jira_key в frontmatter
  WHEN: sync() запускается и задача помечена как UPDATED
  THEN: обновляется существующий файл, а НЕ создаётся дубликат {KEY}.md

AC-03:
  GIVEN: файл {KEY}.md существует (стандартный flow через jira-sync)
  WHEN: sync() запускается
  THEN: поведение не изменилось — файл обновляется как раньше (без fallback scan)

AC-04:
  GIVEN: кастомный файл найден через fallback
  WHEN: update_frontmatter вызывается
  THEN: обновляются только status/synced_at/updated_at, пользовательский контент сохранён

AC-05:
  GIVEN: import_single_issue вызывается для ключа с кастомным файлом
  WHEN: файл {KEY}.md не существует, но есть E-XX-*.md с jira_key
  THEN: обновляется существующий файл, дубликат не создаётся
```

## Out of Scope

- Изменение JQL-фильтра для включения проекта TMPL
- Переименование существующих файлов E-*.md → TMPL-*.md
- Кеширование маппинга jira_key → filepath (можно добавить позже)
- Обратная синхронизация статусов из vault → Jira
