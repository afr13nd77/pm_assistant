# BL-119: Единый источник domain-правил — Task Breakdown

**Status:** DONE
**Created:** 12.06.2026
**Design:** [design.md](design.md)
**Requirements:** [requirements.md](requirements.md)

---

## Зависимости между задачами

```
T-01 ──┬──→ T-02 ──→ T-03 ──→ T-04 (domain_config.py KE)
       │
       ├──→ T-05 ──→ T-06 ──→ T-07 (domain_config.py pm-bot)
       │              ↓
       │         T-08 ──→ T-09 (claude_client.py)
       │
       ├──→ T-10 ──→ T-11 (artifact_extractor.py)
       │
       ├──→ T-12 ──→ T-13 (ingest.py)
       │
       └──→ T-14 (domain-config.yaml seed)

T-04, T-07, T-09, T-11, T-13, T-14 ──→ T-15 (тесты) ──→ T-16 (live test)
```

Параллельные блоки: [T-05..T-07] ‖ [T-10..T-11] ‖ [T-12..T-13] ‖ [T-14]

---

## Block A: domain_config.py (knowledge-engine) — фундамент

```
T-01 [sonnet] — Добавить build_keyword_map(), build_prompt_section(), get_valid_domains()
  Traces to: US-01, US-03, AC-03, AC-04, AC-05
  File: knowledge-engine/app/domain_config.py
  Task: Добавить 3 новые функции и константу _MAX_PROMPT_HINT = 500:
    1. build_keyword_map() -> dict[str, str] — строит {keyword_lower: domain_slug} из конфига
    2. build_prompt_section() -> str — генерирует секцию доменов для LLM-промпта (prompt_hint → description fallback)
    3. get_valid_domains() -> tuple[str, ...] — возвращает tuple slug-ов из конфига
  Context: Файл уже содержит build_tag_map() (строки 380-403) и build_label_map() — следовать тому же паттерну. Все функции используют load() с mtime-кешем. Код каждой функции — в design.md §2.3.1–2.3.3.
  Depends on: нет
  Verify: PYTHONPATH=knowledge-engine pytest knowledge-engine/tests/test_domain_config.py -v
  Live test: python -c "from app.domain_config import build_keyword_map, build_prompt_section, get_valid_domains; print(build_keyword_map()); print(build_prompt_section()); print(get_valid_domains())" (из knowledge-engine/)
  Status: [✓] done
```

```
T-02 [sonnet] — Расширить validate_domain_entry() для keywords и prompt_hint
  Traces to: US-01, AC-01
  File: knowledge-engine/app/domain_config.py, функция validate_domain_entry()
  Task: Добавить валидацию:
    - keywords: optional list, каждый элемент — непустая строка
    - prompt_hint: optional string, max _MAX_PROMPT_HINT (500) символов
  Context: Валидация tags уже реализована (строки 256-268) — следовать тому же паттерну. Код — в design.md §2.3.4.
  Depends on: T-01 (нужна константа _MAX_PROMPT_HINT)
  Verify: PYTHONPATH=knowledge-engine pytest knowledge-engine/tests/test_domain_config.py -k "validate" -v
  Live test: python -c "from app.domain_config import validate_domain_entry; print(validate_domain_entry('test', {'display_name': 'Test', 'keywords': ['a', ''], 'prompt_hint': 'x'*501}))" (ожидать ошибки валидации)
  Status: [✓] done
```

```
T-03 [sonnet] — Расширить set_domain() normalize block + merge с existing
  Traces to: US-01, AC-08
  File: knowledge-engine/app/domain_config.py, функция set_domain() (строка ~330)
  Task: 
    1. Добавить keywords и prompt_hint в normalized dict
    2. При обновлении (домен уже существует) — мержить keywords/prompt_hint/tags с existing записью, чтобы Web UI не затирала поля
  Context: Текущий normalize (строка 330-336) содержит: display_name, description, color, jira_labels, tags. Добавить keywords, prompt_hint. Merge паттерн — design.md §2.11.
  Depends on: T-01
  Verify: PYTHONPATH=knowledge-engine pytest knowledge-engine/tests/test_domain_config.py -k "set_domain" -v
  Live test: вручную вызвать set_domain с entry без keywords → убедиться что existing keywords не затёрты
  Status: [✓] done
```

```
T-04 [sonnet] — Добавить _SEED_DOMAIN_DATA + расширить seed_from_defaults()
  Traces to: US-01, AC-01, AC-02
  File: knowledge-engine/app/domain_config.py, функция seed_from_defaults()
  Task:
    1. Добавить константу _SEED_DOMAIN_DATA (dict с полными данными 5 доменов: tags, keywords, prompt_hint)
    2. Обновить seed_from_defaults() — при создании записи обогащать из _SEED_DOMAIN_DATA
  Context: Текущий seed создаёт домены только с display_name, description, color, jira_labels. Данные для seed — design.md §2.8. seed_from_defaults() идемпотентен: не перезаписывает существующий конфиг.
  Depends on: T-01
  Verify: PYTHONPATH=knowledge-engine pytest knowledge-engine/tests/test_domain_config.py -k "seed" -v
  Live test: удалить domain-config.yaml → вызвать seed_from_defaults() → проверить что файл содержит keywords и prompt_hint
  Status: [✓] done
```

## Block B: domain_config.py (pm-bot) — синхронизация

```
T-05 [sonnet] — Синхронизировать новые функции в pm-bot/app/domain_config.py
  Traces to: US-01, US-02, AC-03
  File: pm-bot/app/domain_config.py
  Task: Добавить из KE-копии:
    1. Константу _MAX_PROMPT_HINT = 500
    2. build_keyword_map() — идентично KE
    3. build_prompt_section() — идентично KE
    4. get_valid_domains() — идентично KE
  Context: pm-bot/app/domain_config.py — копия KE-версии с минимальными отличиями. Новые функции идентичны. Текущая pm-bot версия может не иметь tags в set_domain normalize (строка ~316).
  Depends on: T-01
  Verify: PYTHONPATH=pm-bot:knowledge-engine pytest pm-bot/tests/ -v
  Live test: python -c "import sys; sys.path.insert(0,'pm-bot'); from app.domain_config import get_valid_domains; print(get_valid_domains())"
  Status: [✓] done
```

```
T-06 [sonnet] — Расширить validate_domain_entry() в pm-bot/app/domain_config.py
  Traces to: US-01
  File: pm-bot/app/domain_config.py, функция validate_domain_entry()
  Task: Добавить валидацию keywords и prompt_hint — идентично T-02.
  Context: Следовать паттерну из KE-версии (T-02). Код — design.md §2.3.4.
  Depends on: T-05, T-02 (как образец)
  Verify: PYTHONPATH=pm-bot:knowledge-engine pytest pm-bot/tests/ -k "validate" -v
  Live test: аналогично T-02
  Status: [✓] done
```

```
T-07 [sonnet] — Расширить set_domain() в pm-bot + merge с existing
  Traces to: US-01, AC-08
  File: pm-bot/app/domain_config.py, функция set_domain() (строка ~316)
  Task:
    1. Добавить tags, keywords, prompt_hint в normalized dict
    2. Merge с existing записью для полей, не переданных в entry (защита от Web UI)
  Context: pm-bot set_domain может отличаться от KE. Обязательно: если entry не содержит keywords — взять из existing. Код — design.md §2.11. Это КРИТИЧНО для обратной совместимости с Web UI.
  Depends on: T-05, T-03 (как образец)
  Verify: PYTHONPATH=pm-bot:knowledge-engine pytest pm-bot/tests/ -k "set_domain" -v
  Live test: через Web UI обновить display_name домена → проверить что keywords/prompt_hint не затёрты
  Status: [✓] done
```

## Block C: claude_client.py (pm-bot) — динамический промпт

```
T-08 [sonnet] — Добавить _get_valid_domains() + _FALLBACK_DOMAINS
  Traces to: US-02, AC-01, AC-02, AC-06
  File: pm-bot/app/claude_client.py
  Task:
    1. Переименовать _VALID_DOMAINS → _FALLBACK_DOMAINS (строка 16)
    2. Добавить функцию _get_valid_domains() — читает из domain_config.get_valid_domains() с fallback на _FALLBACK_DOMAINS
    3. Обновить _validate_idea_data() — заменить _VALID_DOMAINS на _get_valid_domains()
  Context: Текущий _VALID_DOMAINS (строка 16) — статический tuple без partner-search-engine. После изменения — динамический список из конфига. Код — design.md §2.4 шаг 1-2.
  Depends on: T-05 (pm-bot domain_config должен иметь get_valid_domains)
  Verify: PYTHONPATH=pm-bot:knowledge-engine pytest knowledge-engine/tests/test_claude_client.py -v
  Live test: docker compose up → отправить идею с domain partner-search-engine → проверить что domain не сбрасывается на general
  Status: [✓] done
```

```
T-09 [sonnet] — Добавить _build_idea_prompt() + _inject_domains_section()
  Traces to: US-02, AC-03
  File: pm-bot/app/claude_client.py
  Task:
    1. Добавить _inject_domains_section(template, domains_section) — трёхуровневая стратегия (placeholder → regex → append)
    2. Добавить _build_idea_prompt(raw_text) — динамическая генерация промпта с fallback на статический idea.txt
    3. Обновить process_idea() — использовать _build_idea_prompt() вместо прямого _load_prompt("idea")
  Context: idea.txt (строки 6-10) содержит статический список 4 доменов. _inject_domains_section заменяет этот блок на динамический из domain_config.build_prompt_section(). Код — design.md §2.4 шаг 3-4.
  Depends on: T-05 (pm-bot domain_config должен иметь build_prompt_section), T-08 (для согласованности)
  Verify: PYTHONPATH=pm-bot:knowledge-engine pytest knowledge-engine/tests/test_claude_client.py -v
  Live test: docker compose up → отправить идею → в логах убедиться "using dynamic domains section (5 domains)"
  Status: [✓] done
```

## Block D: artifact_extractor.py (knowledge-engine) — merged keywords

```
T-10 [sonnet] — Добавить _merged_keyword_map() в artifact_extractor.py
  Traces to: US-03, AC-05
  File: knowledge-engine/app/artifact_extractor.py
  Task: Добавить функцию _merged_keyword_map() — мержит хардкоженный _DOMAIN_KEYWORDS с keywords из domain_config.load(). Config extends hardcoded (добавляет, не удаляет). partner-search-engine появляется автоматически.
  Context: _DOMAIN_KEYWORDS (строки 23-33) содержит 3 домена, partner-search-engine отсутствует. Функция перестраивает config keywords (dict[str, str]) в dict[str, list[str]] для совместимости с _detect_domain(). Код — design.md §2.6 шаг 1.
  Depends on: T-01 (KE domain_config.build_keyword_map)
  Verify: PYTHONPATH=knowledge-engine pytest knowledge-engine/tests/test_artifact_extractor.py -v
  Live test: python -c "from app.artifact_extractor import _merged_keyword_map; m = _merged_keyword_map(); print('partner-search-engine' in m, len(m))"
  Status: [✓] done
```

```
T-11 [sonnet] — Обновить _detect_domain() в artifact_extractor.py
  Traces to: US-03, AC-05
  File: knowledge-engine/app/artifact_extractor.py, функция _detect_domain() (строки 269-288)
  Task: Заменить прямое чтение _DOMAIN_KEYWORDS на вызов _merged_keyword_map(). Добавить .lower() для case-insensitive сравнения.
  Context: Текущий код: `for domain, keywords in _DOMAIN_KEYWORDS.items()`. Новый: `for domain, keywords in _merged_keyword_map().items()`. Код — design.md §2.6 шаг 2.
  Depends on: T-10
  Verify: PYTHONPATH=knowledge-engine pytest knowledge-engine/tests/test_artifact_extractor.py -k "detect_domain" -v
  Live test: вызвать _detect_domain("добавить B2B-фильтр для поставщиков") → ожидать partner-search-engine
  Status: [✓] done
```

## Block E: ingest.py (knowledge-engine) — merged keywords

```
T-12 [sonnet] — Добавить _merged_keyword_map() в ingest.py
  Traces to: US-03, AC-04
  File: knowledge-engine/app/ingest.py
  Task: Добавить функцию _merged_keyword_map() — мержит KEYWORD_TO_DOMAIN с domain_config.build_keyword_map(). Config имеет приоритет (update).
  Context: Паттерн ИДЕНТИЧЕН уже реализованной _merged_tag_map() (строки 150-185). KEYWORD_TO_DOMAIN (строки 83-118) уже содержит partner-search-engine. Код — design.md §2.7 шаг 1.
  Depends on: T-01 (KE domain_config.build_keyword_map)
  Verify: PYTHONPATH=knowledge-engine pytest knowledge-engine/tests/test_ingest.py -v
  Live test: python -c "from app.ingest import _merged_keyword_map; m = _merged_keyword_map(); print(len(m))"
  Status: [✓] done
```

```
T-13 [sonnet] — Обновить detect_domain() keyword path в ingest.py
  Traces to: US-03, AC-04, AC-07
  File: knowledge-engine/app/ingest.py, функция detect_domain() (строки 233-243)
  Task: Заменить прямое чтение KEYWORD_TO_DOMAIN на вызов _merged_keyword_map() в Step 2 (keyword matching).
  Context: Текущий код (строка 237): `for keyword, domain in KEYWORD_TO_DOMAIN.items()`. Новый: `keyword_map = _merged_keyword_map(); for keyword, domain in keyword_map.items()`. Код — design.md §2.7 шаг 2.
  Depends on: T-12
  Verify: PYTHONPATH=knowledge-engine pytest knowledge-engine/tests/test_ingest.py -k "detect_domain" -v
  Live test: добавить keyword "микросервисы" для search-engine в domain-config.yaml → вызвать detect_domain с текстом "микросервисы" → ожидать search-engine
  Status: [✓] done
```

## Block F: Seed data

```
T-14 [sonnet] — Заполнить domain-config.yaml полными данными
  Traces to: US-01, AC-01, AC-02, AC-04, AC-05
  File: <VAULT_PATH>/domain-config.yaml (путь из vault_paths.domain_config_path())
  Task: Обновить domain-config.yaml — добавить поля tags, keywords, prompt_hint для всех 5 доменов. Если файл не существует — будет создан через seed_from_defaults() (T-04). Если существует — обновить вручную.
  Context: Текущий domain-config.yaml может содержать только display_name, description, color, jira_labels. Полный формат — design.md §2.2 (пример конфига). Данные для каждого домена — design.md §2.8 (_SEED_DOMAIN_DATA).
  Depends on: T-01 (валидация новых полей)
  Verify: python -c "from app.domain_config import load, validate; cfg = load(); errs = validate(cfg); print('errors:', errs); print('domains:', list(cfg.get('domains',{}).keys()))" (из knowledge-engine/)
  Live test: прочитать файл → убедиться что все 5 доменов имеют tags, keywords, prompt_hint
  Status: [✓] done
```

## Block G: Тесты

```
T-15 [sonnet] — Тесты для новых функций domain_config.py
  Traces to: AC-01..AC-08
  File: knowledge-engine/tests/test_domain_config.py
  Task: Добавить тесты:
    1. test_build_keyword_map — map из конфига с keywords, пустой конфиг, дубликаты keywords
    2. test_build_prompt_section — prompt_hint приоритет, fallback на description, пустой конфиг
    3. test_get_valid_domains — все slugs, пустой конфиг
    4. test_validate_keywords — валидные, невалидные (не list, пустая строка)
    5. test_validate_prompt_hint — валидный, слишком длинный, не строка
    6. test_set_domain_merge — merge с existing для keywords/prompt_hint
    7. test_seed_with_full_data — seed создаёт домены с keywords/prompt_hint
  Context: Существующие тесты используют tmp_path fixture и VAULT_PATH mock. Следовать тому же паттерну.
  Depends on: T-01..T-04
  Verify: PYTHONPATH=knowledge-engine pytest knowledge-engine/tests/test_domain_config.py -v
  Live test: N/A (unit tests)
  Status: [✓] done
```

```
T-16 [sonnet] — Тесты для claude_client.py
  Traces to: AC-01, AC-02, AC-03, AC-06
  File: knowledge-engine/tests/test_claude_client.py
  Task: Добавить тесты:
    1. test_get_valid_domains_from_config — домены из конфига
    2. test_get_valid_domains_fallback — fallback при отсутствии конфига
    3. test_build_idea_prompt_dynamic — промпт с доменами из конфига
    4. test_build_idea_prompt_fallback — fallback на статический idea.txt
    5. test_inject_domains_placeholder — стратегия 1 (placeholder)
    6. test_inject_domains_regex — стратегия 2 (regex)
    7. test_inject_domains_append — стратегия 3 (append)
  Context: Тесты mock-ают domain_config модуль и LLM-клиент. Следовать паттерну существующих тестов.
  Depends on: T-08, T-09
  Verify: PYTHONPATH=pm-bot:knowledge-engine pytest knowledge-engine/tests/test_claude_client.py -v
  Live test: N/A (unit tests)
  Status: [✓] done
```

```
T-17 [sonnet] — Тесты для artifact_extractor.py
  Traces to: AC-05
  File: knowledge-engine/tests/test_artifact_extractor.py
  Task: Добавить тесты:
    1. test_merged_keyword_map_with_config — config extends hardcoded
    2. test_merged_keyword_map_no_config — fallback на _DOMAIN_KEYWORDS
    3. test_detect_domain_partner_search — partner-search-engine через config keywords
    4. test_detect_domain_general_fallback — fallback на general
  Context: Mock domain_config.load() для подстановки конфига с keywords.
  Depends on: T-10, T-11
  Verify: PYTHONPATH=knowledge-engine pytest knowledge-engine/tests/test_artifact_extractor.py -v
  Live test: N/A (unit tests)
  Status: [✓] done
```

```
T-18 [sonnet] — Тесты для ingest.py
  Traces to: AC-04, AC-07
  File: knowledge-engine/tests/test_ingest.py
  Task: Добавить тесты:
    1. test_merged_keyword_map — config overlay на KEYWORD_TO_DOMAIN
    2. test_merged_keyword_map_no_config — fallback на KEYWORD_TO_DOMAIN
    3. test_detect_domain_config_keyword — keyword из конфига → правильный домен
    4. test_detect_domain_no_config_fallback — работа без конфига
  Context: Тесты _merged_tag_map() уже существуют — следовать паттерну. Mock domain_config.build_keyword_map().
  Depends on: T-12, T-13
  Verify: PYTHONPATH=knowledge-engine pytest knowledge-engine/tests/test_ingest.py -v
  Live test: N/A (unit tests)
  Status: [✓] done
```

## Block H: Full test suite + live verification

```
T-19 [sonnet] — Полный test suite (Phase 4.1)
  Traces to: все AC
  File: всё
  Task: Запустить полный test suite всех сервисов. Разделить результат на new failures и pre-existing.
  Context: Запуск из корня pm_assistant. Команды:
    PYTHONPATH=knowledge-engine pytest knowledge-engine/tests/ -v
    PYTHONPATH=pm-bot:knowledge-engine pytest pm-bot/tests/ -v
  Depends on: T-15..T-18
  Verify: 0 new failures ✅ (717+319 passed, 2 pre-existing fails in test_linter.py)
  Live test: результаты тестов
  Status: [✓] done
```

```
T-20 [sonnet] — Live verification: полный цикл
  Traces to: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06
  File: —
  Task: Проверить полный цикл в работающем окружении:
    1. docker compose up
    2. Проверить partner-search-engine: отправить идею "добавить B2B-фильтр для поставщиков" → ожидать domain: partner-search-engine (AC-02)
    3. Проверить динамический промпт: в логах "using dynamic domains section (5 domains)" (AC-03)
    4. Проверить fallback: остановить/удалить domain-config.yaml → отправить идею → ожидать fallback на хардкод (AC-06)
    5. Проверить artifact_extractor: обработать текст с "поставщик" → domain partner-search-engine (AC-05)
    6. Проверить ingest keyword: добавить новый keyword в конфиг → обработать текст → domain по новому keyword (AC-04, AC-08)
  Context: Требует запущенного Docker с pm-bot, knowledge-engine. VAULT_PATH указывает на vault с domain-config.yaml.
  Depends on: T-19
  Verify: 5/6 проверок пройдены, AC-02 заблокирован (нет кредитов Claude API)
  Live test: логи Docker подтверждают dynamic injection (5 domains, regex strategy)
  Status: [✓] done (AC-02 blocked by external: Claude API credits exhausted)
```

---

## Сводка

| Блок | Задачи | Файлы | Параллельность |
|---|---|---|---|
| A: domain_config KE | T-01..T-04 | knowledge-engine/app/domain_config.py | T-02, T-03, T-04 параллельны (после T-01) |
| B: domain_config pm-bot | T-05..T-07 | pm-bot/app/domain_config.py | T-06, T-07 параллельны (после T-05) |
| C: claude_client | T-08..T-09 | pm-bot/app/claude_client.py | последовательно |
| D: artifact_extractor | T-10..T-11 | knowledge-engine/app/artifact_extractor.py | последовательно |
| E: ingest | T-12..T-13 | knowledge-engine/app/ingest.py | последовательно |
| F: seed data | T-14 | domain-config.yaml | независимо |
| G: тесты | T-15..T-18 | knowledge-engine/tests/*.py | [P] все параллельны |
| H: верификация | T-19..T-20 | — | последовательно |

**Итого:** 20 задач, ~490 новых строк кода, ~100 модифицированных строк, 5 файлов
