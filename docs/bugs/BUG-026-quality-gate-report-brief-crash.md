# BUG-026: quality_gate._extract_fields падает на reaction=report

**status: done**
**completed: 03.08.2026**

## Что сломано (observed)
При обработке сигнала с `reaction=report`, метод `check_analysis_quality` падает с ошибкой:
```
'NoneType' object has no attribute 'get'
```
Сигнал записывается как error, идея/отчёт не создаётся.

## Что должно быть (expected)
Для `reaction=report` метод `_extract_fields` должен извлекать поля из `report_brief` (topic, scope), а не из `idea_draft`.

## Шаги воспроизведения
1. Запустить `moderate-news` с дайджестом, содержащим новость, которую LLM оценит как `reaction=report`
2. LLM возвращает `report_brief={topic, questions, scope}`, `idea_draft=None`
3. `quality_gate._extract_fields` проверяет `"idea_draft" in analysis` → True (ключ есть, значение None)
4. Пытается `None.get("title")` → crash

## Корневая причина
`_extract_fields` (quality_gate.py:356-378) проверяет наличие ключа в dict:
```python
if "idea_draft" in analysis:          # всегда True — ключ есть в __dict__
    draft = analysis["idea_draft"]    # None для reaction=report
    title = draft.get("title", "")    # CRASH
```

`AnalysisResult.__dict__` всегда содержит оба ключа (`idea_draft`, `report_brief`) — это поля dataclass с default=None. Проверка `in` проверяет наличие ключа, а не truthiness значения.

## Файл и строка
- **Файл**: `knowledge-engine/app/quality_gate.py`
- **Метод**: `_extract_fields`, строка 356
- **Вызывается из**: `check_analysis_quality`

## Исправление
Заменить проверку наличия ключа на проверку truthiness:
```python
# Было:
if "idea_draft" in analysis:
# Стало:
if analysis.get("idea_draft"):
```
Аналогично для `report_brief` ветки.

## Severity: major
Блокирует обработку всех сигналов с reaction=report.

## Обнаружен
03.08.2026, live-тест BL-192 с llama-3.1-8b-instruct. Новость "Corporate Travel's AI Booking Advantage" получила reaction=report и упала.
