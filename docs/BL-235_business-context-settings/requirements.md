# BL-235 — Редактирование business_context через Settings UI

## 1.1 Overview

**Что:** Возможность редактировать описание бизнес-контекста компании через Settings UI вместо ручного редактирования файла в vault.

**Кто:** Продакт-менеджер (единственный пользователь системы).

**Зачем:** Бизнес-контекст (`business_context`) подставляется в 6 LLM-промптов (signal_score, signal_report_generate, signal_extract, report_to_ideas, research_report, AI-agent chat). Сейчас хранится в файле `wiki/concepts/business-context-brief.md`, который можно менять только вручную через Obsidian. Пользователь хочет редактировать его через Settings UI — быстрее, не нужно выходить из дашборда.

## 1.2 User Stories

```
US-01: Как PM, я хочу видеть и редактировать business_context в Settings,
       чтобы быстро обновлять описание бизнеса без перехода в Obsidian.
```

## 1.3 User Flows

```
FLOW-01: Редактирование business_context
1. Пользователь открывает Settings → видит секцию BUSINESS CONTEXT
2. В textarea отображается текущее содержимое business_context
   → Источник: поле business_context из user-prefs
   → Fallback: содержимое wiki/concepts/business-context-brief.md (без frontmatter)
   → Fallback: пустая строка
3. Пользователь редактирует текст → нажимает SAVE
4. Система сохраняет в user-prefs (PUT /api/v1/user-prefs)
   → SUCCESS: зелёный flash "Сохранено"
   → FAIL: красный flash с ошибкой
5. KE при следующем LLM-вызове получает обновлённый контекст
   через HTTP fallback (_load_llm_prefs → GET /api/v1/user-prefs)
```

## 1.4 Acceptance Criteria

```
AC-01 (US-01):
  GIVEN: пользователь открывает settings.html
  WHEN: страница загружается
  THEN: секция BUSINESS CONTEXT отображается с textarea
        AND textarea содержит текущее значение business_context из user-prefs
        AND если поле пустое в user-prefs — загружается из файла wiki/concepts/business-context-brief.md

AC-02 (US-01):
  GIVEN: пользователь ввёл новый текст в textarea business_context
  WHEN: нажимает кнопку SAVE
  THEN: текст сохраняется в user-prefs (поле business_context)
        AND отображается flash-уведомление об успехе

AC-03 (US-01):
  GIVEN: business_context сохранён в user-prefs
  WHEN: KE выполняет LLM-вызов (signal scoring, research report и т.д.)
  THEN: KE получает business_context из user-prefs через HTTP API
        AND подставляет его в промпт вместо чтения файла

AC-04 (US-01):
  GIVEN: business_context НЕ задан в user-prefs (пустая строка или отсутствует)
  WHEN: KE выполняет LLM-вызов
  THEN: KE читает business_context из файла wiki/concepts/business-context-brief.md (fallback)

AC-05 (US-01):
  GIVEN: пользователь открывает settings.html
  WHEN: business_context пуст в user-prefs
  THEN: GET /api/v1/user-prefs возвращает содержимое файла business-context-brief.md
        в поле business_context (seed из файла)
```

## 1.5 Out of Scope

- Предпросмотр (preview) markdown в textarea — plain text достаточно
- Валидация содержимого business_context (длина, формат) — пользователь решает сам
- Синхронизация обратно в файл `business-context-brief.md` — файл остаётся как fallback, но не обновляется из UI
- Удаление или переименование файла `business-context-brief.md`

## 1.6 Dependencies

- `PUT /api/v1/user-prefs` — существующий endpoint (vault_api.py)
- `GET /api/v1/user-prefs` — существующий endpoint (vault_api.py)
- `_load_llm_prefs()` — shared/llm_client.py (HTTP fallback для KE, BUG-036)
- `signal_orchestrator._load_business_context()` — knowledge-engine
- `research_runner._collect_context()` — knowledge-engine
- `vault_api._load_business_context_file()` — pm-bot AI-agent
