# BL-119: Единый источник domain-правил — Requirements

**Status:** DRAFT
**Created:** 12.06.2026
**Связь:** расширяет реализованную спеку docs/domain-config/ (jira_labels + Web UI CRUD)

---

## 1.1 Overview

Консолидировать все определения доменов из 6 разрозненных источников в единый конфиг `domain-config.yaml`. Сейчас domain detection дублируется в коде и промптах, при этом `partner-search-engine` отсутствует в 3 из 6 источников.

**Что решает:** добавление/изменение домена требует правки 6 файлов в 3 сервисах. Результат — рассинхрон (partner-search-engine не распознаётся pm-bot). Единый конфиг устраняет дублирование и гарантирует консистентность.

**Пользователь:** продакт-менеджер (владелец vault).

**Базис:** domain-config.yaml УЖЕ реализован (спека docs/domain-config/, T-01..T-14 done) — содержит `display_name`, `description`, `color`, `jira_labels`. BL-119 расширяет его полями `tags`, `keywords`, `prompt_hint`, а все компоненты переводит на чтение из конфига.

---

## 1.2 User Stories

```
US-01: Как PM, я хочу добавить новый домен один раз в domain-config.yaml, и чтобы ВСЕ компоненты (capture, enrichment, Jira sync, LLM-промпты, artifact extraction) автоматически начали его распознавать.

US-02: Как PM, я хочу чтобы при capture идеи через Telegram Claude знал про все домены из конфига (включая partner-search-engine), а не только про захардкоженный список.

US-03: Как PM, я хочу управлять ключевыми словами и тегами для domain detection через domain-config.yaml (и Web UI), чтобы не править Python-код.

US-04: Как PM, я хочу чтобы при отсутствии domain-config.yaml система работала как раньше (fallback на хардкод), без сбоев.
```

---

## 1.3 Текущее состояние: 6 источников domain-правил

| # | Файл | Тип данных | partner-search-engine | Что читает |
|---|---|---|---|---|
| 1 | `pm-bot/app/claude_client.py:16` | `_VALID_DOMAINS` tuple | **ОТСУТСТВУЕТ** | Валидация домена при capture идеи |
| 2 | `pm-bot/app/prompts/idea.txt:6-10` | Текст промпта для Claude | **ОТСУТСТВУЕТ** | Инструкция Claude для классификации идеи |
| 3 | `knowledge-engine/app/artifact_extractor.py:23-33` | `_DOMAIN_KEYWORDS` dict | **ОТСУТСТВУЕТ** | Domain detection для артефактов из встреч |
| 4 | `knowledge-engine/app/jira_fetcher/mapper.py:46-51` | `LABEL_TO_DOMAIN` dict | Есть | Jira label → domain (уже читает из конфига) |
| 5 | `knowledge-engine/app/ingest.py:24-118` | `TAG_TO_DOMAIN` + `KEYWORD_TO_DOMAIN` | Есть | Domain detection для клиппингов |
| 6 | `pm-bot/app/vault_api.py:1967` | `LABEL_TO_DOMAIN` seed dict | Есть | Seeding domain-config.yaml |

**Уже решено (docs/domain-config/):** источник #4 (mapper.py) читает `jira_labels` из конфига.

**Нужно решить (BL-119):** источники #1, #2, #3, #5 — перевести на чтение из конфига.

---

## 1.4 User Flows

```
FLOW-01: Добавление нового домена — единая точка входа
1. PM добавляет домен в domain-config.yaml (через Web UI или вручную):
   - slug, display_name, description, color
   - jira_labels (для Jira sync)
   - tags (для классификации клиппингов и артефактов)
   - keywords (для keyword-based detection)
   - prompt_hint (описание домена для LLM-промпта)
2. При следующем capture идеи через Telegram:
   → Claude получает обновлённый промпт с новым доменом
   → Валидация домена проходит (новый домен в valid list)
3. При следующем Jira sync:
   → Лейблы нового домена распознаются
4. При обработке клиппинга/артефакта:
   → Теги и ключевые слова нового домена используются
5. Ни один Python-файл не нужно менять

FLOW-02: Capture идеи с partner-search-engine (текущий баг)
1. PM отправляет в Telegram: "Идея: добавить B2B-фильтр для поставщиков"
2. Claude классифицирует → domain: "partner-search-engine"
   → СЕЙЧАС: _VALID_DOMAINS не содержит partner-search-engine → fallback на "general"
   → ПОСЛЕ BL-119: domain-config.yaml содержит partner-search-engine → валидация проходит → файл создаётся в wiki/domains/partner-search-engine/ideas/

FLOW-03: Генерация LLM-промпта из конфига
1. При вызове process_idea() в claude_client.py:
2. Система читает domain-config.yaml
3. Для каждого домена берёт prompt_hint (или description как fallback)
4. Формирует секцию промпта:
   "- static-metadata — справочники, классификаторы, атрибуты..."
   "- partner-search-engine — работа с поставщиками, B2B, партнёрский поиск..."
5. Claude получает полный список доменов с описаниями
```

---

## 1.5 Расширение формата domain-config.yaml

Текущий формат (реализован):

```yaml
domains:
  search-engine:
    display_name: "Поисковый движок"
    description: "Поиск отелей и квартир: фильтры, сортировка, выдача"
    color: "#2196F3"
    jira_labels:
      - search
```

Расширенный формат (BL-119):

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

  partner-search-engine:
    display_name: "Поиск партнёров"
    description: "Работа с продавцами Суточно: поиск, фильтрация, профили"
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
```

Новые поля:
- `tags` — список тегов для tag-based detection (используется ingest.py, artifact_extractor.py)
- `keywords` — список ключевых слов для keyword-based detection (используется ingest.py, artifact_extractor.py)
- `prompt_hint` — текст для LLM-промпта (используется claude_client.py для генерации секции доменов). Если пуст — используется `description`

---

## 1.6 Acceptance Criteria

```
AC-01 (US-01):
  GIVEN: domain-config.yaml содержит домен "payments" с tags, keywords, prompt_hint
  WHEN: PM отправляет идею "оплата картой через acquiring"
  THEN: Claude классифицирует идею в домен "payments"
        AND _VALID_DOMAINS содержит "payments" (динамически из конфига)
        AND файл создаётся в wiki/domains/payments/ideas/

AC-02 (US-02):
  GIVEN: domain-config.yaml содержит partner-search-engine с prompt_hint
  WHEN: PM отправляет идею "добавить B2B-фильтр для поставщиков"
  THEN: Claude классифицирует → partner-search-engine
        AND валидация проходит (домен в valid list)
        AND файл создаётся в wiki/domains/partner-search-engine/ideas/

AC-03 (US-02):
  GIVEN: domain-config.yaml содержит 5 доменов
  WHEN: вызывается process_idea()
  THEN: промпт для Claude содержит все 5 доменов с prompt_hint
        AND промпт НЕ содержит захардкоженный список

AC-04 (US-03):
  GIVEN: domain-config.yaml содержит search-engine с tags: [search, ranking]
  WHEN: ingest.py обрабатывает клиппинг с тегом "ranking"
  THEN: клиппинг маршрутизируется в search-engine
        AND лог: "domain detected from config tag: search-engine"

AC-05 (US-03):
  GIVEN: domain-config.yaml содержит suggester с keywords: [автокомплит, подсказка]
  WHEN: artifact_extractor.py обрабатывает текст "реализовать автокомплит по городам"
  THEN: артефакт маршрутизируется в suggester
        AND лог: "domain detected from config keyword: suggester"

AC-06 (US-04):
  GIVEN: domain-config.yaml отсутствует
  WHEN: PM отправляет идею через Telegram
  THEN: claude_client.py fallback на хардкоженный _VALID_DOMAINS
        AND промпт fallback на хардкоженный список в idea.txt
        AND лог: "domain-config.yaml not found, using hardcoded defaults"
        AND идея обрабатывается без ошибок

AC-07 (US-04):
  GIVEN: domain-config.yaml отсутствует
  WHEN: ingest.py обрабатывает клиппинг
  THEN: fallback на хардкоженный TAG_TO_DOMAIN и KEYWORD_TO_DOMAIN
        AND клиппинг обрабатывается без ошибок

AC-08 (US-03):
  GIVEN: PM добавил в domain-config.yaml новый keyword "микросервисы" для домена search-engine
  WHEN: следующий вызов artifact_extractor.py обрабатывает текст с "микросервисы"
  THEN: текст маршрутизируется в search-engine
        AND НЕ требуется перезапуск сервиса (mtime-cache обновляется автоматически)
```

---

## 1.7 Out of Scope

- **Web UI для tags/keywords** — первая итерация: ручное редактирование YAML. Web UI для tags/keywords — отдельная фича
- **Приоритеты между доменами при keyword-коллизии** — оставить текущую логику (первый match)
- **Семантический поиск вместо keyword match** — это BL-22, отдельная задача
- **Валидация keywords/tags через Web UI** — первая итерация без UI
- **Миграция существующих файлов** — файлы, уже классифицированные в general, не перемещаются

---

## 1.8 Dependencies

| Зависимость | Тип | Описание |
|---|---|---|
| `domain-config.yaml` (реализован) | Internal | Базовый конфиг с jira_labels, display_name, color — расширяем tags/keywords/prompt_hint |
| `domain_config.py` (реализован) | Internal | Reader/writer — расширяем build_tag_map(), build_keyword_map(), build_prompt_section() |
| `pm-bot/app/claude_client.py` | Internal | _VALID_DOMAINS → динамический из конфига |
| `pm-bot/app/prompts/idea.txt` | Internal | Статический промпт → динамическая генерация секции доменов |
| `knowledge-engine/app/ingest.py` | Internal | TAG_TO_DOMAIN, KEYWORD_TO_DOMAIN → из конфига |
| `knowledge-engine/app/artifact_extractor.py` | Internal | _DOMAIN_KEYWORDS → из конфига |
