# BUG-022: Список задач Jira не фильтруется по введённому ключу

## Статус: FIXED
## Severity: minor
## Дата: 09.07.2026
## Компонент: web-ui (components.js — capture-terminal)

## Наблюдаемое поведение

В extended-режиме capture terminal на ideas.html: пользователь выбирает проект, загружается список задач. Вводит номер задачи (напр. `SUP-1234`) в поле direct key — список задач не фильтруется, продолжает показывать все задачи проекта.

## Ожидаемое поведение

При вводе ключа задачи в поле direct key список задач должен фильтроваться, показывая только задачи, ключ которых содержит введённый текст.

## Шаги воспроизведения

1. Открыть ideas.html
2. Переключить capture terminal в режим EXTENDED
3. Активировать панель Jira Import
4. Выбрать проект (напр. SUP)
5. Дождаться загрузки списка задач
6. Ввести номер задачи (напр. `SUP-1234`) в поле direct key
7. Наблюдать: список задач не изменился, фильтрация не произошла

## Root cause

Computed property `filteredTickets` (строки 1669–1675) фильтрует только по `typeFilter` и `statusFilter`, не учитывая `directKey`:

```javascript
filteredTickets: function() {
  var self = this;
  return this.tickets.filter(function(t) {
    if (self.typeFilter && t.type !== self.typeFilter) return false;
    if (self.statusFilter && t.status !== self.statusFilter) return false;
    return true;
  });
},
```

Поле `directKey` не участвует в фильтрации.

## Файлы

- `pm-bot/web/components.js`: строки 1593–2276 (capture-terminal component)
  - `directKey` data: строка 1645
  - `filteredTickets` computed: строки 1669–1675
  - `directKey` input: строка 2196

## Fix (направление)

Добавить фильтрацию по `directKey` в `filteredTickets`:

```javascript
filteredTickets: function() {
  var self = this;
  var keyFilter = self.directKey.trim().toUpperCase();
  return this.tickets.filter(function(t) {
    if (self.typeFilter && t.type !== self.typeFilter) return false;
    if (self.statusFilter && t.status !== self.statusFilter) return false;
    if (keyFilter && t.key.toUpperCase().indexOf(keyFilter) === -1) return false;
    return true;
  });
},
```

Это позволит пользователю быстро найти нужную задачу в длинном списке.
