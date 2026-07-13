# BL-161: Поиск и фильтрация отчётов — Technical Design

## Architecture

Изменения затрагивают 2 файла:
- **vault_api.py** — добавить `type` в ответ `GET /api/v1/reports`
- **report.html** — UI: поисковая строка + фильтр-чипы + клиентская фильтрация

Серверная фильтрация не нужна — все ~410 отчётов уже загружаются одним запросом.
Фильтрация и поиск работают на клиенте по загруженному массиву.

## Data Model

### Изменение ответа `GET /api/v1/reports`

Текущий формат элемента:
```json
{"filename": "2026-07-13-week-29.md", "date": "2026-07-13", "title": "Еженедельный отчёт R6/R7 — неделя 29"}
```

Новый формат (добавлено поле `type`):
```json
{"filename": "2026-07-13-week-29.md", "date": "2026-07-13", "title": "...", "type": "weekly-status-report"}
```

Значение `type`:
1. Читается из YAML frontmatter файла (поле `type:`)
2. Если frontmatter отсутствует или поле `type` не найдено → `"other"`

### Парсинг frontmatter

Текущий `list_reports` уже читает весь текст файла (`f.read_text()`).
Вместо `frontmatter_utils.read_frontmatter` (тянет python-frontmatter) используем
лёгкий inline-парсинг — frontmatter в отчётах простой, без вложенных структур:

```python
def _extract_report_type(text: str) -> str:
    stripped = text.lstrip()
    if not stripped.startswith("---"):
        return "other"
    end = stripped.find("---", 3)
    if end == -1:
        return "other"
    fm_block = stripped[3:end]
    for line in fm_block.splitlines():
        if line.startswith("type:"):
            return line.split(":", 1)[1].strip().strip("'\"") or "other"
    return "other"
```

Это избегает полного YAML-парсинга для 410+ файлов и не добавляет зависимостей.

## UI Design

### Layout: левая панель (report-list-panel)

```
┌─────────────────────────────┐
│ [🔍 Поиск отчёта...     ✕] │  ← поисковая строка
├─────────────────────────────┤
│ ALL(410) sync(132) daily ..│  ← горизонтальный скролл чипов
├─────────────────────────────┤
│ REPORTS (23 из 410)         │  ← заголовок с каунтером
├─────────────────────────────┤
│ 13.07.2026                  │
│ Еженедельный отчёт...       │
│ ───────────────             │
│ 12.07.2026                  │
│ Daily Dev Report            │
│ ...                         │
└─────────────────────────────┘
```

### Поисковая строка

- Input type="text" с placeholder "Поиск отчёта..."
- Кнопка очистки (✕) появляется при наличии текста
- Debounce 200ms
- Поиск: `title.toLowerCase().includes(q)` ИЛИ `filename.toLowerCase().includes(q)`

### Фильтр-чипы

- Горизонтальная лента с `overflow-x: auto` (скролл при переполнении)
- Чип "ALL" всегда первый
- Остальные чипы — динамически из уникальных `type` с количеством: `"sync (132)"`
- Сортировка чипов: по убыванию count (самые частые первые)
- Single-select: клик переключает выбор
- Стилизация: css-класс `.active` для выбранного чипа (border/background)
- Theme-aware: оба варианта (matrix, light)

### Заголовок REPORTS

Текущий: `REPORTS` (статический текст)
Новый: `REPORTS (N из M)` где N — количество отфильтрованных, M — общее количество.
Отображается только если N ≠ M (когда фильтр/поиск активен).

### Computed property `filteredReports`

```javascript
var filteredReports = Vue.computed(function() {
  var list = reports.value;
  // 1. Фильтр по типу
  if (selectedType.value && selectedType.value !== 'all') {
    list = list.filter(function(r) { return r.type === selectedType.value; });
  }
  // 2. Поиск по тексту
  var q = searchQuery.value.toLowerCase().trim();
  if (q) {
    list = list.filter(function(r) {
      return (r.title || '').toLowerCase().includes(q)
          || (r.filename || '').toLowerCase().includes(q);
    });
  }
  return list;
});
```

`v-for="r in filteredReports"` вместо текущего `v-for="r in reports"`.

### Computed property `typeChips`

```javascript
var typeChips = Vue.computed(function() {
  var counts = {};
  reports.value.forEach(function(r) {
    var t = r.type || 'other';
    counts[t] = (counts[t] || 0) + 1;
  });
  var chips = Object.keys(counts).map(function(t) {
    return { type: t, count: counts[t] };
  });
  chips.sort(function(a, b) { return b.count - a.count; });
  chips.unshift({ type: 'all', count: reports.value.length });
  return chips;
});
```

## CSS

### Поисковая строка

```css
.report-search {
  padding: 8px 12px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}
.report-search input {
  width: 100%;
  background: var(--bg);
  border: 1px solid var(--border);
  color: var(--text-body);
  padding: 6px 28px 6px 8px;
  font-size: 11px;
  font-family: inherit;
  outline: none;
}
.report-search input:focus {
  border-color: var(--cyan);
}
.report-search-clear {
  /* позиционирование кнопки ✕ внутри input */
}
```

### Фильтр-чипы

```css
.report-type-chips {
  display: flex;
  gap: 4px;
  padding: 6px 12px;
  border-bottom: 1px solid var(--border);
  overflow-x: auto;
  flex-shrink: 0;
}
.report-type-chip {
  white-space: nowrap;
  padding: 2px 8px;
  font-size: 9px;
  border: 1px solid var(--border);
  cursor: pointer;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-muted);
  background: transparent;
  flex-shrink: 0;
}
.report-type-chip:hover {
  border-color: var(--cyan);
  color: var(--text-body);
}
.report-type-chip.active {
  border-color: var(--cyan);
  color: var(--cyan);
  background: rgba(0, 255, 255, 0.08);
}
```

Для light-темы — `style-light.css` уже перебивает `var(--cyan)`, `var(--border)` и т.д.,
поэтому CSS-переменные автоматически работают для обеих тем.

## Security & Edge Cases

- Поиск: XSS невозможен — текст используется только для `includes()`, не для innerHTML
- Пустой тип в frontmatter → fallback `"other"`
- Файлы без frontmatter → тип `"other"`
- Автоселект первого отчёта: при фильтрации, если выбранный отчёт пропал из списка,
  автоматически выбирать первый из отфильтрованного списка

## Integration Points

- `vault_api.py:list_reports` (строка 1597) — добавить `type` в ответ
- `report.html` — переписать левую панель, добавить state-переменные
- `api.js` — изменений не требуется (ответ расширяется совместимо)
- `style.css` / `style-light.css` — проверить при CSS-фиксах (memory: PMA light theme overrides)
