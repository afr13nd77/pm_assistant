"""Process-фаза очереди встреч (BL-145).

Этот модуль содержит:
  - `validate_protocol` — валидатор LLM-ответа (T-06, US-05, AC-06);
  - `process_one` — обработка ОДНОГО уже-claimed юнита (T-07, design §3.3);
  - `process_pending` — drain-проход по `pending/` с reclaim застрявших (T-07).

Process-воркер мигрирует пост-обработку из старого монолита `fetcher.py` (шаги 5b–5i):
LLM → валидация → inject source_file → classify → route → atomic_write →
jira_key_sync → enrich → LOG.md → notify → queue.complete. Источник входа теперь
не `EmailAttachment`, а юнит очереди (`Unit`). Частичный сбой пост-обработки —
non-fatal (design §4.6): юнит считается `done` сразу после `atomic_write` + `complete`,
провал enrich/jira/log/notify НЕ возвращает юнит в retry (иначе дубль протокола).

Блокирующее правило проекта: каждая функция логирует вход (unit_id) и исход.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import frontmatter

from shared.file_writer import atomic_write
from shared.llm_client import call_detailed
from shared.meeting_queue import Unit
from shared.settings import get

from .classifier import classify_type, make_daily_filename, make_filename, route_protocol
from .fetcher import (
    _build_fetcher_log_entry,
    _inject_source_file,
    _notify,
    _unique_filepath,
)
from .queue import MeetingQueue

logger = logging.getLogger(__name__)

# Параметры LLM-вызова протокола (design §3.3): тот же max_tokens, что и в
# claude_client.process_meeting_transcript; таймаут — из настроек очереди.
_PROTOCOL_MAX_TOKENS = 4000


def _load_meeting_prompt() -> str:
    """Загрузить промпт meeting_protocol (как claude_client._load_prompt).

    processor.py лежит в app/meeting_fetcher/, промпты — в app/prompts/.
    """
    path = Path(__file__).parent.parent / "prompts" / "meeting_protocol.txt"
    return path.read_text(encoding="utf-8")

# Минимальная длина валидного протокола.
# Источник: claude_client._MIN_RESPONSE_LENGTH['meeting_protocol'] = 200 — тот же порог,
# что уже применяется при проверке ответа LLM в claude_client._call_claude. Продублирован
# здесь как модульная константа, чтобы processor не зависел от claude_client.
MIN_PROTOCOL_LEN = 200

# Обязательные поля YAML frontmatter протокола (design §3.4).
REQUIRED_FM = ("type", "title", "date")


def validate_protocol(md: str) -> tuple[bool, str]:
    """Проверяет, что markdown-протокол пригоден для записи в wiki (US-05, AC-06).

    Проверки (design §3.4):
      1. len(md) >= MIN_PROTOCOL_LEN (200).
      2. Парсится YAML frontmatter (--- ... ---) через python-frontmatter.
      3. Обязательные поля frontmatter присутствуют и непустые: REQUIRED_FM.
      4. Тело после frontmatter содержит хотя бы один markdown-заголовок '## '.

    Returns:
        (True, '') при успехе, иначе (False, '<человекочитаемая причина>').

    Никогда не бросает: внутренняя логика обёрнута в try/except, при исключении
    возвращается (False, 'validation error: <...>').
    """
    try:
        if not isinstance(md, str):
            reason = f"protocol is not a string: {type(md).__name__}"
            logger.warning("validate_protocol: invalid — %s", reason)
            return False, reason

        # 1. Минимальная длина.
        if len(md) < MIN_PROTOCOL_LEN:
            reason = f"protocol too short: {len(md)} chars < {MIN_PROTOCOL_LEN} minimum"
            logger.warning("validate_protocol: invalid — %s", reason)
            return False, reason

        # 2. Парсинг frontmatter.
        post = frontmatter.loads(md)
        metadata = post.metadata or {}
        if not metadata:
            reason = "missing or empty YAML frontmatter"
            logger.warning("validate_protocol: invalid — %s", reason)
            return False, reason

        # 3. Обязательные поля присутствуют и непустые.
        for field in REQUIRED_FM:
            if field not in metadata:
                reason = f"missing required frontmatter field: '{field}'"
                logger.warning("validate_protocol: invalid — %s", reason)
                return False, reason
            value = metadata[field]
            if value is None or (isinstance(value, str) and not value.strip()):
                reason = f"empty required frontmatter field: '{field}'"
                logger.warning("validate_protocol: invalid — %s", reason)
                return False, reason

        # 4. Тело содержит хотя бы один markdown-заголовок '## '.
        body = post.content or ""
        has_heading = any(line.lstrip().startswith("## ") for line in body.splitlines())
        if not has_heading:
            reason = "body has no markdown section heading ('## ')"
            logger.warning("validate_protocol: invalid — %s", reason)
            return False, reason

        logger.info("validate_protocol: valid (%d chars)", len(md))
        return True, ""

    except Exception as e:  # noqa: BLE001 — функция НИКОГДА не бросает (AC-06)
        reason = f"validation error: {e}"
        logger.warning("validate_protocol: invalid — %s", reason)
        return False, reason


# --------------------------------------------------------------------------- #
# Process-воркер (design §3.3)
# --------------------------------------------------------------------------- #
def _parse_msg_date(meta: dict) -> datetime:
    """Разобрать дату письма/файла из meta для построения имени протокола.

    meta['date'] — ISO-8601 (build_meta пишет date.isoformat()). При отсутствии
    или невалидности — fallback на текущий момент (имя файла всё равно валидно).
    """
    raw = meta.get("date")
    try:
        if raw:
            return datetime.fromisoformat(raw)
    except (TypeError, ValueError) as exc:
        logger.warning("_parse_msg_date: bad meta.date=%r (%s), using now()", raw, exc)
    return datetime.now().astimezone()


def process_one(vault_path: str, unit: Unit, notify: bool = False) -> dict:
    """Обработать ОДИН уже-claimed юнит (лежит в processing/), design §3.3.

    Шаги (миграция логики старого fetcher 5b–5i, источник входа — Unit):
      1. raw_text из unit.txt_path.
      2. LLM `call_detailed(operation='meeting_protocol', ...)` → (text, provider_record).
      3. `validate_protocol(text)`. LLM-исключение ИЛИ невалид → `queue.fail(...)`
         (retry|failed); при 'failed' и notify — одно уведомление о неисправимом юните.
      4. Валид → inject source_file → classify → route → make[_daily]_filename →
         _unique_filepath → atomic_write (КРИТИЧЕСКИЙ шаг). Затем non-fatal пост-обработка
         (jira_key_sync, enrich, LOG.md, notify — каждый в своём try/except). Затем
         `queue.complete(...)`. Юнит done сразу после atomic_write+complete (design §4.6).

    Returns:
        {unit_id, result: 'done'|'requeued'|'failed', output_file?|error?}.
    """
    unit_id = unit.unit_id
    logger.info("process_one: started unit_id=%s (notify=%s)", unit_id, notify)
    q = MeetingQueue(vault_path)

    # ------------------------------------------------------------------ #
    # 1. Прочитать сырой транскрипт юнита.
    # ------------------------------------------------------------------ #
    try:
        raw_text = unit.txt_path.read_text(encoding="utf-8")
        logger.info("process_one: unit_id=%s raw transcript loaded (%d chars)",
                    unit_id, len(raw_text))
    except Exception as exc:  # noqa: BLE001 — чтение .txt не должно ронять проход
        logger.error("process_one: unit_id=%s failed to read .txt: %s", unit_id, exc)
        result = q.fail(unit, error=f"read error: {exc}", provider_record={})
        if result == "failed" and notify:
            _notify_failed(unit, f"read error: {exc}")
        return {"unit_id": unit_id, "result": result, "error": f"read error: {exc}"}

    # ------------------------------------------------------------------ #
    # 2. LLM-вызов с fallback-цепочкой (provider_record фиксирует перебор, AC-04).
    # ------------------------------------------------------------------ #
    text: str | None = None
    provider_record: dict = {}
    llm_error: str | None = None
    try:
        prompt = _load_meeting_prompt()
        user_content = f"{prompt}\n\n---\n\n{raw_text}"
        timeout = get("queue.process_timeout", 180)
        logger.info("process_one: unit_id=%s calling LLM (timeout=%s)", unit_id, timeout)
        text, provider_record = call_detailed(
            operation="meeting_protocol",
            messages=[{"role": "user", "content": user_content}],
            max_tokens=_PROTOCOL_MAX_TOKENS,
            timeout=timeout,
        )
        logger.info(
            "process_one: unit_id=%s LLM ok (provider=%s, %d chars)",
            unit_id, provider_record.get("used"), len(text or ""),
        )
    except Exception as exc:  # noqa: BLE001 — провал всей цепочки → retry-путь
        llm_error = str(exc)
        logger.error("process_one: unit_id=%s LLM call failed: %s", unit_id, exc)

    # ------------------------------------------------------------------ #
    # 3. Валидация. LLM-исключение ИЛИ невалидный ответ → fail (retry|failed).
    # ------------------------------------------------------------------ #
    if llm_error is not None:
        ok, reason = False, llm_error
    elif text is None:
        # Цепочка «успешна», но текста нет — трактуем как ошибочный путь до validate_protocol.
        ok, reason = False, "LLM returned empty response"
    else:
        ok, reason = validate_protocol(text)

    if not ok:
        logger.warning("process_one: unit_id=%s rejected before wiki write: %s",
                       unit_id, reason)
        result = q.fail(unit, error=reason, provider_record=provider_record)
        if result == "failed" and notify:
            _notify_failed(unit, reason)
        logger.info("process_one: unit_id=%s result=%s (no wiki write)", unit_id, result)
        return {"unit_id": unit_id, "result": result, "error": reason}

    # Инвариант: ok=True достижимо только из ветки validate_protocol(text), т.е. text — str.
    assert text is not None

    # ------------------------------------------------------------------ #
    # 4. Пост-обработка валидного протокола (миграция fetcher 5b-bis..5i).
    # ------------------------------------------------------------------ #
    try:
        # 4a. source_file ссылается на постоянный сырой архив done/<unit_id>.txt
        #     (целевой путь известен заранее — валиден после complete(), design §5).
        source_file_rel = f"raw/meeting-queue/done/{unit_id}.txt"
        try:
            protocol_md = _inject_source_file(text, source_file_rel)
        except Exception as src_err:  # noqa: BLE001 — инъекция non-fatal
            logger.warning(
                "process_one: unit_id=%s source_file injection failed (non-fatal): %s",
                unit_id, src_err,
            )
            protocol_md = text

        # 4b. Классификация + маршрутизация в папку wiki.
        subject = unit.meta.get("subject", "")
        protocol_type = classify_type(protocol_md, subject=subject)
        target_folder = route_protocol(protocol_type)
        target_dir = Path(vault_path) / target_folder
        target_dir.mkdir(parents=True, exist_ok=True)
        logger.info(
            "process_one: unit_id=%s type=%s folder=%s", unit_id, protocol_type, target_folder
        )

        # 4c. Имя файла (daily — глобальная нумерация, иначе из даты+subject).
        if protocol_type == "daily":
            filename = make_daily_filename(target_dir)
        else:
            filename = make_filename(_parse_msg_date(unit.meta), subject)
        target_path = _unique_filepath(target_dir, filename)

        # 4d. КРИТИЧЕСКИЙ шаг: атомарная запись протокола в wiki.
        atomic_write(str(target_path), protocol_md)
        output_file = str(target_path.relative_to(Path(vault_path))).replace("\\", "/")
        logger.info("process_one: unit_id=%s protocol written → %s", unit_id, output_file)
    except Exception as exc:
        # Запись протокола не удалась — это фатально для попытки → fail (retry|failed).
        logger.error("process_one: unit_id=%s protocol write failed: %s", unit_id, exc)
        result = q.fail(unit, error=f"write error: {exc}", provider_record=provider_record)
        if result == "failed" and notify:
            _notify_failed(unit, f"write error: {exc}")
        return {"unit_id": unit_id, "result": result, "error": f"write error: {exc}"}

    # ------------------------------------------------------------------ #
    # Non-fatal пост-обработка (design §4.6): провал НЕ возвращает юнит в retry.
    # ------------------------------------------------------------------ #
    jira_sync_detail: dict = {}
    # 4e. Jira key sync (импорт упомянутых ключей + патч ссылок).
    try:
        from ..jira_key_sync import patch_jira_links, sync_jira_keys

        jira_sync_detail = sync_jira_keys(protocol_md, vault_path)
        patch_jira_links(str(target_path), jira_sync_detail.get("keys_map", {}))
        logger.info(
            "process_one: unit_id=%s jira_key_sync keys=%d imported=%d",
            unit_id, len(jira_sync_detail.get("keys", [])),
            len(jira_sync_detail.get("imported", [])),
        )
    except Exception as jira_err:  # noqa: BLE001
        logger.warning(
            "process_one: unit_id=%s jira_key_sync failed (non-fatal): %s", unit_id, jira_err
        )

    # 4f. Обогащение (поиск связей в vault).
    links_found = 0
    try:
        from ..enricher import enrich

        enrich_result = enrich(str(target_path), vault_path)
        links_found = enrich_result.get("links_found", 0) if isinstance(enrich_result, dict) else 0
        logger.info("process_one: unit_id=%s enrich links_found=%d", unit_id, links_found)
    except Exception as enrich_err:  # noqa: BLE001
        logger.warning(
            "process_one: unit_id=%s enrichment failed (non-fatal): %s", unit_id, enrich_err
        )

    # 4g. Запись строки в корневой wiki/LOG.md.
    try:
        from ..ingest import _append_root_log

        log_entry = _build_fetcher_log_entry(
            filename=target_path.name,
            protocol_type=protocol_type,
            protocol_md=protocol_md,
            msg_date=_parse_msg_date(unit.meta),
            target_folder=target_folder,
        )
        _append_root_log(log_entry)
        logger.info("process_one: unit_id=%s LOG.md entry appended", unit_id)
    except Exception as log_err:  # noqa: BLE001
        logger.warning(
            "process_one: unit_id=%s LOG.md append failed (non-fatal): %s", unit_id, log_err
        )

    # 4h. Уведомление об успехе.
    if notify:
        try:
            notify_text = (
                "Протокол встречи готов\n\n"
                f"Файл: {target_path.name}\n"
                f"Тип: {protocol_type}\n"
                f"Папка: {target_folder}/\n"
                f"Связей найдено: {links_found}"
            )
            if jira_sync_detail.get("keys"):
                notify_text += f"\nЗадачи: {', '.join(jira_sync_detail['keys'])}"
            _notify(notify_text)
            logger.info("process_one: unit_id=%s success notification sent", unit_id)
        except Exception as notify_err:  # noqa: BLE001
            logger.warning(
                "process_one: unit_id=%s notify failed (non-fatal): %s", unit_id, notify_err
            )

    # ------------------------------------------------------------------ #
    # 4i. Финализация: complete() переносит юнит processing→done (status=done).
    # ------------------------------------------------------------------ #
    q.complete(
        unit,
        output_file=output_file,
        protocol_type=protocol_type,
        provider_record=provider_record,
    )
    logger.info("process_one: unit_id=%s done (output_file=%s)", unit_id, output_file)
    return {"unit_id": unit_id, "result": "done", "output_file": output_file}


def _notify_failed(unit: Unit, reason: str) -> None:
    """Одно уведомление о неисправимом юните (исчерпан max_attempts), design §3.3."""
    try:
        _notify(
            "Meeting Fetcher: юнит помечен как необработаемый\n\n"
            f"Тема: {unit.meta.get('subject', '')}\n"
            f"unit_id: {unit.unit_id}\n"
            f"Причина: {reason}\n"
            f"Транскрипт сохранён в raw/meeting-queue/failed/"
        )
        logger.info("_notify_failed: notified for unit_id=%s", unit.unit_id)
    except Exception as exc:  # noqa: BLE001 — уведомление non-fatal
        logger.warning("_notify_failed: notify failed for unit_id=%s: %s", unit.unit_id, exc)


def process_pending(
    vault_path: str, limit: int | None = None, notify: bool = False
) -> dict:
    """Drain-проход по очереди: reclaim застрявших + обработка pending по одному.

    Поведение (design §3.3):
      1. `reclaim_stuck(queue.stuck_threshold_seconds)` — подмести застрявшие в processing/.
      2. Цикл `claim_next() → process_one()` пока pending не пуст и не достигнут лимит.
         Лимит: `limit` None ⇒ без лимита; иначе стоп после `limit` обработанных юнитов.
         При `limit` None дополнительно учитывается `queue.batch_limit` (0 ⇒ без лимита).

    Returns:
        {status, reclaimed, processed, failed, requeued, details}.
    """
    logger.info("process_pending: started vault_path=%s limit=%s notify=%s",
                vault_path, limit, notify)
    q = MeetingQueue(vault_path)

    reclaimed = q.reclaim_stuck(get("queue.stuck_threshold_seconds", 1800))
    logger.info("process_pending: reclaim_stuck returned %d unit(s)", len(reclaimed))

    # Разрешить эффективный лимит: явный limit > batch_limit > без лимита.
    effective_limit = limit
    if effective_limit is None:
        batch_limit = get("queue.batch_limit", 0)
        if isinstance(batch_limit, int) and batch_limit > 0:
            effective_limit = batch_limit
            logger.info("process_pending: applying batch_limit=%d", effective_limit)

    processed = failed = requeued = 0
    details: list[dict] = []
    count = 0

    try:
        while True:
            if effective_limit is not None and count >= effective_limit:
                logger.info("process_pending: limit reached (%d)", effective_limit)
                break
            unit = q.claim_next()
            if unit is None:
                logger.info("process_pending: pending drained (processed=%d)", count)
                break
            res = process_one(vault_path, unit, notify=notify)
            count += 1
            result = res.get("result")
            if result == "done":
                processed += 1
            elif result == "failed":
                failed += 1
            elif result == "requeued":
                requeued += 1
            details.append(res)
    except Exception as exc:
        logger.error("process_pending: loop aborted unexpectedly: %s", exc)
        raise

    summary = {
        "status": "ok",
        "reclaimed": len(reclaimed),
        "processed": processed,
        "failed": failed,
        "requeued": requeued,
        "details": details,
    }
    logger.info(
        "process_pending: completed reclaimed=%d processed=%d failed=%d requeued=%d",
        len(reclaimed), processed, failed, requeued,
    )
    return summary
