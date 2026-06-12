# BL-119: Единый источник domain-правил -- Technical Design

**Status:** DRAFT
**Created:** 12.06.2026
**Requirements:** [requirements.md](requirements.md)
**Base:** [docs/domain-config/design.md](../domain-config/design.md) -- расширяет реализованную спеку

---

## 2.1 Обзор архитектуры

`domain-config.yaml` уже является единым источником для `jira_labels` (реализовано в docs/domain-config/). BL-119 расширяет конфиг полями `keywords` и `prompt_hint`, и переводит на чтение из конфига 4 оставшихся потребителя.

```
                      domain-config.yaml
                     (VAULT_PATH корень)
                            |
            +---------------+------------------+
            |               |                  |
     domain_config.py   domain_config.py       |
      (knowledge-engine)  (pm-bot)             |
            |               |                  |
    +-------+-------+   +--+--------+         |
    |       |       |   |   |       |         |
    v       v       v   v   v       v         v
 mapper  ingest  artifact  claude  prompts  vault_api
  .py     .py   _extractor _client  /idea   .py
                   .py      .py     .txt

  [OK]    [NEW]   [NEW]    [NEW]   [NEW]    [OK]


Легенда:
  [OK]  -- уже читает из конфига (реализовано в docs/domain-config/)
  [NEW] -- переводится на конфиг в BL-119
```

### Потоки данных

**Read path (6 потребителей):**

| # | Потребитель | Сервис | Что читает из конфига | Статус |
|---|---|---|---|---|
| 1 | `mapper.py` (jira-sync) | KE | `jira_labels` | Реализовано |
| 2 | `vault_api.py` (Web UI) | pm-bot | все поля (CRUD) | Реализовано |
| 3 | `claude_client.py` (capture) | pm-bot | slugs + `prompt_hint` | **BL-119** |
| 4 | `prompts/idea.txt` (LLM prompt) | pm-bot | `prompt_hint` / `description` | **BL-119** |
| 5 | `artifact_extractor.py` (meetings) | KE | `keywords` | **BL-119** |
| 6 | `ingest.py` (clippings) | KE | `tags` + `keywords` | **BL-119** |

**Write path** -- без изменений. Запись через Web UI (`vault_api.py`) или ручное редактирование YAML.

---

## 2.2 Расширение domain-config.yaml

### Полная схема (существующие + новые поля)

```yaml
domains:
  <domain-slug>:                    # key: ^[a-z0-9]+(?:-[a-z0-9]+)*$
    display_name: <string>          # REQUIRED. Человекочитаемое имя. Max 100.
    description: <string>           # OPTIONAL. Описание домена. Max 500. Default: ""
    color: <string>                 # OPTIONAL. HEX цвет для UI. Default: "#607D8B"
    jira_labels:                    # OPTIONAL. Jira-лейблы. Default: []
      - <string>
    tags:                           # OPTIONAL. Теги для tag-based detection. Default: []
      - <string>                    #   (уже реализовано в validate + build_tag_map)
    keywords:                       # **NEW** OPTIONAL. Ключевые слова для keyword detection. Default: []
      - <string>                    #   Case-insensitive substring match.
    prompt_hint: <string>           # **NEW** OPTIONAL. Текст для LLM-промпта. Max 500. Default: ""
```

### Новые поля -- детали

| Поле | Тип | Required | Валидация | Default | Назначение |
|---|---|---|---|---|---|
| `keywords` | `list[str]` | нет | Каждый элемент -- непустая строка | `[]` | Ключевые слова для keyword-based domain detection в `ingest.py` и `artifact_extractor.py` |
| `prompt_hint` | `str` | нет | Max 500 символов | `""` | Описание домена для включения в LLM-промпт. Если пуст -- используется `description` |

### Пример полного конфига

```yaml
domains:
  search-engine:
    display_name: "Поисковый движок"
    description: "Поиск отелей и квартир: фильтры, сортировка, выдача"
    color: "#2196F3"
    jira_labels:
      - search
    tags:
      - search
      - search-engine
      - ranking
      - indexing
    keywords:
      - поиск
      - релевантность
      - индексация
      - fulltext
      - фильтрация
      - ранжирование
      - выдача
      - getresults
      - searchoffers
    prompt_hint: "поиск, релевантность, индексация, полнотекстовый поиск, фильтрация, ранжирование, выдача"

  static-metadata:
    display_name: "Справочники"
    description: "Справочники, классификаторы, атрибуты, метаданные объектов"
    color: "#FF9800"
    jira_labels:
      - dictionary
    tags:
      - static
      - dictionary
      - catalog
      - reference
      - metadata
      - property
      - amenities
      - rules
      - beds
      - types
    keywords:
      - справочник
      - классификатор
      - атрибут
      - enum
      - словарь
      - статика
      - карточка объекта
      - amenities
      - "property type"
      - метаданн
      - каталог
      - контент
    prompt_hint: "справочники, классификаторы, атрибуты, метаобъекты, каталоги, перечисления, справочная информация, статические данные объектов размещения"

  suggester:
    display_name: "Подсказчик"
    description: "Автокомплит, подсказки, поиск по префиксу"
    color: "#4CAF50"
    jira_labels:
      - suggester
    tags:
      - suggester
      - typeahead
      - autocomplete
    keywords:
      - подсказчик
      - автокомплит
      - подсказка
      - подсказк
      - typeahead
      - префикс
      - "по мере ввода"
      - suggest
    prompt_hint: "автокомплит, подсказки, typeahead, выпадающие списки, поиск по префиксу, подбор"

  partner-search-engine:
    display_name: "Поиск партнёров"
    description: "Работа с продавцами: поиск, фильтрация, профили"
    color: "#9C27B0"
    jira_labels:
      - partner_search
    tags:
      - partner
      - partner_search
      - b2b
      - supplier
      - affiliate
    keywords:
      - партнёр
      - поставщик
      - b2b
      - supplier
      - подключение партнёра
      - аффилиат
    prompt_hint: "партнёрский поиск, B2B, поставщики, аффилиаты, подключение партнёров"

  general:
    display_name: "Общее"
    description: "Задачи, не привязанные к конкретному домену"
    color: "#607D8B"
    jira_labels: []
    tags:
      - general
    keywords: []
    prompt_hint: "если идея не относится к конкретному домену"
```

---

## 2.3 Новые функции в domain_config.py

Добавляются в **обе** копии: `knowledge-engine/app/domain_config.py` и `pm-bot/app/domain_config.py`.

### 2.3.1 `build_keyword_map() -> dict[str, str]`

```python
_MAX_PROMPT_HINT = 500


def build_keyword_map() -> dict[str, str]:
    """Build {keyword_lower: domain_slug} map from config.

    Reads the 'keywords' field from each domain entry.
    Keywords are lowercased for case-insensitive matching.
    First domain to claim a keyword wins (no duplicates).

    Returns:
        Dict mapping lowercase keyword to domain slug.
        Empty dict if config is missing or has no keywords.
    """
    logger.info("build_keyword_map: building keyword map from config")
    config = load()
    keyword_map: dict[str, str] = {}
    domains = config.get("domains", {})

    for slug, entry in domains.items():
        if not isinstance(entry, dict):
            logger.warning(
                "build_keyword_map: entry for slug %r is not a dict, skipping", slug
            )
            continue
        for kw in entry.get("keywords", []):
            if isinstance(kw, str) and kw:
                key = kw.lower()
                if key in keyword_map:
                    logger.warning(
                        "build_keyword_map: duplicate keyword %r (domains %r and %r) "
                        "-- keeping first",
                        kw, keyword_map[key], slug,
                    )
                else:
                    keyword_map[key] = slug

    logger.info(
        "build_keyword_map: built map with %d keyword(s) from %d domain(s)",
        len(keyword_map), len(domains),
    )
    return keyword_map
```

**Кеширование:** Использует тот же mtime-кеш через `load()`. Не добавляет собственный кеш -- `load()` уже кеширует разобранный YAML, а `build_keyword_map()` выполняет лёгкую итерацию по dict. При 5 доменах x 10 keywords = 50 итераций -- пренебрежимо малая стоимость.

### 2.3.2 `build_prompt_section() -> str`

```python
def build_prompt_section() -> str:
    """Generate the domain list section for LLM prompt.

    For each domain, uses prompt_hint if present, otherwise falls back
    to description. Returns empty string if config is missing/empty.

    Format per domain:
        - <slug> -- <prompt_hint or description>

    Returns:
        Multi-line string with domain descriptions for the LLM prompt.
        Empty string if no domains in config.
    """
    logger.info("build_prompt_section: generating prompt section from config")
    config = load()
    domains = config.get("domains", {})

    if not domains:
        logger.warning("build_prompt_section: no domains in config, returning empty")
        return ""

    lines: list[str] = []
    for slug, entry in domains.items():
        if not isinstance(entry, dict):
            continue
        hint = entry.get("prompt_hint", "").strip()
        if not hint:
            hint = entry.get("description", "").strip()
        if not hint:
            hint = slug  # absolute fallback
        lines.append(f"- {slug} -- {hint}")

    section = "\n".join(lines)
    logger.info(
        "build_prompt_section: generated section with %d domain(s) (%d chars)",
        len(lines), len(section),
    )
    return section
```

### 2.3.3 `get_valid_domains() -> tuple[str, ...]`

```python
def get_valid_domains() -> tuple[str, ...]:
    """Return tuple of all domain slugs from config.

    Returns empty tuple if config is missing or has no domains.
    """
    logger.info("get_valid_domains: reading domain slugs from config")
    config = load()
    domains = config.get("domains", {})
    slugs = tuple(domains.keys())
    logger.info("get_valid_domains: found %d domain(s): %s", len(slugs), slugs)
    return slugs
```

### 2.3.4 Расширение валидации

Добавить в `validate_domain_entry()` проверки новых полей:

```python
# В validate_domain_entry(), после блока проверки tags:

    # keywords: optional list of non-empty strings
    keywords = entry.get("keywords", [])
    if keywords is not None:
        if not isinstance(keywords, list):
            errors.append("'keywords' must be a list")
            logger.warning(
                "validate_domain_entry: keywords for slug %r is not a list", slug
            )
        else:
            for i, kw in enumerate(keywords):
                if not isinstance(kw, str) or not kw:
                    errors.append(f"'keywords[{i}]' must be a non-empty string")
                    logger.warning(
                        "validate_domain_entry: keywords[%d] for slug %r is invalid: %r",
                        i, slug, kw,
                    )

    # prompt_hint: optional string, max 500 chars
    prompt_hint = entry.get("prompt_hint", "")
    if prompt_hint is not None:
        if not isinstance(prompt_hint, str):
            errors.append("'prompt_hint' must be a string")
            logger.warning(
                "validate_domain_entry: prompt_hint for slug %r is not a string", slug
            )
        elif len(prompt_hint) > _MAX_PROMPT_HINT:
            errors.append(
                f"'prompt_hint' exceeds max length {_MAX_PROMPT_HINT} "
                f"(got {len(prompt_hint)})"
            )
            logger.warning(
                "validate_domain_entry: prompt_hint for slug %r is too long (%d > %d)",
                slug, len(prompt_hint), _MAX_PROMPT_HINT,
            )
```

### 2.3.5 Расширение `set_domain()` normalize block

Текущий код (KE, строка 330):

```python
    normalized = {
        "display_name": entry["display_name"],
        "description": entry.get("description", ""),
        "color": entry.get("color", _DEFAULT_COLOR),
        "jira_labels": entry.get("jira_labels", []),
        "tags": entry.get("tags", []),
    }
```

Расширенный код:

```python
    normalized = {
        "display_name": entry["display_name"],
        "description": entry.get("description", ""),
        "color": entry.get("color", _DEFAULT_COLOR),
        "jira_labels": entry.get("jira_labels", []),
        "tags": entry.get("tags", []),
        "keywords": entry.get("keywords", []),
        "prompt_hint": entry.get("prompt_hint", ""),
    }
```

Аналогичное изменение в pm-bot копии (текущая строка 316):

```python
    # Текущий код pm-bot:
    normalized = {
        "display_name": entry["display_name"],
        "description": entry.get("description", ""),
        "color": entry.get("color", _DEFAULT_COLOR),
        "jira_labels": entry.get("jira_labels", []),
    }
```

Расширяется до:

```python
    normalized = {
        "display_name": entry["display_name"],
        "description": entry.get("description", ""),
        "color": entry.get("color", _DEFAULT_COLOR),
        "jira_labels": entry.get("jira_labels", []),
        "tags": entry.get("tags", []),
        "keywords": entry.get("keywords", []),
        "prompt_hint": entry.get("prompt_hint", ""),
    }
```

---

## 2.4 Изменения в pm-bot/app/claude_client.py

### Текущий код (строка 16)

```python
_VALID_DOMAINS = ("static-metadata", "suggester", "search-engine", "general")
```

Используется в `_validate_idea_data()` (строка 59):

```python
    if result["domain"] not in _VALID_DOMAINS:
        logger.warning("_validate_idea_data: invalid domain '%s', falling back to 'general'", result["domain"])
        result["domain"] = "general"
```

### Новый код

**Шаг 1.** Заменить статический tuple на функцию с fallback:

```python
# Хардкоженный fallback (используется если конфиг недоступен)
_FALLBACK_DOMAINS = ("static-metadata", "suggester", "search-engine", "general")


def _get_valid_domains() -> tuple[str, ...]:
    """Return valid domain slugs from domain-config.yaml.

    Falls back to hardcoded tuple if config is missing or empty.
    """
    try:
        from . import domain_config
        domains = domain_config.get_valid_domains()
        if domains:
            logger.info(
                "_get_valid_domains: loaded %d domain(s) from config", len(domains)
            )
            return domains
    except Exception as exc:
        logger.warning(
            "_get_valid_domains: failed to load config, using fallback: %s", exc
        )

    logger.info(
        "_get_valid_domains: domain-config.yaml not found or empty, "
        "using hardcoded defaults (%d domains)",
        len(_FALLBACK_DOMAINS),
    )
    return _FALLBACK_DOMAINS
```

**Шаг 2.** Обновить `_validate_idea_data()`:

```python
def _validate_idea_data(data: dict) -> dict:
    """Validate and normalize the parsed idea dict."""
    result = {}
    for key in _IDEA_REQUIRED_KEYS:
        result[key] = data.get(key, "")

    valid_domains = _get_valid_domains()
    if result["domain"] not in valid_domains:
        logger.warning(
            "_validate_idea_data: invalid domain '%s' (not in %s), "
            "falling back to 'general'",
            result["domain"], valid_domains,
        )
        result["domain"] = "general"

    # ... rest unchanged ...
```

**Шаг 3.** Обновить `process_idea()` для динамической генерации промпта:

```python
def _build_idea_prompt(raw_text: str) -> str:
    """Build the full idea prompt with dynamic domain section.

    Tries to inject domains from domain-config.yaml into the prompt.
    Falls back to static idea.txt if config unavailable.

    Args:
        raw_text: Raw idea text from user.

    Returns:
        Complete prompt string (system prompt + separator + user text).
    """
    # Try dynamic prompt generation
    try:
        from . import domain_config
        domains_section = domain_config.build_prompt_section()
        if domains_section:
            prompt_template = _load_prompt("idea")
            # Replace the static domain block with dynamic one
            prompt = _inject_domains_section(prompt_template, domains_section)
            logger.info(
                "_build_idea_prompt: using dynamic domains section (%d domains)",
                domains_section.count("\n") + 1,
            )
            return f"{prompt}\n\n---\n{raw_text}"
    except Exception as exc:
        logger.warning(
            "_build_idea_prompt: failed to build dynamic prompt, "
            "using static: %s", exc,
        )

    # Fallback: use static prompt file
    logger.info("_build_idea_prompt: using static prompt from idea.txt")
    prompt = _load_prompt("idea")
    return f"{prompt}\n\n---\n{raw_text}"


def _inject_domains_section(template: str, domains_section: str) -> str:
    """Replace the static domain list in the prompt template with dynamic one.

    Locates the block between 'Доступные домены:' (or the {domains_section}
    placeholder) and the next empty line, and replaces it with the dynamic list.

    Args:
        template: Original prompt template text.
        domains_section: Dynamic domain list from build_prompt_section().

    Returns:
        Prompt with injected domain section.
    """
    # Strategy 1: look for explicit placeholder
    placeholder = "{domains_section}"
    if placeholder in template:
        logger.info("_inject_domains_section: found placeholder, replacing")
        return template.replace(placeholder, domains_section)

    # Strategy 2: find and replace the static domain block
    # Pattern: "Определи домен..." line through the last "- domain -- ..." line
    import re
    pattern = (
        r"(Определи домен идеи по содержанию сообщения\. Доступные домены:\n)"
        r"(- .+\n?)+"
    )
    match = re.search(pattern, template)
    if match:
        header = match.group(1)  # Keep the header line
        replacement = header + domains_section + "\n"
        result = template[:match.start()] + replacement + template[match.end():]
        logger.info("_inject_domains_section: replaced static block via regex")
        return result

    # Strategy 3: fallback -- append domain section before JSON format block
    logger.warning(
        "_inject_domains_section: could not locate domain block in template, "
        "appending section before JSON block"
    )
    json_marker = "Верни ТОЛЬКО JSON"
    if json_marker in template:
        idx = template.index(json_marker)
        injected = (
            f"Определи домен идеи по содержанию сообщения. "
            f"Доступные домены:\n{domains_section}\n\n"
        )
        return template[:idx] + injected + template[idx:]

    return template
```

**Шаг 4.** Обновить `process_idea()`:

```python
def process_idea(raw_text: str) -> dict:
    """Send raw text to Claude, return structured idea dict."""
    logger.info("process_idea: processing raw_text, len=%d", len(raw_text))

    prompt_with_text = _build_idea_prompt(raw_text)

    try:
        response_text = llm_client.call_with_fallback(
            operation="idea",
            messages=[{"role": "user", "content": prompt_with_text}],
            max_tokens=1000,
        )
        logger.info("process_idea: received response, len=%d", len(response_text))
    except Exception as e:
        logger.error("process_idea: LLM call failed: %s", e)
        raise

    # ... rest unchanged (JSON extraction, validation) ...
```

### Обоснование трёхуровневой стратегии инъекции

1. **Placeholder `{domains_section}`** -- для будущего перехода prompt template на шаблон. Не ломает текущий статический файл.
2. **Regex замена** -- находит существующий блок `"Определи домен... / - static-metadata -- ..."` и заменяет. Работает с текущим форматом `idea.txt`.
3. **Append fallback** -- на случай если формат промпта изменится непредвиденным образом.

---

## 2.5 Изменения в pm-bot/app/prompts/idea.txt

Файл остаётся **как есть** и служит fallback-шаблоном. Динамическая генерация в `_inject_domains_section()` заменяет блок доменов на лету.

Для будущей миграции на шаблон, файл может быть заменён на:

```
Ты -- ассистент продакт-менеджера OTA-компании (онлайн-бронирование отелей и квартир).
Твоя задача -- извлечь структурированные данные из сырой мысли для карточки идеи.

Контекст: PM отвечает за систему контента -- хранилище статической информации об объектах размещения.

Определи домен идеи по содержанию сообщения. Доступные домены:
{domains_section}

Верни ТОЛЬКО JSON внутри блока ```json ... ```. Никакого текста до или после.
...
```

Но в первой итерации BL-119 файл **не модифицируется** -- regex-стратегия работает с текущим содержимым.

---

## 2.6 Изменения в knowledge-engine/app/artifact_extractor.py

### Текущий код (строки 23-35)

```python
_DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "search-engine": [
        "поиск", "индексаци", "ранжирован", "выдач", "фильтр",
    ],
    "suggester": [
        "автокомплит", "подсказк", "typeahead", "suggest",
    ],
    "static-metadata": [
        "справочник", "классификатор", "атрибут", "метаданн", "каталог", "контент",
    ],
}

_DEFAULT_DOMAIN = "general"
```

**Проблема:** `partner-search-engine` полностью отсутствует.

### Текущий `_detect_domain()` (строки 269-288)

```python
def _detect_domain(text: str) -> str:
    lower = text.lower()
    for domain, keywords in _DOMAIN_KEYWORDS.items():
        for kw in keywords:
            if kw in lower:
                logger.info(
                    "_detect_domain: matched keyword '%s' -> domain '%s'",
                    kw, domain,
                )
                return domain
    logger.info("_detect_domain: no keyword match, defaulting to '%s'", _DEFAULT_DOMAIN)
    return _DEFAULT_DOMAIN
```

### Новый код

**Шаг 1.** Добавить функцию получения merged keyword map:

```python
def _merged_keyword_map() -> dict[str, list[str]]:
    """Merge hardcoded _DOMAIN_KEYWORDS with domain-config.yaml keywords.

    Priority: config keywords extend hardcoded (config adds, does not remove).

    Returns:
        Dict mapping domain slug to list of keywords.
    """
    logger.info("_merged_keyword_map: building merged keyword map")
    result: dict[str, list[str]] = {}

    # Start with hardcoded
    for domain, kw_list in _DOMAIN_KEYWORDS.items():
        result[domain] = list(kw_list)

    # Overlay config keywords
    try:
        from . import domain_config
        config = domain_config.load()
        domains = config.get("domains", {})
        config_count = 0
        for slug, entry in domains.items():
            if not isinstance(entry, dict):
                continue
            config_keywords = entry.get("keywords", [])
            if not config_keywords:
                continue
            if slug not in result:
                result[slug] = []
            existing_lower = {kw.lower() for kw in result[slug]}
            for kw in config_keywords:
                if isinstance(kw, str) and kw and kw.lower() not in existing_lower:
                    result[slug].append(kw)
                    existing_lower.add(kw.lower())
                    config_count += 1
        logger.info(
            "_merged_keyword_map: added %d keyword(s) from config across %d domain(s)",
            config_count, len(domains),
        )
    except Exception as exc:
        logger.warning(
            "_merged_keyword_map: could not load config keywords, "
            "using hardcoded only: %s", exc,
        )

    logger.info(
        "_merged_keyword_map: total %d domain(s), %d keyword(s)",
        len(result), sum(len(v) for v in result.values()),
    )
    return result
```

**Шаг 2.** Обновить `_detect_domain()`:

```python
def _detect_domain(text: str) -> str:
    """Determine the domain for an artifact based on keyword matching.

    Checks the text (lowercased) against merged keyword lists
    (config-first, hardcoded fallback).
    Returns the first matching domain, or 'general' if none match.
    """
    lower = text.lower()
    keyword_map = _merged_keyword_map()

    for domain, keywords in keyword_map.items():
        for kw in keywords:
            if kw.lower() in lower:
                logger.info(
                    "_detect_domain: matched keyword '%s' -> domain '%s'",
                    kw, domain,
                )
                return domain

    logger.info(
        "_detect_domain: no keyword match, defaulting to '%s'", _DEFAULT_DOMAIN
    )
    return _DEFAULT_DOMAIN
```

### Результат

- `partner-search-engine` появится автоматически, если в конфиге есть keywords для него.
- Хардкоженный `_DOMAIN_KEYWORDS` остаётся как fallback на случай отсутствия конфига.
- Новые домены, добавленные через Web UI с keywords, начнут распознаваться без изменения кода.

---

## 2.7 Изменения в knowledge-engine/app/ingest.py

### Текущее состояние

Файл уже частично интегрирован с конфигом:

- **Строки 24-53:** Хардкоженный `TAG_TO_DOMAIN` (fallback).
- **Строки 83-118:** Хардкоженный `KEYWORD_TO_DOMAIN` (fallback).
- **Строки 150-185:** `_merged_tag_map()` -- уже реализованная функция, мержит `TAG_TO_DOMAIN` c `domain_config.build_tag_map()`. Конфиг имеет приоритет.
- **Строка 22:** Комментарий `# fallback, primary source is domain-config.yaml`.

### Что нужно изменить

`detect_domain()` (строки 192-268) использует `_merged_tag_map()` для тегов, но для keywords читает напрямую из хардкоженного `KEYWORD_TO_DOMAIN` (строка 237). Нужно добавить аналогичный merge для keywords.

**Шаг 1.** Добавить `_merged_keyword_map()` по аналогии с `_merged_tag_map()`:

```python
def _merged_keyword_map() -> dict[str, str]:
    """Merge hardcoded KEYWORD_TO_DOMAIN with domain-config.yaml keywords.

    Priority: domain-config.yaml > hardcoded.
    Handles ImportError/AttributeError gracefully with fallback.

    Returns:
        Merged keyword-to-domain mapping dict.
    """
    logger.info("_merged_keyword_map: building merged keyword map")
    result = dict(KEYWORD_TO_DOMAIN)

    try:
        from .domain_config import build_keyword_map
        config_keywords = build_keyword_map()
        if config_keywords:
            result.update(config_keywords)
            logger.info(
                "_merged_keyword_map: overlayed %d keywords from domain-config.yaml",
                len(config_keywords),
            )
    except (ImportError, AttributeError) as exc:
        logger.warning(
            "_merged_keyword_map: could not load build_keyword_map from domain_config, "
            "using hardcoded KEYWORD_TO_DOMAIN only: %s",
            exc,
        )
    except Exception as exc:
        logger.warning(
            "_merged_keyword_map: unexpected error loading config keywords, "
            "using hardcoded KEYWORD_TO_DOMAIN only: %s",
            exc,
        )

    logger.info("_merged_keyword_map: total %d entries in merged map", len(result))
    return result
```

**Шаг 2.** Обновить `detect_domain()` -- заменить прямое чтение `KEYWORD_TO_DOMAIN` на `_merged_keyword_map()`:

Текущий код (строки 233-243):

```python
    # Step 2: Content keyword matching (only if Step 1 gave no results)
    if not matched_domains:
        logger.info("detect_domain: no tag matches, trying keyword matching")
        body_lower = body.lower()
        seen_domains: set[str] = set()
        for keyword, domain in KEYWORD_TO_DOMAIN.items():
            if domain in seen_domains:
                continue
            if keyword.lower() in body_lower:
                matched_domains.append((domain, f"keyword:{keyword}"))
                seen_domains.add(domain)
                logger.info("detect_domain: keyword %r matched domain %r", keyword, domain)
```

Новый код:

```python
    # Step 2: Content keyword matching (only if Step 1 gave no results)
    if not matched_domains:
        logger.info("detect_domain: no tag matches, trying keyword matching")
        keyword_map = _merged_keyword_map()
        body_lower = body.lower()
        seen_domains: set[str] = set()
        for keyword, domain in keyword_map.items():
            if domain in seen_domains:
                continue
            if keyword.lower() in body_lower:
                matched_domains.append((domain, f"keyword:{keyword}"))
                seen_domains.add(domain)
                logger.info(
                    "detect_domain: keyword %r matched domain %r", keyword, domain
                )
```

### Паттерн идентичен mapper.py

Оба модуля следуют одному и тому же паттерну:

```
hardcoded dict  -->  merge function  -->  config overlay (highest priority)  -->  result
```

| Модуль | Хардкоженный dict | Merge function | Config source |
|---|---|---|---|
| `mapper.py` | `LABEL_TO_DOMAIN` | `_merged_label_map()` | `build_label_map()` |
| `ingest.py` (tags) | `TAG_TO_DOMAIN` | `_merged_tag_map()` | `build_tag_map()` |
| `ingest.py` (keywords) | `KEYWORD_TO_DOMAIN` | `_merged_keyword_map()` **NEW** | `build_keyword_map()` **NEW** |

---

## 2.8 Seed: расширение seed_from_defaults()

### Текущее поведение

`seed_from_defaults()` создаёт запись домена с полями: `display_name`, `description`, `color`, `jira_labels`. Поля `tags`, `keywords`, `prompt_hint` не заполняются.

### Расширение

При seeding добавить данные из хардкоженных источников. Функция получает расширенный параметр:

```python
# Данные для seed по каждому домену (объединены из всех хардкоженных источников)
_SEED_DOMAIN_DATA: dict[str, dict] = {
    "search-engine": {
        "display_name": "Поисковый движок",
        "description": "Поиск отелей и квартир: фильтры, сортировка, выдача",
        "color": "#2196F3",
        "tags": ["search", "search-engine", "ranking", "indexing"],
        "keywords": [
            "поиск", "релевантность", "индексация", "fulltext",
            "фильтрация", "ранжирование", "выдача", "getresults", "searchoffers",
        ],
        "prompt_hint": (
            "поиск, релевантность, индексация, полнотекстовый поиск, "
            "фильтрация, ранжирование, выдача"
        ),
    },
    "static-metadata": {
        "display_name": "Справочники",
        "description": "Справочники, классификаторы, атрибуты, метаданные объектов",
        "color": "#FF9800",
        "tags": [
            "static", "dictionary", "catalog", "reference",
            "metadata", "property", "amenities", "rules", "beds", "types",
        ],
        "keywords": [
            "справочник", "классификатор", "атрибут", "enum", "словарь",
            "статика", "карточка объекта", "amenities", "property type",
            "метаданн", "каталог", "контент",
        ],
        "prompt_hint": (
            "справочники, классификаторы, атрибуты, метаобъекты, каталоги, "
            "перечисления, справочная информация, статические данные объектов размещения"
        ),
    },
    "suggester": {
        "display_name": "Подсказчик",
        "description": "Автокомплит, подсказки, поиск по префиксу",
        "color": "#4CAF50",
        "tags": ["suggester", "typeahead", "autocomplete"],
        "keywords": [
            "подсказчик", "автокомплит", "подсказка", "подсказк",
            "typeahead", "префикс", "по мере ввода", "suggest",
        ],
        "prompt_hint": (
            "автокомплит, подсказки, typeahead, выпадающие списки, "
            "поиск по префиксу, подбор"
        ),
    },
    "partner-search-engine": {
        "display_name": "Поиск партнёров",
        "description": "Работа с продавцами: поиск, фильтрация, профили",
        "color": "#9C27B0",
        "tags": ["partner", "partner_search", "b2b", "supplier", "affiliate"],
        "keywords": [
            "партнёр", "поставщик", "b2b", "supplier",
            "подключение партнёра", "аффилиат",
        ],
        "prompt_hint": (
            "партнёрский поиск, B2B, поставщики, аффилиаты, "
            "подключение партнёров"
        ),
    },
    "general": {
        "display_name": "Общее",
        "description": "Задачи, не привязанные к конкретному домену",
        "color": "#607D8B",
        "tags": ["general"],
        "keywords": [],
        "prompt_hint": "если идея не относится к конкретному домену",
    },
}
```

Обновление `seed_from_defaults()` -- при создании записи домена обогащать из `_SEED_DOMAIN_DATA`:

```python
    # В seed_from_defaults(), при создании entries из hardcoded_map:
    for slug, labels in domain_labels.items():
        if not _SLUG_RE.match(slug):
            logger.warning(
                "seed_from_defaults: skipping invalid slug %r from hardcoded_map", slug
            )
            continue

        # Start with seed data if available, otherwise create minimal entry
        seed = _SEED_DOMAIN_DATA.get(slug, {})
        domains[slug] = {
            "display_name": seed.get("display_name", slug),
            "description": seed.get("description", ""),
            "color": seed.get("color", _DEFAULT_COLOR),
            "jira_labels": labels,
            "tags": seed.get("tags", []),
            "keywords": seed.get("keywords", []),
            "prompt_hint": seed.get("prompt_hint", ""),
        }
        logger.debug(
            "seed_from_defaults: added domain %r with labels %r, "
            "%d tags, %d keywords",
            slug, labels, len(domains[slug]["tags"]), len(domains[slug]["keywords"]),
        )
```

**Идемпотентность:** Если конфиг уже существует, `seed_from_defaults()` не перезаписывает его (проверка `path.exists()` в начале функции). Поэтому seed data применяется только при первом создании.

---

## 2.9 Технические решения

### Decision 1: `prompt_hint` vs `description` для LLM

**Решение:** Оба поля. `prompt_hint` -- специализированный текст для промпта. `description` -- общее описание для UI.

**Обоснование:**
- `description` оптимизирован для человека (UI, Web-страница доменов). Пример: "Поиск отелей и квартир: фильтры, сортировка, выдача".
- `prompt_hint` оптимизирован для LLM -- содержит ключевые слова-маркеры, по которым Claude определяет домен. Пример: "поиск, релевантность, индексация, полнотекстовый поиск, фильтрация".
- Если PM не хочет писать два текста, `prompt_hint` опционален -- fallback на `description`.

**Альтернатива:** Использовать только `description` для обоих целей. Отклонена: один текст не может быть одновременно хорошим описанием для UI и эффективным промптом для LLM.

### Decision 2: Стратегия мержа -- config extends, not replaces

**Решение:** Хардкоженные dicts остаются как fallback. Config дополняет и переопределяет, но не удаляет.

**Обоснование:**
- Если `domain-config.yaml` удалён или повреждён, система продолжает работать на хардкоженных правилах.
- AC-06, AC-07: fallback на хардкод при отсутствии конфига -- обязательное требование.
- Паттерн уже доказан в `mapper.py` (`_merged_label_map()`) и `ingest.py` (`_merged_tag_map()`).

**Порядок приоритетов:**

```
Config keywords/tags  >  Hardcoded keywords/tags
```

**Альтернатива:** Config полностью заменяет хардкод. Отклонена: слишком хрупко -- удаление конфига = полная потеря domain detection.

### Decision 3: Нет Web UI для keywords/tags/prompt_hint в v1

**Решение:** В BL-119 управление `keywords`, `tags`, `prompt_hint` -- через ручное редактирование YAML (или будущий API). Web UI доменов показывает только `display_name`, `description`, `color`, `jira_labels`.

**Обоснование:**
- Web UI для keyword-editor -- значительный объём фронтенд-работы (drag-and-drop списки, валидация).
- Основные пользователи (PM) комфортно работают с YAML в Obsidian.
- Первая итерация -- убедиться что инфраструктура работает. UI -- отдельная фича.

### Decision 4: Merge pattern в artifact_extractor.py -- dict[str, list[str]] vs dict[str, str]

**Решение:** `artifact_extractor.py` использует `dict[str, list[str]]` (domain -> keywords), а `ingest.py` использует `dict[str, str]` (keyword -> domain). Разные форматы отражают разную логику потребителей.

**Обоснование:**
- `artifact_extractor.py` итерирует по доменам и их keywords (`for domain, keywords in map.items(): for kw in keywords: if kw in text`). Формат dict[str, list[str]] естественен.
- `ingest.py` итерирует по keywords и ищет домен (`for keyword, domain in map.items(): if keyword in text`). Формат dict[str, str] естественен.
- `domain_config.build_keyword_map()` возвращает `dict[str, str]` -- формат `ingest.py`. Для `artifact_extractor.py` данные перестраиваются в `_merged_keyword_map()`.

---

## 2.10 Безопасность и edge cases

### Fallback при отсутствии конфига

| Модуль | Поведение при отсутствии domain-config.yaml |
|---|---|
| `claude_client.py` | `_get_valid_domains()` возвращает `_FALLBACK_DOMAINS` tuple. Лог: `"domain-config.yaml not found, using hardcoded defaults"`. |
| `process_idea()` | `_build_idea_prompt()` ловит Exception, возвращает статический промпт из `idea.txt`. Лог: `"using static prompt from idea.txt"`. |
| `artifact_extractor.py` | `_merged_keyword_map()` ловит Exception, возвращает `_DOMAIN_KEYWORDS`. Лог: `"using hardcoded only"`. |
| `ingest.py` | `_merged_keyword_map()` ловит ImportError/Exception, возвращает `KEYWORD_TO_DOMAIN`. Лог: `"using hardcoded KEYWORD_TO_DOMAIN only"`. |
| `ingest.py` (tags) | `_merged_tag_map()` уже реализован с fallback. |
| `mapper.py` | `_merged_label_map()` уже реализован с fallback. |

### Пустой список keywords

- Домен с `keywords: []` -- валидно. Означает: домен существует, но keyword detection для него не работает (только tag-based или Jira label-based).
- `build_keyword_map()` пропускает домены с пустым keywords.

### Prompt injection через prompt_hint

- `prompt_hint` включается в промпт для Claude. Теоретически злоумышленник может вставить инструкцию для LLM.
- **Митигация:** Доступ к vault ограничен одним PM (владелец). Конфиг-файл в vault, защищённом `ALLOWED_CHAT_ID`.
- **Дополнительная защита:** `prompt_hint` ограничен 500 символами. Валидация в `validate_domain_entry()`.
- **Не реализуем в v1:** Санитизация prompt_hint от LLM-инъекций. Пользователь -- доверенный.

### Concurrent writes

- Без изменений: atomic write (`tmp + os.replace`) предотвращает partial write.
- Last write wins -- приемлемо (описано в docs/domain-config/design.md, секция 2.9).

### Коллизия keywords между доменами

- Один keyword может присутствовать в keywords нескольких доменов.
- В `build_keyword_map()` первый домен побеждает (first-match по порядку в YAML).
- **Не блокируем:** в валидации не проверяем уникальность keywords (в отличие от jira_labels, где уникальность строго обязательна). Keywords -- soft match, коллизии допустимы.

### Влияние на производительность

- `build_keyword_map()` и `build_prompt_section()` используют `load()` с mtime-кешем. При неизменном файле -- чтение из in-memory cache.
- `_merged_keyword_map()` в `ingest.py` вызывается один раз на `detect_domain()`. При batch processing (100 клиппингов) -- 100 вызовов `load()`, но все из кеша (один `os.stat()` + dict lookup).
- `_get_valid_domains()` в `claude_client.py` вызывается при каждой идее. Частота: ~10/день. Оверхед минимален.

---

## 2.11 Обратная совместимость

### Гарантии

1. **Все хардкоженные dicts остаются.** `_DOMAIN_KEYWORDS`, `TAG_TO_DOMAIN`, `KEYWORD_TO_DOMAIN`, `_VALID_DOMAINS` (ren. `_FALLBACK_DOMAINS`) -- сохраняются как fallback.
2. **Новые поля optional.** `keywords` и `prompt_hint` имеют default значения (`[]` и `""` соответственно). Существующие конфиги без этих полей остаются валидными.
3. **Нет breaking changes в API.** Эндпоинты `GET/PUT /api/v1/domain-config` принимают и возвращают новые поля, но они optional. Клиенты, не знающие про новые поля, продолжают работать.
4. **Промпт fallback.** Если dynamic prompt generation сломается -- `process_idea()` использует статический `idea.txt` как было раньше.
5. **Нет миграции данных.** Существующие файлы, уже классифицированные в домены, не перемещаются.

### Обратная совместимость `set_domain()`

При обновлении домена через Web UI (которая пока не знает про `keywords`/`prompt_hint`):
- `set_domain()` вызывается с `entry` без `keywords`/`prompt_hint`.
- normalize block ставит defaults: `keywords: []`, `prompt_hint: ""`.
- **Проблема:** Если домен имел keywords/prompt_hint в YAML, а пользователь обновил его через Web UI, эти поля будут сброшены.
- **Решение:** В `set_domain()` при обновлении (домен уже существует) -- мержить с существующей записью для полей, не переданных в `entry`:

```python
    # In set_domain(), before normalize:
    existing = config.get("domains", {}).get(slug)

    normalized = {
        "display_name": entry["display_name"],
        "description": entry.get("description", ""),
        "color": entry.get("color", _DEFAULT_COLOR),
        "jira_labels": entry.get("jira_labels", []),
        "tags": entry.get("tags", existing.get("tags", []) if existing else []),
        "keywords": entry.get("keywords", existing.get("keywords", []) if existing else []),
        "prompt_hint": entry.get("prompt_hint", existing.get("prompt_hint", "") if existing else ""),
    }
```

Это гарантирует, что Web UI, не передающая `keywords`/`prompt_hint`, не затрёт их.

---

## Приложение: сводка изменений по файлам

### Новые функции (в существующих файлах)

| Файл | Функция | Описание | Est. строк |
|---|---|---|---|
| `knowledge-engine/app/domain_config.py` | `build_keyword_map()` | `{keyword: domain}` map из конфига | ~30 |
| `knowledge-engine/app/domain_config.py` | `build_prompt_section()` | Текст доменов для LLM-промпта | ~25 |
| `knowledge-engine/app/domain_config.py` | `get_valid_domains()` | Tuple slugs из конфига | ~10 |
| `pm-bot/app/domain_config.py` | `build_keyword_map()` | То же (копия) | ~30 |
| `pm-bot/app/domain_config.py` | `build_prompt_section()` | То же (копия) | ~25 |
| `pm-bot/app/domain_config.py` | `get_valid_domains()` | То же (копия) | ~10 |
| `pm-bot/app/claude_client.py` | `_get_valid_domains()` | Dynamic valid domains с fallback | ~15 |
| `pm-bot/app/claude_client.py` | `_build_idea_prompt()` | Dynamic prompt с domain injection | ~25 |
| `pm-bot/app/claude_client.py` | `_inject_domains_section()` | Regex замена блока доменов в промпте | ~30 |
| `knowledge-engine/app/artifact_extractor.py` | `_merged_keyword_map()` | Config + hardcoded keywords merge | ~30 |
| `knowledge-engine/app/ingest.py` | `_merged_keyword_map()` | Config + hardcoded keywords merge | ~25 |

### Модификации существующих функций

| Файл | Функция | Тип изменения | Est. строк |
|---|---|---|---|
| `knowledge-engine/app/domain_config.py` | `validate_domain_entry()` | MODIFY: +валидация `keywords`, `prompt_hint` | +25 |
| `knowledge-engine/app/domain_config.py` | `set_domain()` | MODIFY: +`keywords`, `prompt_hint` в normalize | +5 |
| `knowledge-engine/app/domain_config.py` | `seed_from_defaults()` | MODIFY: обогащение из `_SEED_DOMAIN_DATA` | +15 |
| `pm-bot/app/domain_config.py` | `validate_domain_entry()` | MODIFY: +валидация `keywords`, `prompt_hint` | +25 |
| `pm-bot/app/domain_config.py` | `set_domain()` | MODIFY: merge с existing для новых полей | +10 |
| `pm-bot/app/claude_client.py` | `_validate_idea_data()` | MODIFY: dynamic valid domains | +5 |
| `pm-bot/app/claude_client.py` | `process_idea()` | MODIFY: use `_build_idea_prompt()` | +5 |
| `knowledge-engine/app/artifact_extractor.py` | `_detect_domain()` | MODIFY: use merged keyword map | +5 |
| `knowledge-engine/app/ingest.py` | `detect_domain()` | MODIFY: use `_merged_keyword_map()` | +5 |

### Итого

| Метрика | Значение |
|---|---|
| Новых функций | 11 |
| Модифицированных функций | 9 |
| Затронутых файлов | 5 (2 копии domain_config + claude_client + artifact_extractor + ingest) |
| Новых строк кода (оценка) | ~390 |
| Модифицированных строк (оценка) | ~100 |
| Файл промпта (idea.txt) | Без изменений (regex injection) |
