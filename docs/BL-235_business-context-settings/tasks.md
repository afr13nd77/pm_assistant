# BL-235 — Task Breakdown

## T-01 [opus] — Добавить поле business_context в UserPrefs + GET seed из файла
  Traces to: US-01, AC-01, AC-05
  File: pm-bot/app/vault_api.py
  Task: 
    1. Добавить `business_context: str = ""` в класс `UserPrefs` (~строка 2898).
    2. В `get_user_prefs()`: если `prefs.get("business_context")` пуст — вызвать 
       существующую `_load_business_context_file()` и вернуть результат в поле `business_context`.
  Context: UserPrefs — Pydantic model на строке 2866. get_user_prefs() на строке 2985. 
           _load_business_context_file() уже существует на строке 4520 — читает файл, strip frontmatter.
  Depends on: нет
  Verify: PYTHONPATH=pm-bot pytest pm-bot/tests/ -k "user_pref"
  Live test: curl GET /api/v1/user-prefs → проверить наличие поля business_context
  Status: [✓] done, completed: 07.09.2026

## T-02 [opus] — Заменить _load_business_context_file() в AI-agent на чтение из prefs
  Traces to: US-01, AC-03
  File: pm-bot/app/vault_api.py
  Task:
    В функции `_build_ai_agent_messages()` (~строка 4617): заменить вызов `_load_business_context_file()`
    на чтение из `_read_user_prefs().get("business_context", "")` с fallback на `_load_business_context_file()`.
  Context: AI-agent chat endpoint POST /api/v1/ai-agent/chat. Текущий код:
           `business_context = _load_business_context_file()` на строке 4617.
  Depends on: T-01
  Verify: PYTHONPATH=pm-bot pytest pm-bot/tests/test_ai_agent_chat.py
  Live test: сохранить business_context в settings → отправить сообщение AI-агенту → проверить что контекст используется
  Status: [✓] done, completed: 07.09.2026

## T-03 [opus] — Обновить signal_orchestrator._load_business_context() — prefs через HTTP
  Traces to: US-01, AC-03, AC-04
  File: knowledge-engine/app/signal_orchestrator.py
  Task:
    В `_load_business_context()` (~строка 1100): добавить первый шаг — попытка прочитать 
    business_context из `_load_llm_prefs()` (shared/llm_client.py). Если поле непустое — 
    использовать его. Иначе — fallback на чтение из файла (текущая логика).
  Context: `_load_llm_prefs()` в shared/llm_client.py (строка 91) уже умеет GET /api/v1/user-prefs 
           с TTL-кэшем 60с и fallback на файл. Кэш per-run (self._business_context) сохраняется.
  Depends on: T-01
  Verify: PYTHONPATH=knowledge-engine pytest knowledge-engine/tests/test_signal_orchestrator.py -k "business_context"
  Live test: docker compose up → изменить business_context в settings → запустить moderate-news → проверить логи
  Status: [✓] done, completed: 07.09.2026

## T-04 [opus] — Обновить research_runner._collect_context() — prefs через HTTP
  Traces to: US-01, AC-03, AC-04
  File: knowledge-engine/app/research_runner.py
  Task:
    В `_collect_context()` (~строка 677): добавить первый шаг — попытка прочитать business_context
    из `_load_llm_prefs()`. Если непустое — использовать. Иначе — fallback на файл (текущая логика).
  Context: Аналогично T-03. `_collect_context()` — standalone функция, не метод класса.
           Import `_load_llm_prefs` из shared.llm_client.
  Depends on: T-01
  Verify: PYTHONPATH=knowledge-engine pytest knowledge-engine/tests/test_research_runner.py -k "collect_context"
  Live test: изменить business_context в settings → запустить research-run → проверить что контекст попал в промпт
  Status: [✓] done, completed: 07.09.2026

## T-05 [opus] — Секция BUSINESS CONTEXT в settings.html
  Traces to: US-01, AC-01, AC-02
  File: pm-bot/web/settings.html
  Task:
    1. Добавить секцию BUSINESS CONTEXT между AI AGENT (~строка 440) и FALLBACK CHAINS (~строка 442).
    2. Textarea с v-model="businessContext", rows="8", placeholder.
    3. Кнопка SAVE → вызов saveBusinessContext() → PUT user-prefs.
    4. Flash-уведомление при успехе/ошибке.
    5. Vue data: businessContext загружается из GET user-prefs при mount (loadPrefs).
  Context: Аналогичные секции: AI AGENT (строка 407-440), CALENDAR (строка 520).
           loadPrefs() и trySaveUserPrefs() — существующие функции для работы с user-prefs API.
  Depends on: T-01
  Verify: открыть settings.html → секция BUSINESS CONTEXT видна
  Live test: ввести текст → SAVE → перезагрузить страницу → текст сохранился
  Status: [✓] done, completed: 07.09.2026

## T-06 [opus] — CSS для textarea business_context (dual-theme)
  Traces to: US-01, AC-01
  File: pm-bot/web/style.css, pm-bot/web/style-light.css
  Task:
    Добавить стили `.bc-textarea`: monospace шрифт, width 100%, border, padding, resize vertical,
    theme-aware цвета (matrix: зелёный на тёмном, light: тёмный на кремовом).
  Context: Существующие textarea-стили в style.css и style-light.css.
           Prefix `bc-` чтобы не конфликтовать с существующими классами.
  Depends on: нет (параллельно с T-05)
  Verify: визуальная проверка в обеих темах
  Live test: переключить тему matrix ↔ light → textarea корректно стилизована
  Status: [✓] done, completed: 07.09.2026
