---
type: tasks
status: draft
feature: BL-203
created: 2026-08-05
total_tasks: 27
---

# Task Breakdown: Signal-First Pipeline (BL-203)

## Фаза A: Инфраструктура (нет зависимостей)

Задачи фазы A не зависят друг от друга и могут выполняться параллельно [P].

```
T-01 [P] [sonnet] — Добавить path-функции raw_signals() и wiki_signals() в vault_paths.py
  Traces to: US-01, AC-01, AC-15, AC-16
  File: shared/vault_paths.py
  Task: Добавить три новые функции после wiki_service_index() (строка 174):
    - raw_signals() -> Path: возвращает _ensure_dir(VAULT_PATH / "raw" / "inbound" / "signals")
    - wiki_signals() -> Path: возвращает _ensure_dir(VAULT_PATH / "wiki" / "reports" / "signals")
    Также добавить raw_signals в список raw_dirs в ensure_structure() (строка 226).
    Каждая функция должна иметь docstring и logger.info на входе (blocking_rules: logging).
  Context: vault_paths.py содержит 29 функций (строки 1-240), последняя ensure_structure().
    Паттерн аналогичен raw_ideas() (строка 34) и wiki_reports() (строка 95).
    Новые директории нужны для хранения Signal-артефактов: raw JSON (иммутабельные)
    и wiki Markdown (обновляемые при approve/dismiss). design.md секция 1.3.
  Depends on: none
  Verify: PYTHONPATH=shared pytest shared/ -k "vault_paths" --co (проверить что файл импортируется без ошибок)
  Live test: docker compose exec knowledge-engine python -c "from shared.vault_paths import raw_signals, wiki_signals; print(raw_signals()); print(wiki_signals())"
  Status: [✓] done
```

```
T-02 [P] [sonnet] — Добавить operation mappings signal_report_generate и signal_extract в llm_client.py
  Traces to: US-01, AC-03, AC-19
  File: shared/llm_client.py
  Task: Добавить два новых mapping в dict _OPERATION_GROUPS (строка 12):
    "signal_report_generate": "signal_analysis",
    "signal_extract": "signal_analysis",
    Разместить после существующего "signal_analyze" (строка 38).
  Context: _OPERATION_GROUPS (строки 12-44) маппит operation name на группу для выбора
    LLM-провайдера. Группа "signal_analysis" уже существует с fallback chain
    ["openrouter", "claude"] (строка 52). Новые operations используются в
    generate_analysis_report() и extract_signals() (design.md секция 6.3).
  Depends on: none
  Verify: python -c "from shared.llm_client import _OPERATION_GROUPS; assert 'signal_report_generate' in _OPERATION_GROUPS; assert 'signal_extract' in _OPERATION_GROUPS; print('OK')"
  Live test: docker compose exec knowledge-engine python -c "from shared.llm_client import _OPERATION_GROUPS; print(_OPERATION_GROUPS.get('signal_report_generate'), _OPERATION_GROUPS.get('signal_extract'))"
  Status: [✓] done
```

```
T-03 [P] [sonnet] — Создать промпт signal_report_generate.txt
  Traces to: US-01, AC-01, AC-03
  File: knowledge-engine/app/prompts/signal_report_generate.txt
  Task: Создать новый файл промпта с полным текстом из design.md секция 6.1.
    Промпт содержит плейсхолдеры: {business_context}, {competitor_profile},
    {memory_history}, {news_item}. Структура ответа: Факты, Влияние на рынок,
    Угрозы и возможности, Конкурентный контекст, Рекомендуемые действия.
    JSON-метаданные в теге <report_meta> с полем threat_level.
  Context: Заменяет signal_analyze.txt (строки 278-374 в signal_moderator.py вызывают
    текущий промпт). Новый промпт НЕ содержит выбора reaction: "idea" | "report" (AC-03).
    Результат парсится: markdown до <report_meta> -> ReportResult.content,
    JSON внутри тега -> threat_level. Существующие промпты в knowledge-engine/app/prompts/:
    signal_score.txt, signal_analyze.txt, report_to_ideas.txt, quality_check.txt и др.
  Depends on: none
  Verify: python -c "p = open('knowledge-engine/app/prompts/signal_report_generate.txt').read(); assert '{business_context}' in p; assert '{news_item}' in p; assert 'report_meta' in p; print('OK')"
  Live test: ls -la knowledge-engine/app/prompts/signal_report_generate.txt && head -5 knowledge-engine/app/prompts/signal_report_generate.txt
  Status: [✓] done
```

```
T-04 [P] [sonnet] — Создать промпт signal_extract.txt
  Traces to: US-01, AC-19
  File: knowledge-engine/app/prompts/signal_extract.txt
  Task: Создать новый файл промпта с полным текстом из design.md секция 6.2.
    Промпт содержит плейсхолдеры: {business_context}, {report_content}.
    Ожидаемый ответ: JSON с массивом signals[], каждый элемент содержит:
    title, analysis, threat_level, recommended_action, draft_idea (object|null),
    domain, priority_hint, rationale. Поле no_signals_reason если сигналов нет.
  Context: Адаптация report_to_ideas.txt для новой схемы Signal.
    extract_signals() (design.md секция 1.3) будет загружать этот промпт
    и отправлять LLM с operation="signal_extract". Результат парсится в list[SignalData].
  Depends on: none
  Verify: python -c "p = open('knowledge-engine/app/prompts/signal_extract.txt').read(); assert '{business_context}' in p; assert '{report_content}' in p; assert 'signals' in p; print('OK')"
  Live test: ls -la knowledge-engine/app/prompts/signal_extract.txt && wc -l knowledge-engine/app/prompts/signal_extract.txt
  Status: [✓] done
```

---

## Фаза B: Ядро pipeline (зависит от Фазы A)

```
T-05 [sonnet] — Добавить dataclasses ReportResult и SignalData в signal_moderator.py
  Traces to: US-01, AC-01, AC-02, AC-19
  File: knowledge-engine/app/signal_moderator.py
  Task: Добавить два новых dataclass после существующего AnalysisResult (строка 31):
    1. ReportResult: content (str), threat_level (str), _quality_warning (bool=False), _attempts (int=1)
    2. SignalData: title (str), analysis (str), threat_level (str), recommended_action (str),
       draft_idea (dict|None), domain (str="general"), priority_hint (str="medium"), rationale (str="")
    Точная спецификация в design.md секция 1.3. AnalysisResult пока НЕ удалять --
    он используется в dispatch_idea() и research_runner до фаз C-D.
  Context: AnalysisResult (строки 31-39) используется в analyze_signal(), dispatch_idea(),
    dispatch_report(), _handle_idea(), _handle_report(). Новые dataclasses заменят его
    в новом pipeline. ReportResult хранит результат генерации отчёта (markdown + threat_level).
    SignalData хранит один извлечённый сигнал с полями по AC-02 (13 полей).
  Depends on: T-01, T-02, T-03, T-04 (Фаза A)
  Verify: PYTHONPATH=knowledge-engine pytest knowledge-engine/tests/test_signal_moderator.py --co
  Live test: docker compose exec knowledge-engine python -c "from app.signal_moderator import ReportResult, SignalData; r = ReportResult(content='test', threat_level='medium'); s = SignalData(title='t', analysis='a', threat_level='low', recommended_action='r', draft_idea=None); print(r, s)"
  Status: [✓] done
```

```
T-06 [opus] — Реализовать generate_analysis_report() в signal_moderator.py
  Traces to: US-01, AC-01, AC-03
  File: knowledge-engine/app/signal_moderator.py
  Task: Создать публичную функцию generate_analysis_report() со следующей сигнатурой
    (design.md секция 1.3):
    - Параметры: item (dict), scoring (ScoringResult), business_context (str),
      competitor_profile (str|None), memory_history (str), config (Any),
      critique (str|None=None), operation_group (str|None=None)
    - Возвращает: ReportResult
    Логика:
    1. Загрузить промпт signal_report_generate.txt (через _prompt_cache, строка 18)
    2. Подставить плейсхолдеры: business_context, competitor_profile, memory_history,
       news_item (форматированный из item dict)
    3. Вызвать call_detailed(operation="signal_report_generate", max_tokens=4000)
    4. Распарсить ответ: markdown до <report_meta> -> content, JSON из тега -> threat_level
    5. Fallback если тег не найден: threat_level="medium"
    6. Вернуть ReportResult(content=..., threat_level=...)
    7. Логирование: на входе (параметры), на успехе (длина content, threat_level), на ошибке
    Также добавить приватную _build_report_prompt() для форматирования промпта.
  Context: Заменяет analyze_signal() (строки 278-374). Ключевое отличие: analyze_signal
    возвращал AnalysisResult с reaction="idea"|"report", а generate_analysis_report
    возвращает ReportResult с полным markdown-отчётом. Вызов LLM через call_detailed()
    из shared/llm_client.py (строка 10 -- import). AgentLoop/QualityGate НЕ здесь --
    они в _process_item() orchestrator'а.
    design.md секции 1.3, 3.1, 6.1.
  Depends on: T-03, T-05
  Verify: PYTHONPATH=knowledge-engine pytest knowledge-engine/tests/test_signal_moderator.py -k "test_generate_analysis_report" -v
  Live test: docker compose exec knowledge-engine python -c "
from app.signal_moderator import generate_analysis_report, ScoringResult
# Проверка что функция импортируется и принимает правильные параметры
import inspect; sig = inspect.signature(generate_analysis_report); print(sig)
"
  Status: [✓] done
```

```
T-07 [opus] — Реализовать extract_signals() в signal_moderator.py
  Traces to: US-01, AC-19
  File: knowledge-engine/app/signal_moderator.py
  Task: Создать публичную функцию extract_signals() со следующей сигнатурой
    (design.md секция 1.3):
    - Параметры: report_path (Path), vault_path (str), business_context (str), config (Any)
    - Возвращает: list[SignalData]
    Логика:
    1. Прочитать report_path (markdown отчёта)
    2. Загрузить промпт signal_extract.txt
    3. Подставить плейсхолдеры: business_context, report_content
    4. Вызвать call_detailed(operation="signal_extract", max_tokens=4000)
    5. Распарсить JSON-ответ: массив signals[] -> list[SignalData]
    6. Для каждого сигнала: валидировать обязательные поля (title, analysis, threat_level, recommended_action)
    7. Если signals пуст -- логировать no_signals_reason, вернуть []
    8. Dedup check: вызвать quality_gate.check_dedup() для каждого draft_idea (если не null)
    9. Отфильтровать дубликаты
    10. Логирование: на входе, количество извлечённых, количество после dedup, на ошибке
  Context: Аналог extract_ideas_full() из idea_extractor.py (строки 82-146), но с другой
    схемой ответа (SignalData вместо dict с idea-полями). Промпт signal_extract.txt (T-04)
    запрашивает другой набор полей. design.md секции 1.3, 3.2, 6.2.
    Edge case из design.md секция 4.4: пустой список -> логировать, НЕ блокировать pipeline.
  Depends on: T-04, T-05
  Verify: PYTHONPATH=knowledge-engine pytest knowledge-engine/tests/test_signal_moderator.py -k "test_extract_signals" -v
  Live test: docker compose exec knowledge-engine python -c "
from app.signal_moderator import extract_signals
import inspect; sig = inspect.signature(extract_signals); print(sig)
"
  Status: [✓] done
```

```
T-08 [opus] — Реализовать dispatch_signal() в signal_moderator.py
  Traces to: US-01, AC-01, AC-02, AC-15, AC-16
  File: knowledge-engine/app/signal_moderator.py
  Task: Создать публичную функцию dispatch_signal() со следующей сигнатурой
    (design.md секция 1.3):
    - Параметры: signal_data (SignalData), report_ref (str), item (dict),
      scoring (ScoringResult), vault_path (str), run_id (str), dry_run (bool=False)
    - Возвращает: str|None (signal_id -- имя файла без расширения)
    Логика:
    1. Генерация slug: транслитерация title (до 50 символов), дефисы вместо спецсимволов,
       lowercase (design.md секция 2.1)
    2. Формирование signal_id: "{YYYY-MM-DD}-{slug}" (AC-15)
    3. Если dry_run -- логировать, вернуть signal_id без записи (design.md секция 4.7)
    4. Создать raw JSON: raw/inbound/signals/{signal_id}.json с 13 полями по AC-02:
       title, source_url, source, relevance_score, analysis, threat_level,
       recommended_action, draft_idea, signal_date, run_id, status="pending",
       report_ref, created_at
    5. Создать wiki Markdown: wiki/reports/signals/{signal_id}.md с frontmatter (AC-16)
       и body секциями: Анализ, Рекомендация, Черновик идеи (если есть)
    6. Использовать vault_paths.raw_signals() и vault_paths.wiki_signals() для путей
    7. Логирование: на входе (signal_id, title), на успехе (оба файла записаны), на ошибке
  Context: Аналог dispatch_idea() (строки 741-877) по паттерну (raw файл + wiki копия),
    но для Signal-артефактов. Ключевое отличие: raw = JSON (не markdown), wiki = markdown с
    frontmatter type: signal. Raw файл иммутабелен (C-0002 -- design.md секция 4.2).
    Slug генерация аналогична dispatch_report() (строка 900-901).
    design.md секции 1.3, 2.1, 2.2, 4.7.
  Depends on: T-01, T-05
  Verify: PYTHONPATH=knowledge-engine pytest knowledge-engine/tests/test_signal_moderator.py -k "test_dispatch_signal" -v
  Live test: docker compose exec knowledge-engine python -c "
from app.signal_moderator import dispatch_signal, SignalData, ScoringResult
# Dry run тест -- не создаёт файлов
sd = SignalData(title='Test signal', analysis='Test analysis', threat_level='medium', recommended_action='Test', draft_idea=None)
sc = ScoringResult(relevance=8, reason='test')
result = dispatch_signal(sd, 'test-report.md', {'title': 'test', 'date': '2026-08-05', 'source_url': 'http://test.com', 'source': 'Test'}, sc, '/vault', 'test-run', dry_run=True)
print(f'signal_id={result}')
"
  Status: [✓] done
```

```
T-09 [opus] — Рефакторинг _process_item() в signal_orchestrator.py (убрать бифуркацию idea/report)
  Traces to: US-01, AC-01, AC-03, AC-04
  File: knowledge-engine/app/signal_orchestrator.py
  Task: Переписать _process_item() (строки 403-672) для нового pipeline без бифуркации:
    Текущий flow: score -> analyze_signal -> reaction=="idea" ? _handle_idea : _handle_report
    Новый flow: score -> generate_analysis_report (AgentLoop + QualityGate) -> записать отчёт ->
      extract_signals -> dedup -> dispatch_signal (для каждого сигнала) -> signal_memory
    Конкретные изменения:
    1. Заменить вызов analyze_signal() на generate_analysis_report()
    2. Сохранить AgentLoop паттерн (цикл с critique из quality_gate), адаптировать для ReportResult
    3. Записать отчёт в wiki/reports/signals/{date}-{slug}-report.md
    4. Вызвать extract_signals() на записанном отчёте
    5. Для каждого SignalData вызвать dispatch_signal()
    6. Обновить signal_memory.record_signal(): reaction="signal", result_ref=signal_id
    7. Убрать вызовы _handle_idea() и _handle_report() (они будут удалены в фазе C)
    8. Обновить RunSummary: ideas -> signals (design.md секция 5.1)
    9. Обновить Langfuse spans: analyze -> report, добавить extract-signals, dedup (design.md секция 5.5)
    10. Логирование каждого шага: report generated, signals extracted, signal dispatched
  Context: _process_item() (строки 403-672) -- центральный метод pipeline. Содержит:
    скоринг (score_signal), AgentLoop для анализа, quality gates, dispatch.
    Бифуркация на idea/report происходит в строках ~630-672 через analysis.reaction.
    _handle_idea() (строки 678-740) и _handle_report() (строки 746-767) вызываются
    по результату reaction. В новом pipeline reaction не существует -- всегда signal.
    design.md секции 1.1, 1.2, 5.1, 5.5.
    Edge case: extract_signals вернул [] -> reaction="no_signals" в signal_memory (design.md 4.4).
    Edge case: отчёт не прошёл QualityGate -> продолжить с лучшим результатом (design.md 4.5).
  Depends on: T-05, T-06, T-07, T-08
  Verify: PYTHONPATH=knowledge-engine pytest knowledge-engine/tests/test_signal_orchestrator.py -v
  Live test: docker compose exec knowledge-engine python -c "
from app.signal_orchestrator import SignalOrchestrator
import inspect; members = [m for m in dir(SignalOrchestrator) if not m.startswith('__')]
print('Methods:', members)
"
  Status: [✓] done
```

```
T-10 [sonnet] — Добавить _load_relevance_threshold() в signal_orchestrator.py
  Traces to: US-03, AC-09, AC-10
  File: knowledge-engine/app/signal_orchestrator.py
  Task: Добавить приватный метод _load_relevance_threshold(self) -> int
    в класс SignalOrchestrator. Логика (design.md секция 5.3):
    1. Прочитать Path(self.vault_path) / ".pm-user-prefs.json"
    2. Если файл существует: json.loads -> moderator.relevance_threshold
    3. Валидация: int(), clamp max(1, min(10, val))
    4. Если ключ отсутствует или файл не существует: fallback self.config.relevance_threshold
    5. Логирование: источник значения (user-prefs или config), значение
    Вызвать в начале process_digest() вместо прямого self.config.relevance_threshold.
    Обновить threshold в _process_item() где сравнивается relevance с порогом.
  Context: Текущий threshold берётся из self.config.relevance_threshold (settings.yaml).
    user-prefs (vault/.pm-user-prefs.json) имеет приоритет. Ключ moderator.relevance_threshold
    записывается через settings.html (T-21). Код _load_relevance_threshold полностью
    приведён в design.md секция 5.3 (строки 713-728).
    vault_paths.user_prefs_path() (строка 161 в vault_paths.py) уже существует.
  Depends on: T-05
  Verify: PYTHONPATH=knowledge-engine pytest knowledge-engine/tests/test_signal_orchestrator.py -k "threshold" -v
  Live test: docker compose exec knowledge-engine python -c "
from app.signal_orchestrator import SignalOrchestrator
print(hasattr(SignalOrchestrator, '_load_relevance_threshold'))
"
  Status: [✓] done
```

---

## Фаза C: API и откат BL-202 (зависит от Фазы B)

```
T-11 [opus] — Добавить 4 новых Signal endpoints в vault_api.py
  Traces to: US-02, US-04, AC-05, AC-06, AC-07, AC-08, AC-11, AC-17, AC-18
  File: pm-bot/app/vault_api.py
  Task: Добавить 4 новых endpoint'а для Signal-артефактов (design.md секция 2.4):
    1. GET /api/v1/signals/list?status=pending&date=YYYY-MM-DD&limit=50
       - Сканирует wiki/reports/signals/*.md (исключая *-report.md)
       - Читает frontmatter через read_frontmatter()
       - Фильтрует по status и signal_date
       - Сортирует по дате (новые первые)
       - Возвращает {signals: [...], total: N}
    2. GET /api/v1/signals/{signal_id}
       - Ищет wiki/reports/signals/{signal_id}.md
       - Читает frontmatter + body (парсит секции Анализ, Рекомендация)
       - draft_idea читается из raw JSON (raw/inbound/signals/{signal_id}.json)
       - 404 если не найден
    3. POST /api/v1/signals/{signal_id}/approve
       - Валидация signal_id (_validate_signal_id -- design.md 4.1)
       - Проверка status=="pending", иначе 409
       - Читает draft_idea из raw JSON, 400 если null
       - Вызывает dispatch_idea() с данными draft_idea
       - Обновляет wiki frontmatter: status="approved", result_ref=IDEA filename
       - Threading lock для concurrent safety (design.md 4.3)
       - Invalidate cache
       - Возвращает {status: "ok", signal_id, idea_ref, new_status: "approved"}
    4. POST /api/v1/signals/{signal_id}/dismiss
       - Валидация signal_id
       - Проверка status=="pending", иначе 409
       - Обновляет wiki frontmatter: status="dismissed"
       - Raw JSON НЕ модифицируется (C-0002)
       - Invalidate cache
       - Возвращает {status: "ok", signal_id, new_status: "dismissed"}
    Также добавить helper _validate_signal_id() (design.md 4.1).
    Также добавить _signal_approve_lock = threading.Lock() на уровне модуля (design.md 4.3).
    Каждый endpoint: логирование на входе, успехе, ошибке.
  Context: Новые endpoints заменяют BL-202 endpoints (строки 4946-5153) для IDEA со статусом
    "Сигнал". Работают с Signal-артефактами (raw/inbound/signals/, wiki/reports/signals/).
    Используют vault_paths.raw_signals() и vault_paths.wiki_signals() (T-01).
    approve вызывает dispatch_idea() из signal_moderator.py (строки 741-877) --
    функция остаётся, но из неё удаляется BL-202 код (T-14).
    Размещение: перед существующим блоком "Signal Idea Triage" (строка 4897).
    design.md секции 2.4, 4.1, 4.2, 4.3.
  Depends on: T-01, T-08, T-09
  Verify: PYTHONPATH=pm-bot:knowledge-engine pytest pm-bot/tests/ -k "signal" -v
  Live test: |
    # После Docker rebuild:
    # 1. Список сигналов
    curl -s http://192.168.0.6:8000/api/v1/signals/list?status=pending | python -m json.tool
    # 2. Деталь (заменить signal_id на реальный)
    curl -s http://192.168.0.6:8000/api/v1/signals/test-signal-id | python -m json.tool
    # 3. Approve (если есть pending-сигнал)
    curl -s -X POST http://192.168.0.6:8000/api/v1/signals/test-signal-id/approve | python -m json.tool
    # 4. Dismiss
    curl -s -X POST http://192.168.0.6:8000/api/v1/signals/test-signal-id/dismiss | python -m json.tool
  Status: [✓] done
```

```
T-12 [sonnet] — Удалить BL-202 endpoints и helper _find_wiki_idea_by_signal_ref() из vault_api.py
  Traces to: US-01, AC-13, AC-14
  File: pm-bot/app/vault_api.py
  Task: Удалить весь блок "Signal Idea Triage: approve / dismiss (BL-202)" (строки 4897-5153):
    1. Удалить _find_wiki_idea_by_signal_ref() (строки 4902-4943)
    2. Удалить get_signal_idea() endpoint (строки 4946-4971)
    3. Удалить approve_signal_idea() endpoint (строки 4974-5074)
    4. Удалить dismiss_signal_idea() endpoint (строки 5077-5153)
    Эти endpoints заменены новыми Signal endpoints из T-11.
  Context: BL-202 endpoints работали с IDEA-файлами, у которых status="Сигнал".
    В новой архитектуре Signal -- отдельный тип артефакта, не связанный с IDEA.
    _find_wiki_idea_by_signal_ref() сканировала wiki/domains/*/ideas/IDEA-*.md по
    frontmatter signal_ref. Новые endpoints (T-11) работают напрямую с
    wiki/reports/signals/{signal_id}.md. design.md секция 3.4.
  Depends on: T-11
  Verify: PYTHONPATH=pm-bot:knowledge-engine python -c "import pm-bot.app.vault_api" (проверить что нет import errors)
  Live test: |
    # Убедиться что старые endpoints возвращают 404:
    curl -s -o /dev/null -w "%{http_code}" http://192.168.0.6:8000/api/v1/signals/ideas/test.md
    # Ожидаемый ответ: 404 или 405
  Status: [✓] done
```

```
T-13 [sonnet] — Удалить "Сигнал" из _VALID_IDEA_STATUSES и убрать фильтрацию в board/overview
  Traces to: US-01, AC-13, AC-14
  File: pm-bot/app/vault_api.py
  Task: Три точечных изменения:
    1. Удалить "Сигнал" из frozenset _VALID_IDEA_STATUSES (строка 211-213):
       убрать строку '    "Сигнал",              # BL-202: signal-идея ожидает triage'
    2. Удалить блок фильтрации из board endpoint (строки 1008-1012):
       удалить строки `# BL-202: signal-идеи не показываются на board`,
       `idea_status = note.get("status", "Новая")`, `if idea_status == "Сигнал": skipped_signal += 1; continue`
       (и связанную переменную skipped_signal если только для этого использовалась)
    3. Удалить блок фильтрации из overview endpoint (строки 3847-3849):
       удалить строки `# BL-202: signal-идеи не попадают в overview queue`,
       `if status == "Сигнал": continue`
  Context: BL-202 добавила "Сигнал" как валидный статус IDEA и фильтровала такие идеи
    из board и overview. В BL-203 сигналы -- отдельный тип артефакта, "Сигнал" больше
    не является валидным статусом IDEA. Фильтрация не нужна -- IDEA со статусом "Сигнал"
    будут мигрированы в "Отсев" в T-25. design.md секция 3.4.
  Depends on: T-11
  Verify: PYTHONPATH=pm-bot:knowledge-engine python -c "
from pm_bot_stub import _VALID_IDEA_STATUSES  # или через grep
" && grep -n "Сигнал" pm-bot/app/vault_api.py  # должно быть 0 результатов
  Live test: |
    # Проверить board endpoint -- не должно быть фильтрации по "Сигнал":
    curl -s http://192.168.0.6:8000/api/v1/board | python -m json.tool | head -20
    # Проверить overview -- аналогично:
    curl -s http://192.168.0.6:8000/api/v1/overview | python -m json.tool | head -20
  Status: [✓] done
```

```
T-14 [sonnet] — Удалить BL-202 вызов _create_wiki_signal_idea() из dispatch_idea()
  Traces to: US-01, AC-04
  File: knowledge-engine/app/signal_moderator.py
  Task: В функции dispatch_idea() (строки 741-877) удалить блок BL-202 (строки 829-842):
    Удалить:
    - Комментарий `# === BL-202: создание wiki-копии со статусом "Сигнал" ===`
    - Переменную `wiki_ref = None`
    - Блок try/except с вызовом _create_wiki_signal_idea()
    - Все ссылки на wiki_ref в последующем коде (если есть в логировании/возврате)
    dispatch_idea() должен продолжать создавать только raw IDEA .md файл и отправлять
    Telegram-уведомление (существующая логика). Wiki-копия IDEA при approve будет
    создаваться через стандартный enrich flow (существующий механизм из vault_api approve).
  Context: dispatch_idea() (строки 741-877) после рефакторинга вызывается ТОЛЬКО из
    vault_api.py approve endpoint (T-11), когда PM одобряет сигнал.
    _create_wiki_signal_idea() (строки 500-650) создавала wiki IDEA со статусом "Сигнал" --
    это поведение больше не нужно. Функция удаляется в T-15.
    design.md секция 3.4 пункт 7.
  Depends on: T-11
  Verify: PYTHONPATH=knowledge-engine pytest knowledge-engine/tests/test_signal_moderator.py -k "dispatch_idea" -v
  Live test: docker compose exec knowledge-engine python -c "
from app.signal_moderator import dispatch_idea
import inspect; src = inspect.getsource(dispatch_idea)
assert '_create_wiki_signal_idea' not in src, 'BL-202 code still present'
print('OK: no BL-202 references in dispatch_idea')
"
  Status: [✓] done
```

```
T-15 [sonnet] — Удалить BL-202 helper functions из signal_moderator.py
  Traces to: US-01, AC-04, AC-13
  File: knowledge-engine/app/signal_moderator.py
  Task: Удалить весь блок "Wiki signal idea helpers (BL-202)" (строки 377-734):
    1. Удалить _IDEA_NUM_PATTERN (строка 381)
    2. Удалить _max_idea_number() (строки 384-413)
    3. Удалить _load_idea_template() (~строки 415-450)
    4. Удалить _build_signal_idea_content() (~строки 452-498)
    5. Удалить _fill_template_for_signal() (~строки 500-550)
    6. Удалить _create_wiki_signal_idea() (~строки 552-650)
    7. Удалить _update_wiki_index() (~строки 652-734)
    Эти функции создавали IDEA-файл со статусом "Сигнал" в wiki/domains -- логика,
    заменённая Signal-артефактами. dispatch_idea() (строки 741+) использует obsidian_writer
    для создания IDEA, _max_idea_number не нужен.
  Context: Все 7 функций были добавлены в BL-202 для создания wiki IDEA со статусом "Сигнал".
    В BL-203 dispatch_signal() (T-08) создаёт Signal-артефакт, а dispatch_idea() вызывается
    только при approve. _max_idea_number() может понадобиться для dispatch_idea() -- проверить,
    используется ли она в dispatch_idea() после удаления BL-202 блока (T-14).
    Если используется -- не удалять, а перенести.
    design.md секция 1.4 (таблица удаляемого кода).
  Depends on: T-14
  Verify: PYTHONPATH=knowledge-engine python -c "from app.signal_moderator import dispatch_idea, dispatch_signal; print('OK')"
  Live test: docker compose exec knowledge-engine python -c "
import app.signal_moderator as sm
bl202_funcs = ['_create_wiki_signal_idea', '_build_signal_idea_content', '_fill_template_for_signal', '_update_wiki_index', '_load_idea_template']
for fn in bl202_funcs:
    assert not hasattr(sm, fn), f'BL-202 function {fn} still exists'
print('OK: all BL-202 helpers removed')
"
  Status: [✓] done
```

---

## Фаза D: Research runner адаптация (зависит от Фазы B)

```
T-16 [opus] — Адаптировать _extract_and_classify() в research_runner.py для dispatch_signal()
  Traces to: US-05, AC-12
  File: knowledge-engine/app/research_runner.py
  Task: Рефакторинг _extract_and_classify() (строки 463-575):
    1. Заменить import: dispatch_idea, AnalysisResult -> dispatch_signal, extract_signals, SignalData
       из app.signal_moderator
    2. Заменить вызов extract_ideas_full() (строка 501) на extract_signals()
       (передать report_path, vault_path, business_context, config)
    3. Заменить цикл dispatch_idea() (строки 517-537) на цикл dispatch_signal():
       для каждого SignalData вызвать dispatch_signal() с параметрами:
       - signal_data=signal
       - report_ref=report_path.name
       - item={"title": task.topic, "date": date.today().isoformat(), "source": "research-report"}
       - scoring=ScoringResult(relevance=0, reason="from research")
       - vault_path=vault_path
       - run_id=f"research-{date.today().isoformat()}"
    4. Обновить frontmatter: ideas_count -> signals_count, ideas_refs -> signal_refs (строки 540-545)
    5. Обновить _update_processed_json аналогично (строки 549-554)
    6. Outcome classification: "idea" -> "signal" (строка 510)
    7. Логирование: каждый dispatched signal
  Context: _extract_and_classify() (строки 463-575) извлекает идеи из research-отчёта
    и создаёт IDEA-файлы. В BL-203 вместо идей создаются сигналы (AC-12: "тем же механизмом").
    extract_ideas_full() из idea_extractor.py остаётся для backward compat, но не используется
    в новом pipeline. design.md секция 5.4.
    Signal содержит source: "research-report", report_ref: report_filename (AC-12).
  Depends on: T-07, T-08
  Verify: PYTHONPATH=knowledge-engine pytest knowledge-engine/tests/test_research_runner.py -k "_extract_and_classify" -v
  Live test: docker compose exec knowledge-engine python -c "
from app.research_runner import _extract_and_classify
import inspect; src = inspect.getsource(_extract_and_classify)
assert 'dispatch_signal' in src, 'dispatch_signal not found'
assert 'dispatch_idea' not in src, 'dispatch_idea still present'
print('OK: research_runner uses dispatch_signal')
"
  Status: [✓] done
```

---

## Фаза E: Frontend (зависит от Фазы C)

```
T-17 [sonnet] — Добавить новые методы Signal API в api.js
  Traces to: US-02, AC-05, AC-06, AC-07, AC-17
  File: pm-bot/web/api.js
  Task: Добавить 5 новых методов в объект api (после существующего signalRunDetail, строка ~583):
    1. signalsList(params) -- GET /api/v1/signals/list?status=X&date=Y&limit=Z
    2. signalDetail(signalId) -- GET /api/v1/signals/{signalId}
    3. signalApprove(signalId) -- POST /api/v1/signals/{signalId}/approve
    4. signalDismiss(signalId) -- POST /api/v1/signals/{signalId}/dismiss
    5. updateRelevanceThreshold(value) -- PUT /api/v1/user-prefs (используя существующий
       endpoint updateUserPrefs с {moderator: {relevance_threshold: value}})
    Сохранить существующие signalRuns() и signalRunDetail() (используются в research.html).
    Удалить signalIdeaDetail(), signalIdeaApprove(), signalIdeaDismiss() (строки 585-604) --
    BL-202 endpoints удалены в T-12.
  Context: api.js (строки 575-604) содержит BL-202 методы: signalRuns, signalRunDetail,
    signalIdeaDetail, signalIdeaApprove, signalIdeaDismiss. signalRuns и signalRunDetail
    остаются (используются в research.html для отображения run history).
    Новые методы будут использоваться в today.html (T-18) и settings.html (T-19).
    design.md секция 5.2. Паттерн вызова: apiFetch() (существующий helper).
  Depends on: T-11, T-12
  Verify: grep -c "signalsList\|signalDetail\|signalApprove\|signalDismiss" pm-bot/web/api.js  # должно быть >= 4
  Live test: Открыть http://192.168.0.6:8080/ в браузере -> DevTools Console -> api.signalsList({status:'pending'}).then(console.log)
  Status: [✓] done
```

```
T-18 [opus] — Адаптировать today.html для Signal triage UI
  Traces to: US-02, US-04, AC-05, AC-06, AC-07, AC-08, AC-11
  File: pm-bot/web/today.html, pm-bot/web/style-today.css
  Task: Одна задача на страницу (правило delegation_rules: "Frontend с макетом").
    Адаптировать существующую Signal triage секцию в today.html для работы с новыми
    Signal-артефактами вместо IDEA со статусом "Сигнал". Изменения:
    1. Заменить loadSignalRuns() -> loadSignals():
       - Вызов api.signalsList({date: todayDate}) вместо api.signalRuns()
       - Данные: массив Signal-объектов вместо run items
    2. Убрать buildSignalMap() (строки 518-530) -- не нужен, сигналы приходят напрямую
    3. Секция "Сигналы" с группировкой по статусам (AC-11):
       - pending (сверху) -- карточки с кнопками [Approve] [Dismiss]
       - approved -- карточки без кнопок, с ссылкой на IDEA (result_ref)
       - dismissed -- карточки серым цветом, без кнопок
    4. Карточка сигнала (AC-05): title, source, relevance_score (бейдж), threat_level (цвет)
    5. Drawer/модал с деталями сигнала (FLOW-02 шаг 2):
       - Заголовок, источник, relevance_score
       - Блок "Анализ", "Рекомендация", "Черновик идеи"
       - Кнопки [Approve] и [Dismiss]
       - Загружается через api.signalDetail(signalId)
    6. Approve handler: api.signalApprove(signalId) -> toast + обновить карточку (AC-06)
    7. Dismiss handler: api.signalDismiss(signalId) -> toast + обновить карточку (AC-07)
    8. Обработка 409 Conflict (повторный approve/dismiss) -> toast с сообщением
    9. style-today.css: стили для Signal triage карточек, группировка, dismissed=серый
    Переиспользовать UI-концепцию бейджей из BL-202 (цветовая индикация на карточках).
  Context: today.html содержит существующую BL-202 Signal triage логику (строки 321-323
    signalRuns/signalMap, строки 510-530 loadSignalRuns/buildSignalMap, строки 1206-1219
    approve/dismiss handlers). Концепция бейджей и карточек сохраняется, но данные
    приходят из новых API endpoints (T-11). design.md секция 5.2.
    Контракт данных для агента:
    - GET /api/v1/signals/list ответ: {signals: [{signal_id, title, source, source_url,
      relevance_score, threat_level, status, signal_date, has_draft_idea, report_ref,
      result_ref, created}], total: N}
    - GET /api/v1/signals/{id} ответ: то же + analysis, recommended_action, draft_idea
    - POST approve ответ: {status: "ok", signal_id, idea_ref, new_status: "approved"}
    - POST dismiss ответ: {status: "ok", signal_id, new_status: "dismissed"}
  Depends on: T-11, T-17
  Verify: Открыть http://192.168.0.6:8080/today.html в браузере, проверить отсутствие JS-ошибок в console
  Live test: |
    # 1. Открыть today.html, убедиться что секция "Сигналы" загружается
    # 2. Если есть pending-сигналы: кликнуть на карточку -> проверить drawer с деталями
    # 3. Нажать Approve -> проверить toast + карточка без кнопок
    # 4. Обновить страницу -> approved-сигнал показан в секции "Одобренные"
    curl -s http://192.168.0.6:8080/today.html | head -5  # проверить что страница отдаётся
  Status: [✓] done
```

```
T-19 [sonnet] — Добавить relevance threshold slider в settings.html
  Traces to: US-03, AC-09, AC-10
  File: pm-bot/web/settings.html
  Task: Добавить секцию "Signal Moderator" в settings.html:
    1. HTML: секция с заголовком "Signal Moderator" содержит:
       - Label "Порог скоринга сигналов"
       - Slider (input type="range") или number input, range 1-10, step 1
       - Отображение текущего значения рядом со slider
    2. Vue data: relevanceThreshold (загружается из user-prefs при mounted)
    3. Load: при mounted вызвать api.getUserPrefs() -> moderator.relevance_threshold (default 7)
    4. Save: при изменении значения (blur или кнопка "Сохранить"):
       - Вызвать api.updateUserPrefs({moderator: {relevance_threshold: value}})
       - Toast "Настройки сохранены"
    5. Валидация на клиенте: значение вне 1-10 -> не отправлять
  Context: settings.html уже содержит секции для theme, refresh_mode и др.
    Используется существующий endpoint PUT /api/v1/user-prefs для записи.
    Endpoint GET /api/v1/user-prefs для чтения тоже существует.
    User-prefs хранятся в vault/.pm-user-prefs.json.
    Orchestrator читает threshold из user-prefs с приоритетом (T-10).
    design.md секция 5.3.
  Depends on: T-17
  Verify: grep -c "relevanceThreshold\|relevance_threshold" pm-bot/web/settings.html  # >= 2
  Live test: |
    # 1. Открыть http://192.168.0.6:8080/settings.html
    # 2. Найти секцию "Signal Moderator"
    # 3. Изменить slider на 5 -> Сохранить
    # 4. Проверить:
    curl -s http://192.168.0.6:8000/api/v1/user-prefs | python -m json.tool | grep relevance_threshold
    # Ожидается: "relevance_threshold": 5
  Status: [✓] done
```

---

## Фаза F: Тесты и миграция (зависит от Фаз B, C, D)

```
T-20 [P] [sonnet] — Адаптировать test_signal_moderator.py для нового pipeline
  Traces to: US-01, AC-01, AC-02, AC-03, AC-04, AC-15, AC-16, AC-19
  File: knowledge-engine/tests/test_signal_moderator.py
  Task: Обновить существующие тесты и добавить новые:
    1. Удалить/адаптировать тесты analyze_signal() -> заменить на тесты generate_analysis_report():
       - test_generate_analysis_report_success: mock call_detailed -> markdown + <report_meta>
       - test_generate_analysis_report_no_meta_tag: fallback threat_level="medium"
       - test_generate_analysis_report_llm_error: проверить обработку ошибок
    2. Добавить тесты extract_signals():
       - test_extract_signals_success: mock call_detailed -> JSON с 2 сигналами
       - test_extract_signals_empty: LLM вернул {signals: [], no_signals_reason: "..."}
       - test_extract_signals_invalid_json: проверить обработку невалидного JSON
       - test_extract_signals_dedup: один из сигналов -- дубликат
    3. Добавить тесты dispatch_signal():
       - test_dispatch_signal_creates_raw_and_wiki: проверить создание обоих файлов
       - test_dispatch_signal_json_schema (AC-02): проверить 13 полей в raw JSON
       - test_dispatch_signal_wiki_frontmatter (AC-16): проверить frontmatter формат
       - test_dispatch_signal_slug_generation (AC-15): проверить формат имени файла
       - test_dispatch_signal_dry_run: файлы НЕ создаются
    4. Адаптировать тесты dispatch_idea(): убрать проверки _create_wiki_signal_idea
    5. Удалить тесты BL-202 helper functions (если есть)
    Использовать tmp_path fixture для файловых операций.
  Context: Существующие тесты покрывают analyze_signal, dispatch_idea, dispatch_report,
    BL-202 helpers. После рефакторинга ядра (T-06, T-07, T-08) и удаления BL-202 (T-14, T-15)
    тесты должны быть обновлены. Паттерн тестирования: mock call_detailed через monkeypatch.
  Depends on: T-06, T-07, T-08, T-14, T-15
  Verify: PYTHONPATH=knowledge-engine pytest knowledge-engine/tests/test_signal_moderator.py -v
  Live test: docker compose exec knowledge-engine sh -c "PYTHONPATH=. pytest tests/test_signal_moderator.py -v --tb=short"
  Status: [✓] done
```

```
T-21 [P] [sonnet] — Адаптировать test_signal_orchestrator.py для нового pipeline
  Traces to: US-01, US-03, AC-01, AC-03, AC-09, AC-10
  File: knowledge-engine/tests/test_signal_orchestrator.py
  Task: Обновить существующие тесты:
    1. Адаптировать тесты _process_item():
       - Заменить mock analyze_signal -> mock generate_analysis_report + extract_signals
       - Заменить проверки _handle_idea/_handle_report -> проверки dispatch_signal
       - Проверить что signal_memory.record_signal вызывается с reaction="signal"
    2. Удалить тесты _handle_idea() и _handle_report() (методы удалены)
    3. Добавить тест _load_relevance_threshold():
       - test_threshold_from_user_prefs: prefs файл существует с moderator.relevance_threshold=5
       - test_threshold_fallback_to_config: prefs файл не существует
       - test_threshold_invalid_value: значение вне range -> clamp
    4. Адаптировать тесты process_digest() для нового flow
    5. Проверить обработку edge case: extract_signals вернул [] (design.md 4.4)
  Context: Существующие тесты покрывают _process_item с бифуркацией idea/report,
    _handle_idea, _handle_report. После рефакторинга (T-09, T-10) pipeline работает
    без бифуркации: всегда report -> extract_signals -> dispatch_signal.
  Depends on: T-09, T-10
  Verify: PYTHONPATH=knowledge-engine pytest knowledge-engine/tests/test_signal_orchestrator.py -v
  Live test: docker compose exec knowledge-engine sh -c "PYTHONPATH=. pytest tests/test_signal_orchestrator.py -v --tb=short"
  Status: [✓] done
  Completed: 05.08.2026
```

```
T-22 [P] [sonnet] — Адаптировать test_research_runner.py для dispatch_signal()
  Traces to: US-05, AC-12
  File: knowledge-engine/tests/test_research_runner.py
  Task: Обновить тесты _extract_and_classify():
    1. Заменить mock extract_ideas_full -> mock extract_signals
    2. Заменить mock dispatch_idea -> mock dispatch_signal
    3. Проверить что dispatch_signal вызывается с source="research-report"
    4. Проверить что frontmatter обновляется с signals_count и signal_refs (вместо ideas_count, ideas_refs)
    5. Проверить outcome classification: "signal" вместо "idea"
    6. Добавить тест: extract_signals вернул [] -> outcome="insight" или "not_relevant"
  Context: Существующие тесты _extract_and_classify проверяют цепочку
    extract_ideas_full -> dispatch_idea. После рефакторинга (T-16) цепочка:
    extract_signals -> dispatch_signal. Паттерн тестирования тот же (monkeypatch).
  Depends on: T-16
  Verify: PYTHONPATH=knowledge-engine pytest knowledge-engine/tests/test_research_runner.py -k "_extract_and_classify" -v
  Live test: docker compose exec knowledge-engine sh -c "PYTHONPATH=. pytest tests/test_research_runner.py -v --tb=short"
  Status: [✓] done (05.08.2026)
```

```
T-23 [P] [sonnet] — Создать тесты для новых Signal API endpoints
  Traces to: US-02, AC-05, AC-06, AC-07, AC-08, AC-17, AC-18
  File: knowledge-engine/tests/test_api_signals.py
  Task: Создать новые тесты (или переписать существующие BL-202 тесты):
    1. test_signals_list_empty: нет файлов -> {signals: [], total: 0}
    2. test_signals_list_with_pending: 2 pending сигнала -> корректный список
    3. test_signals_list_filter_by_status: фильтрация status=pending
    4. test_signals_list_filter_by_date: фильтрация date=YYYY-MM-DD
    5. test_signal_detail_success: существующий signal_id -> полные данные
    6. test_signal_detail_not_found: несуществующий -> 404
    7. test_signal_approve_success (AC-18): pending -> approved + dispatch_idea вызван
    8. test_signal_approve_conflict (AC-18): уже approved -> 409
    9. test_signal_approve_no_draft_idea: draft_idea=null -> 400
    10. test_signal_dismiss_success: pending -> dismissed
    11. test_signal_dismiss_conflict: уже dismissed -> 409
    12. test_signal_id_validation: path traversal -> 400
    Тесты используют TestClient из FastAPI + tmp_path для vault.
    Подготовка: создать wiki/reports/signals/{id}.md и raw/inbound/signals/{id}.json.
  Context: test_api_signals.py существует с тестами BL-202 endpoints.
    Старые тесты нужно заменить на новые для Signal-артефактов.
    Контракт API из design.md секция 2.4.
  Depends on: T-11, T-12
  Verify: PYTHONPATH=pm-bot:knowledge-engine pytest knowledge-engine/tests/test_api_signals.py -v
  Live test: docker compose exec pm-bot sh -c "PYTHONPATH=.:../knowledge-engine pytest ../knowledge-engine/tests/test_api_signals.py -v --tb=short"
  Status: [✓] done (05.08.2026)
```

```
T-24 [P] [sonnet] — Написать скрипт миграции IDEA файлов со статусом "Сигнал"
  Traces to: US-01, AC-13, AC-14
  File: knowledge-engine/scripts/migrate_signal_ideas.py
  Task: Создать скрипт миграции (одноразовый запуск):
    1. Сканировать wiki/domains/*/ideas/IDEA-*.md
    2. Для каждого файла: read_frontmatter(), проверить status
    3. Если status == "Сигнал":
       - update_frontmatter(path, {"status": "Отсев", "migrated_from": "Сигнал", "migrated_at": ISO timestamp})
       - Логировать: путь файла, старый статус -> новый статус
    4. Вывести итоговую статистику: N файлов найдено, M мигрировано
    5. Поддержка --dry-run: показать что будет изменено без фактической записи
    6. Логирование каждого шага
  Context: design.md секция 3.4 "Что делать с existing ideas со статусом Сигнал":
    один раз выполнить миграцию status "Сигнал" -> "Отсев". Скрипт необратим,
    но не деструктивен -- "Отсев" является допустимым статусом IDEA.
    read_frontmatter и update_frontmatter из shared.file_writer (импортируются в vault_api.py).
  Depends on: T-13
  Verify: PYTHONPATH=knowledge-engine python -c "import knowledge_engine.scripts.migrate_signal_ideas; print('import OK')"
  Live test: |
    # Dry run:
    docker compose exec knowledge-engine python scripts/migrate_signal_ideas.py --dry-run
    # Если есть файлы для миграции -- запустить без dry-run:
    docker compose exec knowledge-engine python scripts/migrate_signal_ideas.py
    # Проверить что нет IDEA со статусом "Сигнал":
    grep -rl "status: Сигнал" /vault/wiki/domains/*/ideas/  # должно быть 0 результатов
  Status: [✓] done
```

---

## Фаза G: Удаление старого кода и документация (зависит от Фазы F)

```
T-25 [P] [sonnet] — Удалить промпт signal_analyze.txt
  Traces to: US-01, AC-03
  File: knowledge-engine/app/prompts/signal_analyze.txt
  Task: Удалить файл signal_analyze.txt. Он заменён на signal_report_generate.txt (T-03).
    Проверить что ни один import/open не ссылается на signal_analyze.txt:
    - grep по всем .py файлам на "signal_analyze"
    - Если есть ссылки -- убрать их
  Context: signal_analyze.txt использовался в analyze_signal() (строки 278-374 signal_moderator.py).
    analyze_signal() удалён в рамках рефакторинга _process_item() (T-09).
    Operation "signal_analyze" в llm_client.py остаётся (backward compat) -- не трогать.
    design.md секция 7.3: "signal_analyze.txt: Удалить в фазе G".
  Depends on: T-20, T-21 (тесты прошли -- значит старый код не используется)
  Verify: python -c "import os; assert not os.path.exists('knowledge-engine/app/prompts/signal_analyze.txt'); print('OK')"
  Live test: docker compose exec knowledge-engine ls -la app/prompts/ | grep signal  # signal_analyze.txt должен отсутствовать
  Status: [✓] done
```

```
T-26 [P] [sonnet] — Финальная очистка imports в signal_orchestrator.py и signal_moderator.py
  Traces to: US-01, AC-01
  File: knowledge-engine/app/signal_orchestrator.py, knowledge-engine/app/signal_moderator.py
  Task: Проверить и очистить неиспользуемые imports после рефакторинга:
    1. signal_orchestrator.py:
       - Убрать import analyze_signal (если остался)
       - Убрать import dispatch_report (если остался)
       - Убрать import AnalysisResult (если не используется)
       - Убрать ссылки на _handle_idea, _handle_report, check_pending_reports
       - Добавить import generate_analysis_report, extract_signals, dispatch_signal, ReportResult, SignalData (если не добавлены)
    2. signal_moderator.py:
       - Убрать import/ссылки на BL-202 функции (если остались)
       - Убрать AnalysisResult если не используется (dispatch_idea может всё ещё использовать -- проверить)
       - Убрать dispatch_report() если не используется
    Запустить ruff check для проверки unused imports (если настроен).
  Context: После рефакторинга фаз B-E в файлах могут остаться неиспользуемые imports.
    ruff check может помочь найти их. Blocking rule: CI check before push (MEMORY.md).
  Depends on: T-20, T-21, T-22, T-23 (тесты прошли)
  Verify: cd knowledge-engine && ruff check app/signal_orchestrator.py app/signal_moderator.py --select F401
  Live test: docker compose exec knowledge-engine python -c "
import app.signal_orchestrator
import app.signal_moderator
print('OK: no import errors')
"
  Status: [✓] done
```

```
T-27 [haiku] — Обновить index.md, BACKLOG.md, CHANGELOG.md, README.md
  Traces to: US-01, US-02, US-03, US-04, US-05
  File: index.md, BACKLOG.md, CHANGELOG.md, README.md
  Task: Обновить проектную документацию:
    1. index.md: добавить новые файлы (signal_report_generate.txt, signal_extract.txt),
       новые функции (generate_analysis_report, extract_signals, dispatch_signal),
       новые vault пути (raw/inbound/signals/, wiki/reports/signals/),
       обновить описание signal_moderator.py и signal_orchestrator.py
    2. BACKLOG.md: отметить BL-203 как [done], убрать из текущего спринта
    3. CHANGELOG.md: добавить запись для BL-203 с описанием: Signal-First Pipeline,
       HITL triage, новые API endpoints, откат BL-202, settings threshold
    4. README.md: обновить если изменились: API endpoints, pipeline flow, конфигурация
       (moderator.relevance_threshold в user-prefs)
    Все даты в формате DD.MM.YYYY. Все тексты на русском.
  Context: Blocking rule из CLAUDE.md: "после каждой задачи обновлять BACKLOG/CHANGELOG/README
    без напоминания" (Phase 4 шаг 6). Эта задача выполняется последней, после прохождения
    всех тестов и pre-flight checklist.
  Depends on: T-25, T-26 (вся реализация завершена)
  Verify: ls -la index.md BACKLOG.md CHANGELOG.md README.md  # все файлы существуют
  Live test: head -20 CHANGELOG.md  # должна быть запись BL-203
  Status: [✓] done
```

---

## Матрица параллелизма

| Фаза | Задачи | Параллельные | Зависят от |
|------|--------|-------------|------------|
| A | T-01, T-02, T-03, T-04 | Все [P] | none |
| B | T-05 | - | Фаза A |
| B | T-06, T-07, T-08 | T-07, T-08 [P] после T-05 | T-05, T-03/T-04 |
| B | T-09 | - | T-06, T-07, T-08 |
| B | T-10 | [P] с T-06-T-08 | T-05 |
| C | T-11 | - | T-01, T-08, T-09 |
| C | T-12, T-13 | [P] | T-11 |
| C | T-14 | [P] с T-12, T-13 | T-11 |
| C | T-15 | - | T-14 |
| D | T-16 | [P] с Фазой C | T-07, T-08 |
| E | T-17 | - | T-11, T-12 |
| E | T-18 | - | T-11, T-17 |
| E | T-19 | [P] с T-18 | T-17 |
| F | T-20, T-21, T-22, T-23, T-24 | Все [P] | Фазы B, C, D |
| G | T-25, T-26 | [P] | Фаза F |
| G | T-27 | - | T-25, T-26 |

## Трассировка AC -> Tasks

| AC | Tasks |
|----|-------|
| AC-01 | T-01, T-05, T-06, T-08, T-09, T-20 |
| AC-02 | T-05, T-08, T-20 |
| AC-03 | T-02, T-03, T-06, T-09, T-20, T-25 |
| AC-04 | T-09, T-14, T-15 |
| AC-05 | T-17, T-18, T-23 |
| AC-06 | T-11, T-17, T-18, T-23 |
| AC-07 | T-11, T-17, T-18, T-23 |
| AC-08 | T-18, T-23 |
| AC-09 | T-10, T-19, T-21 |
| AC-10 | T-10, T-19, T-21 |
| AC-11 | T-11, T-18 |
| AC-12 | T-16, T-22 |
| AC-13 | T-13, T-15, T-24 |
| AC-14 | T-13, T-24 |
| AC-15 | T-01, T-08, T-20 |
| AC-16 | T-08, T-20 |
| AC-17 | T-11, T-17, T-23 |
| AC-18 | T-11, T-23 |
| AC-19 | T-02, T-04, T-05, T-07, T-20 |
