# BL-235 — Technical Design

## Архитектура изменений

Фича затрагивает 3 слоя: хранение (user-prefs), чтение (3 потребителя), UI (settings.html).

### 1. Хранение — user-prefs

**Новое поле** в `UserPrefs` (vault_api.py):
```python
business_context: str = ""
```

**GET /api/v1/user-prefs** — seed из файла:
- Если `business_context` пуст в prefs → читаем `wiki/concepts/business-context-brief.md`, strip frontmatter, возвращаем как значение поля.
- Если задан — возвращаем as-is.

**PUT /api/v1/user-prefs** — сохранение:
- Поле `business_context` сохраняется без валидации (произвольный текст).
- Merge-only (не затирает остальные поля, аналогично существующим).

### 2. Потребители — 3 точки чтения

#### 2.1 vault_api.py — AI-agent chat (pm-bot)
- `_load_business_context_file()` → заменить на чтение из user-prefs с fallback на файл.
- pm-bot имеет прямой доступ к файлу prefs, дополнительный HTTP-запрос не нужен.

#### 2.2 signal_orchestrator.py — KE
- `_load_business_context()` → заменить на чтение из user-prefs через HTTP API (PM_BOT_API_URL, паттерн BUG-036).
- Fallback: если HTTP недоступен или поле пустое — читать из файла (текущая логика).
- Кэш per-run сохраняется (self._business_context).

#### 2.3 research_runner.py — KE
- `_collect_context()` → аналогично: HTTP API → fallback на файл.

### 3. Вспомогательная функция — shared

Чтобы не дублировать HTTP-логику в двух модулях KE, добавить функцию в общий scope KE:
```python
# В signal_orchestrator.py или отдельный хелпер
def _fetch_business_context_from_api() -> str | None:
    """GET /api/v1/user-prefs → business_context field. None если недоступен."""
```

Или проще: использовать существующую `_load_llm_prefs()` из shared/llm_client.py — она уже умеет GET /api/v1/user-prefs с TTL-кэшем (60с). Достаточно читать поле `business_context` из результата.

**Решение:** использовать `_load_llm_prefs()` — минимум нового кода, TTL-кэш уже есть.

### 4. UI — settings.html

Новая секция **BUSINESS CONTEXT** между AI AGENT и FALLBACK CHAINS:
```html
<!-- BUSINESS CONTEXT -->
<div class="settings-section">
  <div class="settings-section-title">// BUSINESS CONTEXT</div>
  <div class="provider-config-block">
    <div class="provider-config-header">ОПИСАНИЕ БИЗНЕСА ДЛЯ LLM-ПРОМПТОВ</div>
    <div class="field-group">
      <textarea v-model="businessContext" rows="8"
                class="bc-textarea"
                placeholder="Опишите ваш бизнес, продукт, целевую аудиторию...">
      </textarea>
    </div>
    <div class="field-note">
      Этот текст подставляется в промпты News Moderator, Research Runner и AI-агента.
      Чем точнее описание — тем релевантнее результаты анализа.
    </div>
    <button class="action-btn" @click="saveBusinessContext">SAVE</button>
  </div>
</div>
```

Vue-данные:
- `businessContext: ""` — загружается из GET user-prefs при mount.
- `saveBusinessContext()` — PUT user-prefs с полем `business_context`.

CSS:
- `.bc-textarea` — стили textarea (monospace, ширина 100%, theme-aware).

### 5. Data flow

```
[Settings UI] --PUT user-prefs--> [vault_api.py] --write--> [.pm-user-prefs.json]
                                                                   |
                                              ┌────────────────────┤
                                              │ (file, pm-bot)     │ (HTTP API, KE)
                                              ▼                    ▼
                                    [AI-agent chat]    [signal_orchestrator]
                                                       [research_runner]
```

### 6. Безопасность и edge cases

- **Max length**: не ограничиваем (бизнес-описание может быть 2-3 абзаца).
- **XSS**: textarea → JSON → template.replace() → LLM prompt. Не рендерится как HTML, XSS-вектора нет.
- **Пустое значение**: допустимо, промпт получит пустую строку (текущее поведение при отсутствии файла).
- **Обратная совместимость**: файл `business-context-brief.md` остаётся как fallback. Если user-prefs не содержит поле — всё работает как раньше.
