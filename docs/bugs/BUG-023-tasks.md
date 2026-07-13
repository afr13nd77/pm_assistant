# BUG-023: Задачи

## T-01 [opus] — Добавить `_find_vault_file_by_jira_key()` в fetcher.py
  Traces to: AC-01, AC-02, AC-05
  File: knowledge-engine/app/jira_fetcher/fetcher.py
  Task: Добавить функцию `_find_vault_file_by_jira_key(domain, jira_key, artifact_types)`.
    Логика: для каждого artifact_type из переданного набора сканировать
    `vault_paths.wiki_domain_dir(domain, art_type)` → перебрать `*.md` файлы →
    прочитать frontmatter через `frontmatter_utils.read_frontmatter` →
    если `fm.get("jira_key") == jira_key` → вернуть Path.
    Если ничего не найдено → вернуть None.
    Логирование: info при нахождении (с путём), debug при скане (количество файлов),
    info при ненахождении.
  Context: Сейчас файлы ищутся только по имени `{KEY}.md`. Функция `_find_vault_file` (строка 597)
    ищет тоже по имени файла, не по frontmatter. Новая функция — fallback для файлов
    с кастомными именами (E-15-*.md, E-18-*.md), созданных через PM Assistant.
    Использовать `from shared import frontmatter_utils`.
  Depends on: —
  Verify: python -c "from knowledge_engine.app.jira_fetcher.fetcher import _find_vault_file_by_jira_key; print('OK')"
  Status: [✓] done

## T-02 [opus] — Fallback в секции 6 (UPDATED issues) + partial update
  Traces to: AC-01, AC-02, AC-04
  File: knowledge-engine/app/jira_fetcher/fetcher.py
  Task: В секции 6 (строка 275-285) после `wiki_path = wiki_dir / f"{key}.md"`:
    1. Если `wiki_path.exists()` — False, вызвать `_find_vault_file_by_jira_key(domain, key, {art_type, "tasks", "epics"})`
    2. Если найден файл через fallback:
       - Использовать `frontmatter_utils.update_frontmatter(wiki_path, {...})` для точечного обновления
         полей `status`, `synced_at`, `updated_at`, `assignee`, `priority`
       - НЕ вызывать `to_markdown()` / `mapper.update_frontmatter()` — они делают полный rewrite
       - Логировать: "sync: updated custom-named file via fallback: {path}"
    3. Если wiki_path.exists() — True (стандартный flow) — оставить без изменений
  Context: `update_frontmatter` из mapper.py (строка 302) вызывает `to_markdown()` — полный rewrite,
    который уничтожает пользовательский контент (goals, scope, AC, decisions).
    `frontmatter_utils.update_frontmatter` (shared/) обновляет только указанные поля.
  Depends on: T-01
  Verify: визуальная проверка кода
  Status: [✓] done

## T-03 [opus] — Fallback в секции 7 (CLOSED issues)
  Traces to: AC-01
  File: knowledge-engine/app/jira_fetcher/fetcher.py
  Task: В секции 7 (строка 392-407) внутри цикла `for try_art in {...}`:
    1. После `wiki_path = wiki_dir / f"{key}.md"`
    2. Если `not wiki_path.exists()` → вызвать `_find_vault_file_by_jira_key(domain, key, (try_art,))`
    3. Если найден → использовать этот path для regex-замены status
    4. Остальная логика (regex, atomic_write, updated_any_wiki) остаётся без изменений
  Context: Closed handler обновляет status через regex `re.sub(r"^status: .+$", ...)`.
    Это безопасно для кастомных файлов — меняет только строку status в frontmatter.
  Depends on: T-01
  Verify: визуальная проверка кода
  Status: [✓] done

## T-04 [opus] — Fallback в `import_single_issue`
  Traces to: AC-05
  File: knowledge-engine/app/jira_fetcher/fetcher.py
  Task: В `import_single_issue` (строка 538-545):
    1. После `wiki_path = wiki_dir / f"{key}.md"`
    2. Если `not wiki_path.exists()` → вызвать `_find_vault_file_by_jira_key(domain, key, {art_type, "tasks", "epics"})`
    3. Если найден → `wiki_path = found`, `is_update = True`
    4. При `is_update` для кастомного файла — использовать `frontmatter_utils.update_frontmatter`
       вместо `mapper.update_frontmatter` (аналогично T-02)
  Context: `import_single_issue` используется при `/jira_import <KEY>`. Без fallback
    создаёт дубликат `TMPL-16260.md` рядом с `E-15-*.md`.
  Depends on: T-01
  Verify: визуальная проверка кода
  Status: [✓] done

## T-05 [sonnet] — Unit-тесты
  Traces to: AC-01, AC-02, AC-03, AC-04, AC-05
  File: knowledge-engine/tests/test_jira_sync_custom_files.py (новый)
  Task: Написать unit-тесты:
    1. `test_find_by_jira_key_found` — файл с jira_key в frontmatter найден
    2. `test_find_by_jira_key_not_found` — jira_key не совпадает → None
    3. `test_find_by_jira_key_no_frontmatter` — файл без frontmatter → пропускается
    4. `test_updated_flow_fallback` — UPDATED issue, файл {KEY}.md не существует,
       кастомный файл найден → обновлён через frontmatter_utils (не rewrite)
    5. `test_updated_flow_standard` — UPDATED issue, файл {KEY}.md существует →
       стандартное поведение (AC-03, регрессия)
    6. `test_closed_flow_fallback` — CLOSED issue, файл {KEY}.md не существует,
       кастомный файл найден → status обновлён
    7. `test_import_fallback` — import_single_issue, кастомный файл найден → обновлён, дубликат не создан
    Использовать tmp_path fixture, mock для Jira API.
  Context: Существующие тесты в knowledge-engine/tests/. Следовать паттернам из test_jira_*.py.
  Depends on: T-01, T-02, T-03, T-04
  Verify: PYTHONPATH=knowledge-engine pytest knowledge-engine/tests/test_jira_sync_custom_files.py -v
  Status: [✓] done

## T-06 — Live test на Docker
  Traces to: AC-01, AC-02
  Task: Пересобрать Docker, запустить sync, проверить что E-15 и E-18 обновились.
    1. docker compose build knowledge-engine
    2. docker compose up -d
    3. Вызвать /jira_sync в Telegram или curl POST /api/v1/jira/sync
    4. Проверить файлы E-15-*.md и E-18-*.md — status должен обновиться
    5. Проверить что дубликаты TMPL-16260.md / TMPL-16285.md НЕ созданы
  Depends on: T-01, T-02, T-03, T-04, T-05
  Status: [✓] done
