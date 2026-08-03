# BL-192 — Signal Chain Settings — UI настройка LLM-цепочек для News Moderator

## Phase 1 — Requirements

**Дата:** 03.08.2026
**Автор:** Team Lead
**Статус:** approved

---

## 1.1 Overview

Signal Moderator (BL-189) использует 3 группы LLM-операций: signal_triage, signal_analysis, signal_escalation. Их fallback-цепочки захардкожены как `["claude"]` и не настраиваются через Settings UI. Пользователь не может переключить их на OpenRouter. Нужно добавить настройку цепочек в Settings, аналогично существующим capture/transcription/analysis/pipeline.

## 1.2 User Stories

```
US-01: Как владелец системы, я хочу настроить fallback-цепочки для signal_triage,
       signal_analysis и signal_escalation через Settings UI,
       чтобы News Moderator использовал OpenRouter вместо Claude API.
```

## 1.3 User Flow

```
FLOW-01: Настройка цепочки
1. Пользователь открывает Settings → секция LLM PROVIDERS → FALLBACK CHAINS
2. Видит 3 новые группы: SIGNAL TRIAGE, SIGNAL ANALYSIS, SIGNAL ESCALATION
   (в дополнение к существующим CAPTURE, TRANSCRIPTION, ANALYSIS, PIPELINE)
3. Каждая группа показывает список операций (signal_score, quality_check, ...)
4. Пользователь добавляет OpenRouter первым в цепочку SIGNAL TRIAGE
5. Выбирает модель из dropdown (searchable-model-select)
6. Drag-and-drop для порядка: OpenRouter → Claude (fallback)
7. Сохранение → настройки применяются к следующему запуску moderate-news
```

## 1.4 Acceptance Criteria

```
AC-01 (US-01):
  GIVEN: Settings UI открыта
  WHEN: пользователь прокручивает до FALLBACK CHAINS
  THEN: видны 7 групп: CAPTURE, TRANSCRIPTION, ANALYSIS, PIPELINE,
        SIGNAL TRIAGE, SIGNAL ANALYSIS, SIGNAL ESCALATION
        AND каждая группа показывает свои операции

AC-02 (US-01):
  GIVEN: пользователь добавил openrouter в SIGNAL TRIAGE
  WHEN: нажимает Save
  THEN: GET /api/v1/user-prefs возвращает signal_triage_fallback
        с openrouter-шагом

AC-03 (US-01):
  GIVEN: signal_triage_fallback = ["openrouter", "claude"] в prefs
  WHEN: запускается moderate-news (signal_score operation)
  THEN: LLM-клиент использует OpenRouter первым,
        Claude как fallback

AC-04 (US-01):
  GIVEN: signal_*_fallback не настроены в prefs
  WHEN: запускается moderate-news
  THEN: используется дефолт ["openrouter", "claude"]
```

## 1.5 Out of Scope

- Изменение логики signal_orchestrator/moderator
- Новые провайдеры (только claude/ollama/openrouter)
- Изменение операций внутри групп

## 1.6 Dependencies

| Зависимость | Тип | Статус |
|---|---|---|
| BL-189 (News Moderator) | signal_* операции | ✅ |
| BL-155 (OpenRouter chains) | UI паттерн | ✅ |
