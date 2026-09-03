# BL-197 — Task Breakdown: Управление промптами через Settings UI

**Дата:** 03.09.2026
**Требования:** [requirements.md](./requirements.md)
**Дизайн:** [design.md](./design.md)

---

## Группа 1: Backend Knowledge Engine [P — параллельно с Группой 2]

```
T-01 [sonnet] — Создать prompt_registry.py для KE
  Traces to: US-01, AC-01
  File: knowledge-engine/app/prompt_registry.py (НОВЫЙ)
  Task: Создать файл с PROMPT_REGISTRY — словарь метаданных для всех 24 промптов KE.
        Каждая запись: {name: {description: str, variables: list[str]}}.
        Данные из requirements.md раздел 1.5 "knowledge-engine (24 файла)".
        Пример:
          "enrich": {"description": "Обогащение идей связями", "variables": []},
          "signal_score": {"description": "Скоринг новостей", "variables": ["business_context", "memory_context", "news_item"]},
        Добавить логирование при импорте модуля: logger.info("prompt_registry loaded: %d entries", len(PROMPT_REGISTRY))
  Context: Реестр используется endpoint'ами GET /api/v1/prompts для формирования response с description и variables.
           Промпт-файлы лежат в knowledge-engine/app/prompts/*.txt (24 файла).
  Depends on: none
  Verify: python -c "from app.prompt_registry import PROMPT_REGISTRY; assert len(PROMPT_REGISTRY) == 24; print('OK')"
  Live test: нет (data-only модуль)
  Status: [✓] done — 03.09.2026
```

```
T-02 [sonnet] — Startup defaults для KE промптов
  Traces to: US-04, AC-06
  File: knowledge-engine/app/api.py
  Task: В startup event KE api.py добавить создание *.txt.default файлов.
        При запуске для каждого .txt файла в prompts_dir — если .txt.default
        не существует, копировать через shutil.copy2().
        Код:
          import shutil
          prompts_dir = pathlib.Path(__file__).parent / "prompts"
          for txt_file in prompts_dir.glob("*.txt"):
              default_file = txt_file.with_suffix(".txt.default")
              if not default_file.exists():
                  shutil.copy2(txt_file, default_file)
                  logger.info("Created default backup: %s", default_file.name)
        Добавить в существующий startup event (если есть) или создать новый @app.on_event("startup").
  Context: KE api.py (1766 строк). Startup event нужно найти — может быть уже определён.
           Файлы .txt.default используются для операции RESET (T-05) и для определения is_modified.
  Depends on: none
  Verify: pytest knowledge-engine/tests/ -k "startup" --no-header -q
  Live test: запустить KE → проверить ls knowledge-engine/app/prompts/*.default — должно быть 24 файла
  Status: [✓] done — 03.09.2026
```

```
T-03 [sonnet] — Функция invalidate_prompt_cache в signal_moderator.py
  Traces to: US-02, AC-04
  File: knowledge-engine/app/signal_moderator.py
  Task: Добавить публичную функцию invalidate_prompt_cache() после строки 19
        (_prompt_cache определение). Сигнатура:
          def invalidate_prompt_cache(name: str | None = None) -> list[str]:
        Если name указан — удалить конкретный ключ из _prompt_cache.
        Если name=None — очистить весь кэш.
        Вернуть список invalidated ключей.
        Логирование: logger.info на каждый вызов с количеством очищенных записей.
        Код из design.md раздел 4.2.
  Context: _prompt_cache (строка 19) — module-level dict, кэширует промпты навсегда.
           _load_prompt() (строка 73) читает из кэша если есть, иначе с диска.
           Функция invalidate вызывается из endpoint POST /api/v1/prompts/{name} (T-04).
  Depends on: none
  Verify: pytest knowledge-engine/tests/ -k "invalidate" --no-header -q
  Live test: curl POST /api/v1/prompts/signal_score → проверить логи KE на "invalidate_prompt_cache"
  Status: [✓] done — 03.09.2026
```

```
T-04 [opus] — Prompt endpoints в KE api.py (GET + POST save + POST reset)
  Traces to: US-01, US-02, US-04, AC-01, AC-03, AC-04, AC-06, AC-07
  File: knowledge-engine/app/api.py
  Task: Добавить 3 endpoint'а в конец api.py (перед if __name__):

        1. Вспомогательные функции (в начале файла после импортов):
           - import re, shutil
           - from app.prompt_registry import PROMPT_REGISTRY
           - from app.signal_moderator import invalidate_prompt_cache
           - _PROMPT_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
           - MAX_PROMPT_SIZE = 50 * 1024
           - Pydantic model: PromptSaveRequest(content: str = Field(..., max_length=MAX_PROMPT_SIZE))
           - _validate_prompt_name(name) — regex check, raise HTTPException(400)
           - _safe_prompt_path(name, prompts_dir) — resolve + проверка внутри prompts_dir
           - _is_modified(prompt_path) — сравнение .txt с .txt.default

        2. GET /api/v1/prompts — возвращает все 24 промпта с metadata из PROMPT_REGISTRY.
           Response: {"prompts": [{name, description, content, lines, variables, is_modified}, ...]}

        3. POST /api/v1/prompts/{name} — сохраняет промпт на диск.
           Валидация name, проверка размера, запись файла.
           После записи: invalidate_prompt_cache(name).
           Response: {status, name, lines, is_modified, cache_invalidated: true}

        4. POST /api/v1/prompts/{name}/reset — сбрасывает к дефолту.
           Читает .txt.default, перезаписывает .txt.
           После записи: invalidate_prompt_cache(name).
           Response: {status, name, content, lines, is_modified: false, cache_invalidated: true}

        Логирование: info на каждый вызов endpoint'а, error на ошибки.
  Context: api.py уже содержит ~1766 строк. Endpoint'ы добавляются в конец.
           prompts_dir = pathlib.Path(__file__).parent / "prompts" (уже используется в файле).
           Формат response из design.md раздел 2.2.
  Depends on: T-01 (prompt_registry), T-02 (defaults), T-03 (invalidate_cache)
  Verify: pytest knowledge-engine/tests/ -k "prompt" --no-header -q
  Live test: |
    curl http://localhost:8001/api/v1/prompts → 200, 24 промпта
    curl -X POST http://localhost:8001/api/v1/prompts/signal_score -H "Content-Type: application/json" -d '{"content":"test"}' → 200
    curl -X POST http://localhost:8001/api/v1/prompts/signal_score/reset → 200, is_modified=false
    curl -X POST http://localhost:8001/api/v1/prompts/../etc/passwd -H "Content-Type: application/json" -d '{"content":"x"}' → 400
  Status: [✓] done — 03.09.2026
```

---

## Группа 2: Backend Idea Pipeline [P — параллельно с Группой 1]

```
T-05 [sonnet] — Создать prompt_registry.py для pipeline
  Traces to: US-01, AC-01
  File: idea-pipeline/app/prompt_registry.py (НОВЫЙ)
  Task: Создать файл с PROMPT_REGISTRY — словарь метаданных для 3 промптов pipeline.
        Записи:
          "analyst": {"description": "System prompt аналитика", "variables": []},
          "pm": {"description": "System prompt PM-агента", "variables": []},
          "decomposer": {"description": "System prompt декомпозера", "variables": []},
        Добавить логирование при импорте: logger.info("prompt_registry loaded: %d entries", len(PROMPT_REGISTRY))
  Context: Промпт-файлы: idea-pipeline/app/prompts/analyst.txt, pm.txt, decomposer.txt.
           AgentConfig.prompt_file содержит путь "prompts/analyst.txt" и т.д.
  Depends on: none
  Verify: python -c "from app.prompt_registry import PROMPT_REGISTRY; assert len(PROMPT_REGISTRY) == 3; print('OK')"
  Live test: нет (data-only модуль)
  Status: [✓] done — 03.09.2026
```

```
T-06 [sonnet] — Startup defaults для pipeline промптов
  Traces to: US-04, AC-06
  File: idea-pipeline/app/api.py
  Task: В существующий startup event (строка 35-49, @app.on_event("startup"))
        добавить создание *.txt.default файлов перед инициализацией оркестратора.
        Код аналогичен T-02:
          prompts_dir = Path(__file__).parent / "prompts"
          for txt_file in prompts_dir.glob("*.txt"):
              default_file = txt_file.with_suffix(".txt.default")
              if not default_file.exists():
                  shutil.copy2(txt_file, default_file)
                  logger.info("Created default backup: %s", default_file.name)
        Добавить import shutil в начало файла.
  Context: startup() уже существует на строке 35. Добавить ДО строки 45
           (инициализации _orchestrator), чтобы defaults были готовы до старта агентов.
  Depends on: none
  Verify: pytest idea-pipeline/tests/ -k "startup" --no-header -q
  Live test: запустить pipeline → проверить ls idea-pipeline/app/prompts/*.default — должно быть 3 файла
  Status: [✓] done — 03.09.2026
```

```
T-07 [sonnet] — Метод reload_prompt() в BaseAgent
  Traces to: US-02, AC-04
  File: idea-pipeline/app/agents/base.py
  Task: Добавить метод reload_prompt() в класс BaseAgent после _load_prompt():
          def reload_prompt(self) -> None:
              old_len = len(self.prompt)
              self.prompt = self._load_prompt()
              logger.info(
                  "Agent %s: prompt reloaded, old_len=%d, new_len=%d",
                  self.config.name, old_len, len(self.prompt),
              )
        Метод перечитывает промпт из файла и заменяет self.prompt.
        Потокобезопасность: str assignment атомарно в Python.
  Context: BaseAgent.__init__ загружает промпт один раз в self.prompt (строка 14).
           _load_prompt() (строка 16) читает файл из self.config.prompt_file.
           self.prompt используется в run() (строка 40) как system prompt для LLM.
  Depends on: none
  Verify: pytest idea-pipeline/tests/ -k "reload" --no-header -q
  Live test: curl POST /api/v1/prompts/analyst → проверить логи pipeline на "prompt reloaded"
  Status: [✓] done — 03.09.2026
```

```
T-08 [sonnet] — Метод reload_agents() в PipelineOrchestrator
  Traces to: US-02, AC-04
  File: idea-pipeline/app/orchestrator.py
  Task: Добавить метод reload_agents() в класс PipelineOrchestrator
        (после __init__, перед is_running):
          def reload_agents(self) -> list[str]:
              reloaded = []
              for name, agent in [
                  ("analyst", self.analyst),
                  ("pm", self.pm_agent),
                  ("decomposer", self.decomposer),
              ]:
                  agent.reload_prompt()
                  reloaded.append(name)
              logger.info("reload_agents: reloaded %s", reloaded)
              return reloaded
        Вызывает reload_prompt() для каждого из 3 агентов.
  Context: Агенты создаются в __init__ (строки 33-35): self.analyst, self.pm_agent, self.decomposer.
           Метод вызывается из endpoint POST /api/v1/prompts/{name} и POST /api/v1/reload-agents (T-09).
  Depends on: T-07 (reload_prompt в BaseAgent)
  Verify: pytest idea-pipeline/tests/ -k "reload" --no-header -q
  Live test: curl POST /api/v1/reload-agents → {"agents_reloaded": ["analyst", "pm", "decomposer"]}
  Status: [✓] done — 03.09.2026
```

```
T-09 [opus] — Prompt endpoints в pipeline api.py (GET + POST save + POST reset + reload)
  Traces to: US-01, US-02, US-04, AC-01, AC-03, AC-04, AC-06, AC-07
  File: idea-pipeline/app/api.py
  Task: Добавить 4 endpoint'а в api.py:

        1. Вспомогательные функции (после импортов):
           - import re, shutil
           - from app.prompt_registry import PROMPT_REGISTRY
           - _PROMPT_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
           - MAX_PROMPT_SIZE = 50 * 1024
           - Pydantic model: PromptSaveRequest(content: str = Field(..., max_length=MAX_PROMPT_SIZE))
           - _validate_prompt_name(name), _safe_prompt_path(name, prompts_dir), _is_modified(prompt_path)
           - (аналогично T-04, но для pipeline prompts_dir)

        2. GET /api/v1/prompts — возвращает 3 промпта с metadata.

        3. POST /api/v1/prompts/{name} — сохраняет промпт + _orchestrator.reload_agents().
           Response включает agents_reloaded: true.

        4. POST /api/v1/prompts/{name}/reset — сбрасывает к дефолту + reload.

        5. POST /api/v1/reload-agents — принудительная перезагрузка всех агентов.
           Response: {status: "ok", agents_reloaded: ["analyst", "pm", "decomposer"]}

        prompts_dir = Path(__file__).parent / "prompts"
        Использовать глобальный _orchestrator (уже определён на строке 31).
        Логирование: info на каждый endpoint.
  Context: api.py содержит 313 строк. _orchestrator инициализируется в startup() (строка 45).
           _orchestrator может быть None до startup — endpoint'ы вернут 503 если None.
  Depends on: T-05 (prompt_registry), T-06 (defaults), T-07 (reload_prompt), T-08 (reload_agents)
  Verify: pytest idea-pipeline/tests/ -k "prompt" --no-header -q
  Live test: |
    curl http://localhost:8100/api/v1/prompts → 200, 3 промпта
    curl -X POST http://localhost:8100/api/v1/prompts/analyst -H "Content-Type: application/json" -d '{"content":"test"}' → 200
    curl -X POST http://localhost:8100/api/v1/prompts/analyst/reset → 200
    curl -X POST http://localhost:8100/api/v1/reload-agents → 200, agents_reloaded
  Status: [✓] done — 03.09.2026
```

---

## Группа 3: Backend pm-bot

```
T-10 [sonnet] — Создать prompt_registry.py для pm-bot
  Traces to: US-01, AC-01
  File: pm-bot/app/prompt_registry.py (НОВЫЙ)
  Task: Создать файл с PROMPT_REGISTRY — словарь метаданных для 5 промптов pm-bot.
        Записи (из requirements.md раздел 1.5):
          "idea": {"description": "Обработка идей из Telegram", "variables": []},
          "meeting": {"description": "Обработка транскриптов встреч", "variables": []},
          "daily": {"description": "Обработка daily-заметок", "variables": []},
          "jira_ticket": {"description": "Генерация Jira-черновиков", "variables": []},
          "weekly_report": {"description": "Еженедельный отчёт", "variables": []},
        Логирование при импорте.
  Context: Промпт-файлы: pm-bot/app/prompts/*.txt (5 файлов: idea, meeting, daily, jira_ticket, weekly_report).
  Depends on: none
  Verify: python -c "from app.prompt_registry import PROMPT_REGISTRY; assert len(PROMPT_REGISTRY) == 5; print('OK')"
  Live test: нет (data-only модуль)
  Status: [✓] done — completed: 03.09.2026
```

```
T-11 [sonnet] — Startup defaults для pm-bot промптов
  Traces to: US-04, AC-06
  File: pm-bot/app/vault_api.py
  Task: В startup event pm-bot (если существует) или создать новый — добавить
        создание *.txt.default файлов для pm-bot промптов.
        Код аналогичен T-02 и T-06.
        prompts_dir = Path(__file__).parent / "prompts"
        Добавить import shutil если отсутствует.
  Context: vault_api.py — 5541 строк. Найти существующий startup event или создать.
           pm-bot промпты читаются с диска каждый раз (hot-reload бесплатный),
           но .txt.default нужны для is_modified и RESET.
  Depends on: none
  Verify: pytest pm-bot/tests/ -k "startup or default" --no-header -q
  Live test: запустить pm-bot → проверить ls pm-bot/app/prompts/*.default — должно быть 5 файлов
  Status: [✓] done — 03.09.2026
```

```
T-12 [sonnet] — Создать pipeline_client.py
  Traces to: US-01, US-02, US-04, AC-01, AC-03, AC-06
  File: pm-bot/app/pipeline_client.py (НОВЫЙ)
  Task: Создать HTTP-клиент для idea-pipeline API. Структура аналогична ke_client.py.
        Содержимое:
          - PIPELINE_API_URL = os.getenv("PIPELINE_API_URL", "http://idea-pipeline:8100")
          - _get_timeout(operation) — из shared.settings
          - _post(path, timeout, json) — POST с raise_for_status() и логированием
          - _get(path, timeout, params) — GET с raise_for_status() и логированием
          - get_prompts() -> dict — GET /api/v1/prompts
          - save_prompt(name, content) -> dict — POST /api/v1/prompts/{name}
          - reset_prompt(name) -> dict — POST /api/v1/prompts/{name}/reset
        Полный код в design.md раздел 7.2.
        Логирование каждого вызова: logger.info на вход и результат.
  Context: ke_client.py (392 строки) — шаблон для pipeline_client.py.
           PIPELINE_API_URL уже определён в docker-compose.yml (строка 35):
           PIPELINE_API_URL=http://idea-pipeline:8100.
           Pipeline доступен внутри Docker-сети на порту 8100.
  Depends on: none
  Verify: python -c "import pm_bot.app.pipeline_client as pc; print('imported OK')"
  Live test: curl http://localhost:8100/api/v1/prompts (прямой запрос к pipeline для проверки)
  Status: [✓] done
  Completed: 03.09.2026
```

```
T-13 [sonnet] — Добавить prompt-функции в ke_client.py
  Traces to: US-01, US-02, US-04, AC-01, AC-03, AC-06
  File: pm-bot/app/ke_client.py
  Task: Добавить 3 функции в конец ke_client.py (после signal_approve, строка 392):

        # ---------------------------------------------------------------------------
        # 33. GET /api/v1/prompts
        # ---------------------------------------------------------------------------
        def get_prompts() -> dict:
            """Get all KE prompts."""
            logger.info("get_prompts: fetching KE prompts")
            return _get("/api/v1/prompts", _get_timeout("default"))

        # ---------------------------------------------------------------------------
        # 34. POST /api/v1/prompts/{name}
        # ---------------------------------------------------------------------------
        def save_prompt(name: str, content: str) -> dict:
            """Save a KE prompt by name."""
            logger.info("save_prompt: name=%s, content_len=%d", name, len(content))
            return _post(f"/api/v1/prompts/{name}", _get_timeout("default"),
                         json={"content": content})

        # ---------------------------------------------------------------------------
        # 35. POST /api/v1/prompts/{name}/reset
        # ---------------------------------------------------------------------------
        def reset_prompt(name: str) -> dict:
            """Reset a KE prompt to default."""
            logger.info("reset_prompt: name=%s", name)
            return _post(f"/api/v1/prompts/{name}/reset", _get_timeout("default"))
  Context: ke_client.py — 393 строки, 32 функции. Использует _get() и _post() хелперы (строки 23-43).
           _get_timeout() (строка 18) получает таймаут из shared.settings.
  Depends on: none (клиентские функции, не зависят от KE endpoint'ов для компиляции)
  Verify: python -c "from app.ke_client import get_prompts, save_prompt, reset_prompt; print('OK')"
  Live test: запустить pm-bot + KE → из pm-bot контейнера вызвать ke_client.get_prompts() → ожидать 24 промпта
  Status: [✓] done — 03.09.2026
```

```
T-14 [opus] — Агрегирующие prompt endpoints в vault_api.py
  Traces to: US-01, US-02, US-04, AC-01, AC-02, AC-03, AC-06, AC-07
  File: pm-bot/app/vault_api.py
  Task: Добавить новые endpoint'ы ПЕРЕД секцией "# Settings" (строка 2620).

        1. Импорты (в начале файла):
           - import re, shutil
           - from app.prompt_registry import PROMPT_REGISTRY
           - from app import pipeline_client
           (ke_client уже импортирован)

        2. Константы:
           - _PROMPT_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
           - _VALID_COMPONENTS = frozenset({"pm-bot", "knowledge-engine", "idea-pipeline"})
           - MAX_PROMPT_SIZE = 50 * 1024
           - Pydantic model: PromptSaveRequest(content: str = Field(..., max_length=MAX_PROMPT_SIZE))

        3. Вспомогательные функции:
           - _validate_prompt_name(name) — regex, raise HTTPException(400)
           - _validate_component(component) — in _VALID_COMPONENTS, raise HTTPException(400)
           - _safe_prompt_path(name, prompts_dir) — resolve + parent check
           - _is_modified(prompt_path) — сравнение .txt vs .txt.default
           - _get_pmbot_prompts() — читает локальные pm-bot промпты с metadata из PROMPT_REGISTRY

        4. GET /api/v1/prompts/all — агрегация из 3 компонентов:
           - pm-bot: локально через _get_pmbot_prompts()
           - KE: через ke_client.get_prompts() с try/except
           - pipeline: через pipeline_client.get_prompts() с try/except
           Response: {"pm-bot": {status, prompts}, "knowledge-engine": {status, prompts}, "idea-pipeline": {status, prompts}}
           При ошибке компонента: status="error", error=str(exc), prompts=[] (AC-02)

        5. POST /api/v1/prompts/{component}/{name} — роутинг по component:
           - pm-bot: запись локально, _is_modified
           - knowledge-engine: ke_client.save_prompt(name, content)
           - idea-pipeline: pipeline_client.save_prompt(name, content)
           Валидация component + name перед роутингом (AC-07).
           При ошибке сервиса: HTTPException(502, detail=f"{component} service unavailable")

        6. POST /api/v1/prompts/{component}/{name}/reset — роутинг аналогично:
           - pm-bot: копия .default → .txt, вернуть новый content
           - knowledge-engine: ke_client.reset_prompt(name)
           - idea-pipeline: pipeline_client.reset_prompt(name)

        Логирование: info каждого endpoint'а с параметрами и результатом.
  Context: vault_api.py — 5541 строк. ke_client уже импортируется.
           pipeline_client.py создаётся в T-12. PROMPT_REGISTRY в T-10.
           Startup defaults для pm-bot в T-11.
           Формат response из design.md раздел 2.1.
  Depends on: T-10 (pm-bot registry), T-11 (pm-bot defaults), T-12 (pipeline_client), T-13 (ke_client prompts)
  Verify: pytest pm-bot/tests/ -k "prompt" --no-header -q
  Live test: |
    curl http://localhost:8000/api/v1/prompts/all → 200, 3 группы
    curl -X POST http://localhost:8000/api/v1/prompts/pm-bot/idea -H "Content-Type: application/json" -d '{"content":"test"}' → 200
    curl -X POST http://localhost:8000/api/v1/prompts/pm-bot/idea/reset → 200
    curl -X POST http://localhost:8000/api/v1/prompts/invalid-component/test → 400
    curl -X POST http://localhost:8000/api/v1/prompts/pm-bot/../etc/passwd → 400
  Status: [✓] done (03.09.2026)
```

```
T-15 [sonnet] — Убрать промпты из GET/POST /api/v1/settings
  Traces to: US-02 (чистка)
  File: pm-bot/app/vault_api.py
  Task: Модифицировать существующие settings endpoints (строки 2623-2702):

        1. SettingsModel (строка 2623): удалить поле prompts: dict = {}

        2. GET /api/v1/settings (строка 2629): убрать "prompts": {} из settings dict,
           убрать блок чтения промпт-файлов (строки 2640-2657),
           убрать лог "returning %d prompts".

        3. POST /api/v1/settings (строка 2665): убрать блок итерации по settings.prompts (строки 2673-2698),
           убрать лог "saved %d prompts". Endpoint теперь ничего не сохраняет (roadmap labels
           сохраняются через user-prefs). Оставить endpoint для обратной совместимости,
           но тело сократить до return {"status": "ok"}.

        Это breaking change для фронтенда — settings.html перестаёт использовать промпты
        из settings (заменяется на /api/v1/prompts/all в T-16).
  Context: Текущий GET /api/v1/settings возвращает промпты pm-bot как {prompts: {name: content}}.
           POST /api/v1/settings принимает prompts dict и сохраняет файлы.
           Кнопка SAVE внизу settings.html вызывает saveSettings() → POST /api/v1/settings.
           После T-15 + T-16 промпты управляются через отдельные endpoints.
  Depends on: T-14 (новые prompt endpoints готовы)
  Verify: pytest pm-bot/tests/ -k "settings" --no-header -q
  Live test: |
    curl http://localhost:8000/api/v1/settings → 200, НЕТ поля "prompts"
    curl -X POST http://localhost:8000/api/v1/settings -H "Content-Type: application/json" -d '{}' → 200
  Status: [✓] done — 03.09.2026
```

---

## Группа 4: Frontend

```
T-16 [opus] — Переработка секции PROMPTS в settings.html
  Traces to: US-01, US-02, US-03, US-04, AC-01, AC-02, AC-03, AC-05, AC-06
  File: pm-bot/web/settings.html
  Task: Полная переработка секции PROMPTS (строки 603-610) и JS-логики.

        ### HTML (заменить строки 603-610):
        Accordion-дерево с 3 группами. Каждая группа:
          - Заголовок с именем компонента, счётчик промптов, chevron для свёртки
          - При ошибке компонента: alert "Сервис недоступен" (AC-02)
          - Список промптов: каждый промпт — collapsible item:
            - Header: имя файла (NAME.TXT), описание, badge строк, badge "modified" если is_modified
            - Body (раскрывается по клику): textarea с содержимым
            - Variable badges ПОД textarea: [variable_name] для каждой переменной
            - Кнопки SAVE и RESET (RESET только если is_modified)

        ### CSS (все классы с prefix prompt-):
        - .prompt-group, .prompt-group-header, .prompt-group-count
        - .prompt-item, .prompt-item-header, .prompt-item-name, .prompt-item-desc
        - .prompt-item-lines (badge), .prompt-item-modified (badge "modified")
        - .prompt-editor (textarea — monospace, min-height 200px)
        - .prompt-var-badge (inline badge для переменных)
        - .prompt-actions (кнопки SAVE/RESET)
        - .prompt-error (ошибка сервиса)
        Стили интегрировать в <style> секцию settings.html.
        Учитывать оба theme: matrix (тёмная) и light.

        ### JavaScript (в setup()):
        Новые ref'ы:
          - promptGroups = ref([])
          - promptsLoading = ref(true)
          - promptSaving = ref({})     // {component/name: true}
          - promptExpanded = ref({})   // {component/name: true}

        Функции:
          - loadPrompts() — GET /api/v1/prompts/all → заполнить promptGroups
          - savePrompt(component, name) — POST /api/v1/prompts/{component}/{name}
            Toast success/error. Обновить is_modified, lines в UI.
          - resetPrompt(component, name) — confirm() → POST .../reset
            Toast success/error. Обновить content, is_modified в UI.
          - togglePromptGroup(component) — свернуть/развернуть группу
          - togglePromptItem(component, name) — свернуть/развернуть промпт
          - isPromptDirty(component, name) — текущий content != original (unsaved changes)
          Код из design.md раздел 5.6.

        Вызвать loadPrompts() в onMounted (рядом с loadSettings).

        Убрать поле prompts из reactive settings (строка 637):
          settings.prompts = {} → удалить эту строку.

        Модифицировать saveSettings() (строка 866): убрать промпты из body.
        Обновить статус после save: "SAVED" без "(N prompts)".

        Return: добавить новые ref'ы и функции в return.

  Context: settings.html — большой файл. Секция PROMPTS сейчас простая (строки 603-610).
           JS setup() начинается на строке 630. Return объект — найти в конце файла.
           apiFetch() определён в api.js — использовать его.
           cmd-button компонент уже определён в components.js — использовать для SAVE/RESET.
           style-light.css может переопределять стили — учитывать при создании CSS.
           Контракт данных (JSON response) из design.md раздел 2.1.
  Reference: design.md разделы 5.1-5.7
  Depends on: T-14 (агрегирующие endpoints), T-15 (очистка settings)
  Verify: запустить http-server → открыть settings.html в браузере → нет JS-ошибок
  Live test: |
    Открыть http://192.168.0.6:8080/settings.html
    1. Секция PROMPTS отображает 3 группы (pm-bot, KE, pipeline)
    2. pm-bot развёрнута по умолчанию, KE и pipeline свёрнуты
    3. Каждый промпт показывает имя, описание, badge строк
    4. По клику на промпт — textarea с содержимым
    5. Под textarea — variable badges (если есть)
    6. SAVE сохраняет (toast), RESET сбрасывает (confirm + toast)
    7. При недоступном KE/pipeline — ошибка в группе, pm-bot работает
  Status: [✓] done — 03.09.2026
```

```
T-17 [sonnet] — CSS для prompt-секции в style-light.css
  Traces to: US-01
  File: pm-bot/web/style-light.css
  Task: Добавить overrides для всех prompt- классов из T-16 в light theme.
        Основные отличия от matrix theme:
        - .prompt-group-header: фон светлый, текст тёмный
        - .prompt-item-header: hover без neon-эффектов
        - .prompt-editor: белый фон, тёмный текст, светлый border
        - .prompt-var-badge: светлый фон, синий текст
        - .prompt-item-modified: оранжевый badge на светлом фоне
        - .prompt-error: красный текст на светлом фоне
        Убедиться что все prompt- классы из T-16 имеют light-overrides.
  Context: style-light.css перебивает style.css (память: "PMA: light theme overrides base CSS").
           Если не добавить overrides — в light theme останутся тёмные стили.
  Depends on: T-16 (CSS-классы определены в settings.html)
  Verify: открыть settings.html → переключить тему на light → промпты читаемы
  Live test: |
    Открыть http://192.168.0.6:8080/settings.html
    Переключить тему на Light
    Промпты должны быть читаемы (светлый фон, тёмный текст)
  Status: [✓] done — 03.09.2026
```

---

## Группа 5: Тесты

```
T-18 [sonnet] — Unit-тесты для KE prompt endpoints
  Traces to: AC-01, AC-03, AC-04, AC-06, AC-07
  File: knowledge-engine/tests/test_prompt_api.py (НОВЫЙ)
  Task: Создать тесты для prompt endpoints KE:
        1. test_get_prompts — GET /api/v1/prompts возвращает 24 промпта с metadata
        2. test_get_prompts_structure — каждый промпт содержит name, description, content, lines, variables, is_modified
        3. test_save_prompt — POST /api/v1/prompts/enrich сохраняет и возвращает updated lines
        4. test_save_prompt_cache_invalidation — после save промпта из signal_moderator — cache_invalidated=true
        5. test_reset_prompt — POST /api/v1/prompts/enrich/reset возвращает дефолтный контент, is_modified=false
        6. test_invalid_name_rejected — name "../etc" возвращает 400
        7. test_invalid_name_regex — name "UPPER" возвращает 400
        8. test_unknown_prompt_404 — name "nonexistent" возвращает 404
        9. test_content_too_large — content > 50KB возвращает 422
        Использовать TestClient из fastapi.testclient.
        Создать tmp prompts_dir с fixture для изоляции тестов.
  Context: Существующие тесты в knowledge-engine/tests/. Формат response из design.md 2.2.
  Depends on: T-04 (KE endpoints)
  Verify: pytest knowledge-engine/tests/test_prompt_api.py -v --no-header
  Live test: нет (unit-тесты)
  Status: [✓] done — 03.09.2026 (создан агентом T-04, файл test_api_prompts.py, 19 тестов)
```

```
T-19 [sonnet] — Unit-тесты для pipeline prompt endpoints
  Traces to: AC-01, AC-03, AC-04, AC-06, AC-07
  File: idea-pipeline/tests/test_prompt_api.py (НОВЫЙ)
  Task: Создать тесты для prompt endpoints pipeline:
        1. test_get_prompts — GET /api/v1/prompts возвращает 3 промпта с metadata
        2. test_save_prompt — POST /api/v1/prompts/analyst, agents_reloaded=true
        3. test_reset_prompt — POST /api/v1/prompts/analyst/reset, is_modified=false
        4. test_reload_agents — POST /api/v1/reload-agents, agents_reloaded=["analyst", "pm", "decomposer"]
        5. test_invalid_name_rejected — 400
        6. test_unknown_prompt_404 — 404
        Мокировать _orchestrator для тестов reload.
        Использовать TestClient.
  Context: Существующие тесты в idea-pipeline/tests/. Формат response из design.md 2.3.
  Depends on: T-09 (pipeline endpoints)
  Verify: pytest idea-pipeline/tests/test_prompt_api.py -v --no-header
  Live test: нет (unit-тесты)
  Status: [✓] done — 03.09.2026 (15 тестов, 44 total passed)
```

```
T-20 [sonnet] — Unit-тесты для pm-bot prompt endpoints
  Traces to: AC-01, AC-02, AC-03, AC-06, AC-07
  File: pm-bot/tests/test_prompt_api.py (НОВЫЙ)
  Task: Создать тесты для агрегирующих prompt endpoints pm-bot:
        1. test_get_all_prompts — GET /api/v1/prompts/all возвращает 3 группы
        2. test_get_all_prompts_ke_unavailable — мок ke_client.get_prompts raises → status="error", pm-bot OK (AC-02)
        3. test_get_all_prompts_pipeline_unavailable — аналогично для pipeline (AC-02)
        4. test_save_pmbot_prompt — POST /api/v1/prompts/pm-bot/idea → 200, is_modified=true
        5. test_save_ke_prompt_proxy — POST /api/v1/prompts/knowledge-engine/enrich → проксируется в ke_client
        6. test_save_pipeline_prompt_proxy — POST /api/v1/prompts/idea-pipeline/analyst → проксируется в pipeline_client
        7. test_reset_pmbot_prompt — POST /api/v1/prompts/pm-bot/idea/reset → 200
        8. test_invalid_component — POST /api/v1/prompts/invalid/test → 400
        9. test_path_traversal — POST /api/v1/prompts/pm-bot/../etc → 400 (AC-07)
        Мокировать ke_client и pipeline_client для proxy-тестов.
        Использовать tmp prompts_dir для pm-bot промптов.
  Context: Существующие тесты в pm-bot/tests/. Формат response из design.md 2.1.
  Depends on: T-14 (pm-bot endpoints), T-15 (settings cleanup)
  Verify: pytest pm-bot/tests/test_prompt_api.py -v --no-header
  Live test: нет (unit-тесты)
  Status: [✓] done — 03.09.2026 (создан агентом T-14, файл test_prompts_endpoints.py, 28 тестов)
```

```
T-21 [sonnet] — Unit-тесты для pipeline_client.py
  Traces to: US-01
  File: pm-bot/tests/test_pipeline_client.py (НОВЫЙ)
  Task: Создать тесты для pipeline_client:
        1. test_get_prompts — мок requests.get → корректный response
        2. test_save_prompt — мок requests.post → корректный response
        3. test_reset_prompt — мок requests.post → корректный response
        4. test_connection_error — мок requests.get raises ConnectionError → пробросить исключение
        5. test_timeout — мок requests.get raises Timeout → пробросить исключение
        Использовать unittest.mock.patch для мока requests.
  Context: pipeline_client.py (T-12) аналогичен ke_client.py. Тесты ke_client если есть — шаблон.
  Depends on: T-12 (pipeline_client)
  Verify: pytest pm-bot/tests/test_pipeline_client.py -v --no-header
  Live test: нет (unit-тесты)
  Status: [✓] done — 03.09.2026 (20 тестов)
```

```
T-22 [sonnet] — Тест invalidate_prompt_cache
  Traces to: AC-04
  File: knowledge-engine/tests/test_signal_moderator.py (дополнить или создать)
  Task: Добавить тесты для invalidate_prompt_cache():
        1. test_invalidate_specific — заполнить _prompt_cache, вызвать invalidate(name) → удалён только один ключ
        2. test_invalidate_all — заполнить _prompt_cache, вызвать invalidate(None) → весь кэш пуст
        3. test_invalidate_nonexistent — вызвать invalidate("nonexistent") → вернёт [] без ошибки
        4. test_invalidate_returns_names — проверить что возвращает список invalidated имён
        Прямой доступ к _prompt_cache для setup.
  Context: signal_moderator.py, _prompt_cache (строка 19), invalidate_prompt_cache (T-03).
  Depends on: T-03 (invalidate function)
  Verify: pytest knowledge-engine/tests/test_signal_moderator.py -v --no-header -k "invalidate"
  Live test: нет (unit-тесты)
  Status: [✓] done — 03.09.2026 (4 теста, 71 total passed)
```

```
T-23 [sonnet] — Тест reload_prompt и reload_agents
  Traces to: AC-04
  File: idea-pipeline/tests/test_reload.py (НОВЫЙ)
  Task: Создать тесты для reload-механизма:
        1. test_reload_prompt_updates_content — создать агента с temp prompt file,
           изменить файл, вызвать reload_prompt() → self.prompt обновился
        2. test_reload_agents_all — создать оркестратор с 3 агентами,
           вызвать reload_agents() → возвращает ["analyst", "pm", "decomposer"]
        3. test_reload_prompt_logs — проверить что reload_prompt логирует old_len и new_len
        Мокировать AgentConfig и temp файлы.
  Context: base.py (T-07), orchestrator.py (T-08).
  Depends on: T-07 (reload_prompt), T-08 (reload_agents)
  Verify: pytest idea-pipeline/tests/test_reload.py -v --no-header
  Live test: нет (unit-тесты)
  Status: [✓] done — 03.09.2026 (8 тестов: 3 reload + 3 agents + 2 edge cases)
```

---

## Группа 6: Инфраструктура и документация

```
T-24 [sonnet] — Добавить .gitignore для *.txt.default
  Traces to: нефункциональное
  File: .gitignore (или pm-bot/.gitignore, knowledge-engine/.gitignore, idea-pipeline/.gitignore)
  Task: Добавить паттерн *.txt.default в .gitignore каждого компонента
        (или в корневой .gitignore если он един для монорепо).
        Файлы .txt.default создаются при startup и не должны коммититься.
        Также добавить комментарий: # Prompt defaults (created at startup for RESET feature)
  Context: .txt.default файлы создаются в T-02, T-06, T-11 при первом запуске контейнеров.
           Они содержат копии оригинальных промптов для операции RESET.
  Depends on: none
  Verify: git status → *.txt.default не показываются как untracked
  Live test: нет
  Status: [✓] done — 03.09.2026
```

```
T-25 [haiku] — Обновить BACKLOG.md
  Traces to: документация
  File: BACKLOG.md
  Task: Отметить BL-197 как [->] in-progress.
        Добавить подзадачи если формат бэклога это предусматривает.
  Context: BACKLOG.md в корне pm_assistant.
  Depends on: T-16 (все задачи завершены)
  Verify: grep "BL-197" BACKLOG.md
  Live test: нет
  Status: [✓] done — 03.09.2026 (BL-197 → Реализовано, счётчики обновлены)
```

```
T-26 [haiku] — Обновить CHANGELOG.md
  Traces to: документация
  File: CHANGELOG.md
  Task: Добавить запись для BL-197 в текущую версию:
        - Добавлено: управление всеми 32 промптами (pm-bot, KE, pipeline) через Settings UI
        - Добавлено: hot-reload промптов без перезапуска контейнеров
        - Добавлено: сброс промптов к дефолтной версии
        - Добавлено: pipeline_client.py для связи pm-bot с idea-pipeline
        - Изменено: промпты убраны из GET/POST /api/v1/settings (breaking change)
  Context: CHANGELOG.md в корне pm_assistant. Формат: даты DD.MM.YYYY.
  Depends on: T-25 (BACKLOG обновлён)
  Verify: grep "BL-197" CHANGELOG.md
  Live test: нет
  Status: [✓] done — 03.09.2026 (секция с 9 bullet points добавлена)
```

```
T-27 [haiku] — Обновить index.md
  Traces to: документация
  File: index.md
  Task: Обновить index.md — добавить новые файлы:
        - pm-bot/app/prompt_registry.py
        - pm-bot/app/pipeline_client.py
        - knowledge-engine/app/prompt_registry.py
        - idea-pipeline/app/prompt_registry.py
        Обновить описание модулей и счётчики файлов.
        Обновить раздел API endpoints — добавить /api/v1/prompts/*.
        Bump semver.
  Context: index.md в корне pm_assistant. Память: "bump semver in index.md after every bugfix or feature".
  Depends on: T-26 (CHANGELOG обновлён)
  Verify: grep "prompt_registry" index.md
  Live test: нет
  Status: [✓] done — 03.09.2026 (3 prompt_registry.py, versions bumped, counts updated)
```

```
T-28 [haiku] — Обновить README.md
  Traces to: документация
  File: README.md
  Task: Обновить README.md — добавить в описание Settings:
        - Секция "Управление промптами" — описание функциональности
        - Упомянуть 3 компонента, 32 промпта
        - Упомянуть hot-reload без перезапуска контейнеров
  Context: README.md в корне pm_assistant.
  Depends on: T-27 (index обновлён)
  Verify: grep -i "prompt" README.md
  Live test: нет
  Status: [✓] done — 03.09.2026 (секция Промпты + Settings UI добавлена)
```

---

## Зависимости (граф)

```
Группа 1 (KE) [P]:          Группа 2 (Pipeline) [P]:
  T-01 ─┐                     T-05 ─┐
  T-02 ─┼→ T-04                T-06 ─┤
  T-03 ─┘                     T-07 ─┼→ T-09
                               T-08 ─┘
         ↓                          ↓
      Группа 3 (pm-bot):
        T-10 ─┐
        T-11 ─┤
        T-12 ─┼→ T-14 → T-15
        T-13 ─┘
                   ↓
              Группа 4 (Frontend):
                T-16 → T-17
                   ↓
              Группа 5 (Тесты) [P]:
                T-18 (KE)
                T-19 (pipeline)
                T-20 (pm-bot)
                T-21 (pipeline_client)
                T-22 (invalidate_cache)
                T-23 (reload)
                   ↓
              Группа 6 (Docs):
                T-24 → T-25 → T-26 → T-27 → T-28
```

**Итого: 28 задач** (4 opus, 19 sonnet, 5 haiku)

**Параллелизм:**
- T-01..T-04 || T-05..T-09 (KE и pipeline независимы)
- T-18..T-23 все параллельно (тесты разных компонентов)
- T-24 можно в любой момент (gitignore)

---

## Финальный статус

**Статус: ✅ ЗАВЕРШЕНО — 04.09.2026**

- Все 28 задач выполнены (T-01..T-28)
- 94 новых теста, 0 new failures
- Pre-flight checklist: 7/7 пройдено
- Live test: все API endpoints работают, UI проверен визуально
- Hotfix: KE api.py import fix (`from app.` → `from .`)
- Commit: `2ba3d43` — 26 файлов, 2454 insertions
- Pre-existing failures: 12 (signal_memory 5, openrouter 3, transcription 4, settings 1)
