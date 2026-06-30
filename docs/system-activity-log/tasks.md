# System Activity Log — Tasks

**Статус:** DONE (100%, все 14 задач завершены)
**Бэклог:** BL-143
**Дата:** 30.06.2026 (дополнение: LLM trace + per-unit details)
**Требования:** [requirements.md](requirements.md)
**Дизайн:** [design.md](design.md)

---

## Задачи

### Слой 1 — shared/system_log.py (ядро)

```
T-01 [opus] — Создать shared/system_log.py
  Traces to: AC-07, AC-09
  File: shared/system_log.py (новый)
  Task: Создать модуль с функциями:
    - init_db(db_path) — CREATE TABLE IF NOT EXISTS system_log + 3 индекса
    - _connect(db_path) — sqlite3.connect с timeout=5, PRAGMA journal_mode=WAL (fallback DELETE)
    - log_event(process_type, status, summary, details, duration_ms, source, db_path) → int
    - query_log(period, process_type, status, limit, offset, db_path) → {"total": int, "entries": list}
    - get_stats(db_path) → {"last_24h": {...}, "last_error": {...}}
    - cleanup_old(keep_days=90, db_path) → int
    - LoggedProcess context manager (process_type, source) — замер duration, auto status=error при exception
    - Константы: DB_FILENAME=".system-log.db", VALID_PROCESS_TYPES (11 шт.), VALID_STATUSES (4 шт.)
    - DB_PATH = Path(os.getenv("VAULT_PATH", "/vault")) / DB_FILENAME
  Context: Паттерн из enrichment_db.py — connect-per-call, db_path как параметр с дефолтом.
    Все записи безопасны при ошибке БД (логируем, не падаем).
    LoggedProcess использует time.monotonic_ns() для замера, не подавляет исключения.
    Схема таблицы и поля — см. design.md секция 2.
  Acceptance criteria: AC-07 — запись события при завершении задачи. AC-09 — cleanup старых записей.
  Verify: PYTHONPATH=. pytest shared/tests/test_system_log.py
  Live test: python -c "from shared.system_log import log_event, query_log, init_db; init_db(); log_event('linter','success','Ошибок: 0',{'total_issues':0},1200,'ke-cron'); print(query_log())"
  Status: [✓] done
```

```
T-02 [sonnet] — Unit-тесты для shared/system_log.py
  Traces to: AC-07, AC-08, AC-09
  File: shared/tests/test_system_log.py (новый)
  Task: Написать 12 unit-тестов:
    - test_init_db_creates_table
    - test_init_db_idempotent
    - test_log_event_success
    - test_log_event_error
    - test_log_event_with_details
    - test_log_event_invalid_type_still_writes (warning в лог, запись создаётся)
    - test_query_log_period_24h
    - test_query_log_filter_type_and_status
    - test_query_log_pagination
    - test_get_stats_counts
    - test_cleanup_old_deletes_expired
    - test_logged_process_success_and_error
  Context: Использовать tmp_path fixture для изолированной SQLite БД.
    Паттерн из shared/tests/test_llm_client.py — pytest, mocker, tmp_path.
  Acceptance criteria: AC-07, AC-08, AC-09 — программная верификация поведения модуля.
  Verify: PYTHONPATH=. pytest shared/tests/test_system_log.py -v
  Live test: запуск тестов, все 12 проходят
  Depends on: T-01
  Status: [✓] done
```

---

### Слой 2 — Интеграция в KE CLI (ke-cron)

```
T-03 [sonnet] — Обернуть CLI-команды KE в LoggedProcess
  Traces to: US-02, AC-01, AC-02, AC-03
  File: knowledge-engine/app/cli.py
  Task: Добавить LoggedProcess обёртку для 8 cron-команд:
    - decay_recalc: summary="{processed} файлов обработано, {transitions} переходов"
    - lint: summary="Проверка завершена. Проблем: {total_issues}"
    - health (--save): summary="Score: {prev}→{score} ({delta:+d}), grade: {grade}"
    - jira_sync: summary из result dict
    - synthesize: summary="Синтез выполнен" / "Пропущен"
    - fetch_meetings: summary="{enqueued} транскриптов поставлены в очередь"
    - process_queue: summary="{processed} обработано, {failed} ошибок"
    - rebuild_index: summary="{total_indices} индексов перестроено"
    Каждая обёртка:
    1. from shared.system_log import LoggedProcess
    2. with LoggedProcess("<type>", source="ke-cron") as lp:
    3. Заполнить lp.summary и lp.details из result dict
    Не менять существующую логику, только обернуть в context manager.
  Context: Все команды возвращают dict с ключом status. Вывод через _output_json() не трогать.
    source="ke-cron" для всех — они запускаются из crontab ke-cron контейнера.
    Таблица summary/details по типам — design.md секция 4.4.
  Acceptance criteria: AC-01 — после выполнения cron-задач записи появляются в system_log.
    AC-02 — success-записи содержат summary с метриками.
    AC-03 — error-записи содержат traceback в details.
  Verify: docker exec ke-cron python -m knowledge_engine lint && curl http://192.168.0.6:8000/api/v1/system-log
  Live test: запустить lint вручную → проверить запись в БД через sqlite3 /vault/.system-log.db "SELECT * FROM system_log"
  Depends on: T-01
  Status: [✓] done
```

---

### Слой 3 — Интеграция в pm-bot scheduler

```
T-04 [sonnet] — Обернуть scheduler jobs в LoggedProcess
  Traces to: US-02, AC-01
  File: pm-bot/app/scheduler.py, pm-bot/app/enrichment_reminder.py, pm-bot/app/daily_alert.py
  Task: Добавить LoggedProcess обёртку для 3 scheduled jobs:
    - _run_weekly_report_async: summary="Еженедельный отчёт сгенерирован", details={report_path, telegram_sent}
    - run_enrichment_check (enrichment_reminder.py): summary="{sent} напоминаний из {scanned} идей", details={ideas_scanned, reminders_sent, skipped_cooldown}
    - run_daily_alert (daily_alert.py): summary="Daily-протокол найден"/"Alert отправлен", details={daily_exists, alert_sent}
    source="pm-bot" для всех.
    LoggedProcess синхронный — не блокирует async event loop (INSERT < 1мс).
  Context: Jobs — async-функции (asyncio). LoggedProcess.__exit__ вызывает синхронный log_event().
    Не менять существующую логику Telegram-уведомлений.
  Acceptance criteria: AC-01 — scheduler jobs видны в system_log.
  Verify: дождаться daily_alert (18:00) или enrichment_reminder → проверить запись
  Live test: после запуска pm-bot контейнера → curl http://192.168.0.6:8000/api/v1/system-log?process_type=daily-alert
  Depends on: T-01
  Status: [✓] done
```

---

### Слой 4 — API endpoints

```
T-05 [sonnet] — Добавить API endpoints в vault_api.py
  Traces to: AC-08, AC-05, AC-10
  File: pm-bot/app/vault_api.py
  Task: Добавить 2 endpoint'а:
    1. GET /api/v1/system-log — проксирует shared.system_log.query_log()
       Query params: period (24h|7d|30d|all), process_type, status, limit (default 100), offset (default 0)
       Response: {"total": int, "entries": [...]}
    2. GET /api/v1/system-log/stats — проксирует shared.system_log.get_stats()
       Response: {"last_24h": {"total","success","warning","error","info"}, "last_error": {...}}
    Оба endpoint'а не кэшируются (данные меняются часто).
    Логирование: info на успех, error на исключение.
  Context: Паттерн из существующих endpoints (GET /api/v1/decisions, GET /api/v1/vault/health).
    Lazy import: from shared.system_log import query_log, get_stats — внутри функции.
  Acceptance criteria: AC-08 — endpoint возвращает JSON с фильтрацией и пагинацией.
  Verify: curl "http://192.168.0.6:8000/api/v1/system-log?period=24h&process_type=linter" | python -m json.tool
  Live test: запустить Docker → выполнить cron-задачу → проверить оба endpoint'а
  Depends on: T-01
  Status: [✓] done
```

---

### Слой 5 — Web UI

```
T-06 [opus] — Создать system-log.html
  Traces to: US-01, US-04, AC-01, AC-02, AC-03, AC-04, AC-05, AC-11
  File: pm-bot/web/system-log.html (новый)
  Task: Создать страницу журнала системных операций:
    1. HTML-каркас: app-sidebar (active="system-log") + search-overlay + main.page-content
    2. Метрики: 3 metric-box (TOTAL, SUCCESS, ERRORS)
    3. Фильтры: 3 select (период: 24h/7d/30d/all, тип процесса: все 11 типов, статус: success/warning/error/info) + кнопка Сброс
    4. Список записей: группировка по дням (СЕГОДНЯ / ВЧЕРА / DD.MM.YYYY)
    5. Каждая запись: [HH:MM] ● process-type — summary
       Цвет dot: success=зелёный, warning=оранжевый, error=красный, info=cyan
    6. Expand по клику: duration, source, details_json (key-value пары)
       Для process-queue: provider_chain, final_provider
    7. Пагинация: кнопка [LOAD MORE]
    8. Фильтры синхронизируются с URL query params (history.replaceState)
       Прямой переход system-log.html?status=error&period=24h применяет фильтры
    9. Refresh-кнопка в header (без auto-refresh)
    10. Loading/error/empty states
    11. Dual-theme: CSS через var(--border), var(--cyan), var(--card) и т.д.
  Context: Паттерн из decisions.html — Vue 3 Composition API, ES5 синтаксис (var, function(), без стрелок).
    registerComponents(app) → applyPageTheme().then(mount).
    CSS-классы: syslog-* (syslog-entry, syslog-filters, syslog-dot, syslog-details).
    Цвета статусов — design.md секция 5.3.
    Scripts: vue@3, api.js, components.js, inline setup.
  Acceptance criteria:
    AC-01 — все выполнения отображаются в хронологическом порядке.
    AC-05 — фильтрация по type, status, period с отражением в URL.
    AC-11 — dual-theme matrix + light.
  Verify: открыть http://192.168.0.6:8080/system-log.html в браузере
  Live test: запустить Docker → дождаться cron → открыть страницу → проверить отображение,
    переключить тему → проверить визуал, применить фильтры → проверить URL
  Depends on: T-05
  Status: [✓] done
```

```
T-07 [sonnet] — Добавить функции в api.js
  Traces to: AC-08
  File: pm-bot/web/api.js
  Task: Добавить 2 метода в объект api:
    1. systemLog(params) — GET /system-log с query-param builder
       params: {period, process_type, status, limit, offset}
    2. systemLogStats() — GET /system-log/stats
    Паттерн из api.decisions() — собираем parts[], join с '&'.
  Context: Паттерн query-param builder из api.decisions() (api.js ~line 91).
  Acceptance criteria: AC-08 — Web UI получает данные через API.
  Verify: node -e "..." (не применимо, проверяется через T-06)
  Live test: открыть system-log.html → DevTools Network → убедиться в корректных запросах
  Depends on: T-05
  Status: [✓] done
```

```
T-08 [sonnet] — Добавить System Log в sidebar
  Traces to: US-01
  File: pm-bot/web/components.js
  Task: Добавить пункт в массив links (после playground, ~line 140):
    { name: 'system-log', label: 'SYSTEM LOG', href: 'system-log.html', icon: 'terminal' }
  Context: Sidebar — computed links в app-sidebar компоненте (components.js).
    active prop на каждой странице: <app-sidebar active="system-log">.
  Acceptance criteria: US-01 — навигация на страницу System Log из sidebar.
  Verify: открыть любую страницу → sidebar содержит SYSTEM LOG
  Live test: открыть overview.html → кликнуть SYSTEM LOG в sidebar → переход на system-log.html
  Depends on: T-06
  Status: [✓] done
```

```
T-09 [sonnet] — Добавить error badge на overview.html
  Traces to: US-01, AC-10
  File: pm-bot/web/overview.html
  Task: Добавить индикатор ERRORS в cmd-status-strip (~line 829):
    1. HTML: status-indicator с id="si-errors", onclick → system-log.html?status=error&period=24h
    2. JS: fetchSystemLogStats() — GET /api/v1/system-log/stats → обновить errors-count и errors-dot
       dot-offline (красный) если count > 0, dot-online (зелёный) если 0
    3. Вызывать fetchSystemLogStats() в цикле обновления (каждые 30 сек, вместе с fetchSystemStatus)
  Context: cmd-status-strip (overview.html ~line 807) — flex row с status-indicator элементами.
    Паттерн из fetchSystemStatus() — plain DOM, setIndicator, flashElement.
    fetchWithTimeout из api.js.
  Acceptance criteria: AC-10 — badge «N errors» кликабелен, ведёт на system-log.html с фильтрами.
  Verify: открыть overview.html → видеть индикатор ERRORS
  Live test: создать error-запись → обновить overview → badge показывает count → клик → переход
  Depends on: T-05
  Status: [✓] done
```

---

### Слой 6 — Cleanup и финализация

```
T-10 [sonnet] — Добавить cleanup в init_db и ke-cron
  Traces to: AC-09
  File: shared/system_log.py, knowledge-engine/app/cli.py
  Task:
    1. В init_db() после создания таблицы вызывать cleanup_old(90)
    2. В cli.py команда health (--save, cron 04:00) — добавить вызов cleanup_old(90) после основной логики
       Это обеспечивает ежедневную ротацию (health запускается в 04:00).
  Context: Паттерн из enrichment_db.py — cleanup_old(keep_days=90) есть, но не вызывается.
    Наш модуль не повторит эту ошибку. Два уровня защиты: при init + в cron.
  Acceptance criteria: AC-09 — записи старше 90 дней удаляются.
  Verify: создать запись с timestamp 100 дней назад → cleanup_old() → запись удалена
  Live test: docker exec ke-cron python -c "from shared.system_log import cleanup_old; print(cleanup_old())"
  Depends on: T-01, T-03
  Status: [✓] done
```

```
T-11 [haiku] — Обновить index.md
  Traces to: —
  File: index.md
  Task: Обновить index.md:
    1. Добавить shared/system_log.py в таблицу shared/ модулей
    2. Добавить system-log.html в таблицу Web UI страниц
    3. Добавить GET /api/v1/system-log и /system-log/stats в описание vault_api.py
    4. Обновить версии компонентов: shared, pm-bot, knowledge-engine, web-ui
    5. Добавить docs/system-activity-log/ в таблицу документации
  Context: index.md — живая документация проекта (обновляется при каждом изменении).
  Acceptance criteria: index.md отражает текущее состояние проекта.
  Verify: прочитать index.md → убедиться в наличии всех новых элементов
  Live test: не применимо (документация)
  Depends on: T-01..T-10
  Status: [✓] done
```

---

## Граф зависимостей

```
T-01 (shared/system_log.py)
 ├── T-02 (тесты)
 ├── T-03 (KE CLI интеграция)
 ├── T-04 (pm-bot scheduler интеграция)
 ├── T-05 (API endpoints)
 │    ├── T-06 (system-log.html)
 │    │    └── T-08 (sidebar)
 │    ├── T-07 (api.js)
 │    └── T-09 (overview badge)
 └── T-10 (cleanup)
      └── T-11 (index.md)
 └── T-12 (LLM trace)
 └── T-13 (process-queue per-unit)
 └── T-14 (UI filter)
```

---

### Слой 7 — LLM trace + per-unit details (дополнение 30.06.2026)

```
T-12 [opus] — Автоматический LLM trace в call_detailed()
  Traces to: BL-143 остаток (LLM trace)
  File: shared/llm_client.py (call_detailed), shared/system_log.py (VALID_PROCESS_TYPES)
  Task: Добавить автоматическое логирование каждого LLM-вызова в system_log.
    - Новый process_type "llm-call" в VALID_PROCESS_TYPES
    - Таймер monotonic_ns в начале call_detailed()
    - На success: log_event(llm-call, success, "{operation} via {provider}", details={operation, group, chain, used, fallback_count, errors, output_len})
    - На all-fail: log_event(llm-call, error, "{operation}: all providers failed", details={...})
    - Обёрнуто в try/except pass — логирование не ломает LLM-вызовы
  Context: call_detailed() — единая точка входа для LLM-вызовов, call() и call_with_fallback() делегируют в неё.
  Depends on: T-01
  Status: [✓] done
```

```
T-13 [opus] — Per-unit details в process-queue LoggedProcess
  Traces to: BL-143 остаток (meeting queue интеграция)
  File: knowledge-engine/app/cli.py (process-queue command)
  Task: Расширить LoggedProcess.details результатами по каждому юниту:
    - units: [{unit_id, result, error?}, ...]
    - summary с количеством юнитов
  Context: process_pending() возвращает details list с per-unit результатами, ранее не прокидывался.
  Depends on: T-03
  Status: [✓] done
```

```
T-14 [opus] — Фильтр llm-call в system-log.html
  Traces to: BL-143 остаток (UI)
  File: pm-bot/web/system-log.html
  Task: Добавить <option value="llm-call">llm-call</option> в select process type.
  Depends on: T-06
  Status: [✓] done
```

## Параллелизация

```
Phase A: T-01
Phase B: T-02 [P] T-03 [P] T-04 [P] T-05 [P]
Phase C: T-06 [P] T-07 [P] T-09 [P] T-10
Phase D: T-08
Phase E: T-11
```

---

## Итого

| Метрика | Значение |
|---|---|
| Задач | 11 |
| Новых файлов | 3 (shared/system_log.py, shared/tests/test_system_log.py, pm-bot/web/system-log.html) |
| Изменяемых файлов | 7 (cli.py, scheduler.py, enrichment_reminder.py, daily_alert.py, vault_api.py, components.js, overview.html, api.js, index.md) |
| Агенты | opus: 2, sonnet: 8, haiku: 1 |
