# BL-161: Поиск и фильтрация отчётов — Tasks

## Задачи

```
T-01 [sonnet] — Добавить функцию _extract_report_type в vault_api.py
  Traces to: AC-03, AC-07
  File: pm-bot/app/vault_api.py
  Task: Добавить функцию _extract_report_type(text: str) -> str перед list_reports().
        Логика: ищет YAML frontmatter (--- ... ---), парсит поле type:.
        Если frontmatter отсутствует или type не найден → возвращает "other".
        Добавить логирование: успех — тип найден, fallback — "other".
  Context: list_reports() уже читает весь текст файла через f.read_text().
           Полный YAML-парсер не нужен — frontmatter в отчётах плоский.
           Функция _extract_report_title(text) уже существует рядом (строка ~1590).
           12 допустимых типов: daily, daily-status-report, sync, planning,
           weekly-status-report, synthesis, supplier-profile, competitor-info,
           feature-analysis-report, pm_assistant-audit, analysis, plan-next-week.
  Acceptance criteria: AC-07 — файлы без type получают "other"
  Verify: python -m pytest pm-bot/tests/ -k "extract_report_type" -v
  Live test: curl http://192.168.0.6:8000/api/v1/reports | python -m json.tool | head -20
             → каждый элемент содержит поле "type"
  Depends on: нет
  Status: [✓] done
```

```
T-02 [sonnet] — Добавить type в ответ list_reports
  Traces to: AC-03, AC-07
  File: pm-bot/app/vault_api.py, функция list_reports (строка 1597)
  Task: В цикле for f in files (строка 1628) после извлечения title
        вызвать report_type = _extract_report_type(text).
        Добавить "type": report_type в dict, формируемый через results.append().
        Обновить логирование parsed-записи: добавить type в log.
  Context: Текущий dict: {"filename": f.name, "date": date, "title": title}.
           Нужно расширить до {"filename": f.name, "date": date, "title": title, "type": report_type}.
           text уже прочитан строкой выше (строка 1630).
  Acceptance criteria: AC-03 — endpoint возвращает type для каждого отчёта
  Verify: python -m pytest pm-bot/tests/ -k "list_reports" -v
  Live test: curl -s http://192.168.0.6:8000/api/v1/reports | python -c "
    import sys,json; data=json.load(sys.stdin);
    types=set(r['type'] for r in data['reports']);
    print(f'Types: {types}'); print(f'Count: {len(data[\"reports\"])}');
    assert all('type' in r for r in data['reports']), 'missing type field'"
  Depends on: T-01
  Status: [✓] done
```

```
T-03 [sonnet] — Написать unit-тесты для _extract_report_type и обновлённого list_reports
  Traces to: AC-03, AC-07
  File: pm-bot/tests/test_report_type_extraction.py (новый файл)
  Task: Написать тесты:
        1. _extract_report_type с валидным frontmatter → возвращает тип
        2. _extract_report_type без frontmatter → "other"
        3. _extract_report_type с frontmatter без type → "other"
        4. _extract_report_type с пустым type → "other"
        5. _extract_report_type с type в кавычках (одинарных и двойных) → корректный тип
        6. list_reports включает поле type в каждый элемент (mock файловой системы)
  Context: Существующие тесты для vault_api в pm-bot/tests/.
           _extract_report_type — чистая функция, тестируется без mock.
  Acceptance criteria: AC-07
  Verify: python -m pytest pm-bot/tests/test_report_type_extraction.py -v
  Live test: N/A (unit-тесты)
  Depends on: T-01, T-02
  Status: [✓] done (20/20 passed)
```

```
T-04 [sonnet] — Добавить поиск и фильтр UI в report.html
  Traces to: US-01, US-02, US-03, AC-01, AC-02, AC-03, AC-04, AC-05, AC-06
  File: pm-bot/web/report.html
  Task: Комплексная задача по модификации Vue-приложения:

  A) Добавить CSS стили (в блок <style> перед </head>):
     - .report-search — контейнер поисковой строки
     - .report-search input — стилизация инпута
     - .report-search-wrapper — relative-обёртка для позиционирования кнопки ✕
     - .report-search-clear — кнопка очистки
     - .report-type-chips — контейнер чипов (flex, overflow-x: auto)
     - .report-type-chip — стиль чипа (border, uppercase, 9px)
     - .report-type-chip.active — активный чип (cyan border+color)
     - .report-list-counter — стиль счётчика "N из M"
     - .report-list-empty-filtered — пустое состояние при фильтрации

  B) Добавить HTML в левую панель (report-list-panel), ПЕРЕД report-list-header:
     - Поисковая строка: div.report-search > div.report-search-wrapper >
       input(v-model, placeholder="Поиск отчёта...") + span.report-search-clear(v-if, @click)
     - Фильтр-чипы: div.report-type-chips > span.report-type-chip(v-for="chip in typeChips",
       :class, @click)

  C) Обновить report-list-header:
     - Текст: "REPORTS" → "REPORTS" + span с "(N из M)" при активном фильтре

  D) Обновить v-for списка:
     - v-for="r in reports" → v-for="r in filteredReports"
     - Пустое состояние при фильтрации: v-else-if="reports.length > 0"
       → "Ничего не найдено" (AC-06)

  E) Добавить Vue-переменные в setup():
     - var searchQuery = Vue.ref('');
     - var selectedType = Vue.ref('all');

  F) Добавить computed properties:
     - filteredReports — фильтрация по type + поиск по title/filename (AND)
     - typeChips — динамические чипы из уникальных type с counts

  G) Добавить функции:
     - clearSearch() — сброс searchQuery
     - selectType(type) — установка selectedType

  H) Добавить watcher на filteredReports:
     - Если selectedFilename не в filteredReports → авто-выбор первого

  I) Обновить return в setup(): добавить searchQuery, selectedType,
     filteredReports, typeChips, clearSearch, selectType

  Context: report.html — Vue 3 SPA (строки 353-559). Dual-theme: matrix (var(--cyan)
           и пр.) и light (style-light.css перебивает). Использует var(--border),
           var(--text-muted), var(--text-body), var(--cyan), var(--card) CSS-переменные.
           Текущий шаблон: строки 276-293 (левая панель), 353-552 (setup).
           Стиль кода: vanilla JS, function() {} (не arrow), var (не const/let),
           Vue.ref/Vue.computed/Vue.watch.

  Acceptance criteria: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06
  Verify: Визуальная проверка — файл должен быть синтаксически корректным HTML
  Live test: Открыть http://192.168.0.6:8080/report.html в браузере →
    1. Видна поисковая строка и фильтр-чипы
    2. Ввести "supplier" → видны только supplier-отчёты
    3. Нажать ✕ → список полный
    4. Кликнуть чип "sync" → только sync-отчёты
    5. Кликнуть "daily" → переключение (single-select)
    6. Ввести "grafana" при выбранном чипе → AND-фильтрация
    7. Ввести несуществующий текст → "Ничего не найдено"
    8. Переключить тему на light → стили корректны
  Depends on: T-02 (нужен type в ответе API)
  Status: [✓] done
```

```
T-05 [sonnet] — Проверить и дополнить стили для light-темы
  Traces to: AC-01 через AC-06 (visual consistency)
  File: pm-bot/web/style-light.css
  Task: Проверить, что CSS-переменные var(--border), var(--text-muted),
        var(--text-body), var(--cyan), var(--card), var(--card-hover)
        корректно применяются к новым элементам в light-теме.
        Если .report-type-chip.active использует rgba(0,255,255,0.08) —
        добавить override для light-темы с подходящим цветом.
        Проверить контрастность текста чипов на светлом фоне.
  Context: memory: "PMA: light theme overrides base CSS" — style-light.css
           перебивает style.css, при CSS-фиксах проверять оба файла.
           Переменные определены в style-matrix.css и style-light.css.
  Acceptance criteria: визуальная корректность обеих тем
  Verify: diff стилей — убедиться что нет hardcoded цветов
  Live test: Открыть report.html → переключить тему → поиск/чипы читаемы
  Depends on: T-04
  Status: [✓] done
```

```
T-06 [sonnet] — Обновить автовыбор первого отчёта при фильтрации
  Traces to: AC-02, AC-04
  File: pm-bot/web/report.html
  Task: Добавить Vue.watch на filteredReports: если текущий selectedFilename
        не содержится в filteredReports, автоматически выбрать первый элемент
        из отфильтрованного списка (или null если список пуст).
        Это предотвращает ситуацию, когда правая панель показывает отчёт,
        которого нет в левом списке.
  Context: Watcher должен быть внутри setup() перед return.
           Формат: Vue.watch(filteredReports, function(newList) { ... })
  Acceptance criteria: AC-02 — при сбросе поиска список обновляется корректно
  Verify: ручная проверка логики
  Live test: Выбрать отчёт "X" → ввести поиск, исключающий "X" →
             правая панель переключается на первый из найденных
  Depends on: T-04
  Status: [✓] done (watcher включён в T-04)
```

## Порядок выполнения

```
T-01 → T-02 → T-03 (бэкенд, последовательно)
         ↓
T-04 → T-05 (фронтенд, после T-02)
  ↓
T-06 (интеграция watcher, после T-04)
```

Примечание: T-06 может быть включён в T-04 как подзадача (пункт H),
но выделен отдельно для явной трассировки к AC-02/AC-04.

## Параллелизм

- T-03 [P] и T-04 [P] могут запускаться параллельно после T-02
- T-05 и T-06 последовательны после T-04
