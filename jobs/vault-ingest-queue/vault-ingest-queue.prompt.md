Ты обрабатываешь очередь необработанных raw-файлов в базе знаний (Obsidian vault PM Суточно.ру). Рабочая директория — корень vault.

Сначала прочитай CLAUDE.md в корне vault — он определяет все правила. Ключевые секции: ingest_dod (§6a, definition of done), ingest_rules (§6), domain_detection (§3), index_rules (§7), logging/always_log (§15).

Алгоритм:
1. Построй очередь: raw-файл считается НЕобработанным, если в wiki/ нет ни одного артефакта с frontmatter `source:`, указывающим на него (критерий 1 ingest_dod). Проверяй через grep по wiki/ значения `source:`. Области: raw/inbound/meeting-notes/, raw/inbound/clippings/, raw/inbound/misc/, raw/inbound/ideas/. НЕ трогай raw/competitors/ (только по команде /compile-competitor-report), raw/inbound/daily-logs/ и свежие транскрипты — текущий поток обрабатывает knowledge-engine.
2. Возьми батч 10–15 файлов, начиная с самых свежих по дате в имени.
3. Каждый файл обработай по ingest_rules: определи домен по domain_detection (при неоднозначности — домен по умолчанию static-metadata + warning в LOG.md, не задавай вопросов — сессия автономная), создай артефакт в wiki/ с frontmatter `source:` — это ВСЕГДА путь к raw-файлу (критерий 1 ingest_dod, по нему определяется очередь). URL оригинала для клиппингов — в отдельное поле `original:`. Если несколько raw-клиппингов — дубли одной страницы (один и тот же URL внутри): создай ОДИН артефакт и перечисли все raw-пути списком в `source:`, дубль-артефакты не плодить. Если для raw-файла уже существует артефакт по той же теме (проверь по original:/заголовку) — добавь raw-путь в его `source:` вместо создания нового. Для meeting-notes: решения → decisions.md домена, action items → wiki/domains/{domain}/tasks/.
4. После КАЖДОЙ записи в wiki/ за пределами wiki/domains/ — сразу запись в корневой wiki/LOG.md (правило always_log, формат [ISO-дата] ACTION file_path → описание). Изменения внутри домена — запись в log.md домена и обновление index.md домена. ВАЖНО: wiki/LOG.md и все log.md — append-only: добавляй строки строго в конец файла, НИКОГДА не переписывай лог-файл целиком (прерванная перезапись уже приводила к потере данных).
5. Raw-файлы не редактируй и не переноси.
6. В конце прогона добавь в wiki/LOG.md итоговую запись: сколько обработано, сколько осталось в очереди (по областям).

Контекст: задача BL-118 из I:\ai_projects\pm_assistant\BACKLOG.md, аудит wiki/reports/audit-2026-06-10-system-maturity.md (Н-2, Б-1).
