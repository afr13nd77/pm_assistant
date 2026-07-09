# BUG-021: Jira Import по прямому ключу не работает в extended capture terminal

## Статус: FIXED
## Severity: major
## Дата: 09.07.2026
## Компонент: web-ui (components.js — capture-terminal)

## Наблюдаемое поведение

В extended-режиме capture terminal на ideas.html: пользователь вводит номер задачи (например `SUP-1234`) в поле "Direct Key" — кнопка IMPORT остаётся неактивной (disabled). Импорт не запускается.

## Ожидаемое поведение

Ввод ключа задачи в поле direct key и нажатие IMPORT должно запускать `api.jiraImport(key)` — аналогично тому, как работает simple-режим с типом `jira_import`.

## Шаги воспроизведения

1. Открыть ideas.html
2. Переключить capture terminal в режим EXTENDED
3. Активировать панель Jira Import
4. НЕ выбирать проект и тип задачи
5. Ввести номер задачи (напр. `SUP-1234`) в поле direct key
6. Нажать кнопку IMPORT → кнопка disabled, ничего не происходит

## Root cause

Поле `directKey` (data property, строка 1645) привязано к input (строка 2196), но **нигде не используется в логике импорта**.

Computed property `canImport` (строка 1683) проверяет только `selectedTicketIds.length > 0`:

```javascript
canImport: function() {
  return this.selectedTicketIds.length > 0 && !this.importing;
},
```

Массив `selectedTicketIds` наполняется только кликом по тикетам из списка (`toggleTicket()`, строка 1809). Ввод в `directKey` никак не влияет на `selectedTicketIds` → `canImport` всегда `false` → кнопка IMPORT disabled.

Метод `importSelected()` (строка 1820) тоже работает только с `selectedTicketIds` и не обращается к `directKey`.

**В simple-режиме импорт по ключу работает**: `simpleCapture()` (строка 1865) при `captureType === 'jira_import'` вызывает `api.jiraImport(text)` напрямую (строка 1876). В extended-режиме этот путь отсутствует.

## Файлы

- `pm-bot/web/components.js`: строки 1593–2276 (capture-terminal component)
  - `directKey` data: строка 1645
  - `canImport` computed: строка 1683
  - `importSelected()`: строка 1820
  - `directKey` input: строка 2196
  - Import button: строка 2261

## Fix (направление)

1. В `canImport` добавить проверку `directKey`:
   ```javascript
   canImport: function() {
     return (this.selectedTicketIds.length > 0 || this.directKey.trim()) && !this.importing;
   },
   ```

2. В `importSelected()` добавить обработку `directKey`:
   - Если `directKey` заполнен — вызвать `api.jiraImport(directKey.trim())`
   - Если есть и `directKey`, и `selectedTicketIds` — импортировать все
   - После импорта очистить `directKey`

3. В `handleExtKeydown` (Ctrl+Enter) — аналогично учитывать `directKey`.
