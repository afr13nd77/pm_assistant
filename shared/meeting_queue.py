"""Enqueue-ядро файловой очереди обработки встреч (BL-145).

Этот модуль — общая часть очереди, доступная ОБОИМ контейнерам монорепо
(knowledge-engine и pm-bot), т.к. оба линкуют `shared/`. Здесь живёт только
ПОСТАНОВКА юнита в очередь (`enqueue`) и сопутствующие примитивы:
- структура папок-статусов `raw/meeting-queue/{pending,processing,done,failed}`,
- модель юнита (`Unit`),
- генерация детерминированного `unit_id` (`make_unit_id`),
- схема сайдкара `meta.json` (`build_meta`, `META_SCHEMA_VERSION`).

Операции обработки (claim/complete/fail/...) живут в KE-шном
`knowledge-engine/app/meeting_fetcher/queue.py` и импортируют это ядро.

Зависимости — только: `shared.file_writer.atomic_write`, `shared.settings`,
`shared.vault_paths`. Никаких импортов knowledge-engine (design §3.2, §4.7).

См. design.md §2.1–2.4, §3.2 и requirements AC-01, AC-03, AC-07.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from shared import settings
from shared.file_writer import atomic_write

logger = logging.getLogger(__name__)

META_SCHEMA_VERSION = 1

# Подпапка очереди внутри vault (общий /vault volume для обоих контейнеров).
_QUEUE_SUBPATH = ("raw", "meeting-queue")


@dataclass
class Unit:
    """Юнит работы очереди = пара файлов с общим unit_id (design §2.2).

    Attributes:
        unit_id:   уникальный идентификатор (см. make_unit_id).
        txt_path:  путь к <unit_id>.txt — сырой транскрипт (не модифицируется).
        meta_path: путь к <unit_id>.meta.json — сайдкар-метаданные.
        meta:      разобранное содержимое meta.json (dict).
    """

    unit_id: str
    txt_path: Path
    meta_path: Path
    meta: dict


# --------------------------------------------------------------------------- #
# Хелперы путей очереди (design §2.1). Все создают директорию при обращении.
# --------------------------------------------------------------------------- #
def _ensure_dir(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


def meeting_queue_root(vault_path: str | Path) -> Path:
    """Корень очереди: <vault_path>/raw/meeting-queue/ (создаётся)."""
    root = Path(vault_path).joinpath(*_QUEUE_SUBPATH)
    logger.debug("meeting_queue_root: resolving %s", root)
    return _ensure_dir(root)


def meeting_queue_pending(vault_path: str | Path) -> Path:
    """Папка pending/ — юниты ждут обработки (наполняет Fetch)."""
    return _ensure_dir(meeting_queue_root(vault_path) / "pending")


def meeting_queue_processing(vault_path: str | Path) -> Path:
    """Папка processing/ — юнит claimed воркером, идёт LLM-обработка."""
    return _ensure_dir(meeting_queue_root(vault_path) / "processing")


def meeting_queue_done(vault_path: str | Path) -> Path:
    """Папка done/ — успешно обработанные (= постоянный сырой архив)."""
    return _ensure_dir(meeting_queue_root(vault_path) / "done")


def meeting_queue_failed(vault_path: str | Path) -> Path:
    """Папка failed/ — исчерпан max_attempts или неустранимо повреждён."""
    return _ensure_dir(meeting_queue_root(vault_path) / "failed")


# --------------------------------------------------------------------------- #
# Генерация unit_id и схема meta.json
# --------------------------------------------------------------------------- #
def make_unit_id(
    *,
    source: str,
    date: datetime,
    message_id: str | None = None,
    source_filename: str | None = None,
    content_sha: str,
) -> str:
    """Детерминированный unit_id вида <YYYYMMDD-HHMMSS>-<source>-<sha1(dedup_key)[:10]>.

    dedup_key:
        - email: message_id;
        - local: f"{source_filename}:{content_sha}".

    Детерминирован: одинаковый dedup_key + одинаковая секунда date → один id
    (повторный enqueue idempotent, design §2.3).
    """
    try:
        if source == "email":
            dedup_key = message_id or ""
        else:
            dedup_key = f"{source_filename or ''}:{content_sha}"

        if not dedup_key.strip(":"):
            logger.warning(
                "make_unit_id: empty dedup_key (source=%s, message_id=%s, "
                "source_filename=%s) — id may collide",
                source,
                message_id,
                source_filename,
            )

        short_hash = hashlib.sha1(dedup_key.encode("utf-8")).hexdigest()[:10]
        ts = date.strftime("%Y%m%d-%H%M%S")
        unit_id = f"{ts}-{source}-{short_hash}"
        logger.info(
            "make_unit_id: generated unit_id=%s (source=%s)", unit_id, source
        )
        return unit_id
    except Exception as exc:
        logger.error(
            "make_unit_id: failed (source=%s, message_id=%s, source_filename=%s): %s",
            source,
            message_id,
            source_filename,
            exc,
        )
        raise


def build_meta(
    *,
    unit_id: str,
    source: str,
    subject: str,
    date: datetime,
    message_id: str | None = None,
    source_filename: str | None = None,
    content_sha: str,
    max_attempts: int,
) -> dict:
    """Сформировать dict meta.json по схеме design §2.4.

    status='pending', attempts=0, provider_history=[], output_file/protocol_type
    /last_error = None. created_at == updated_at == момент вызова (ISO-8601).
    """
    try:
        now_iso = datetime.now().astimezone().isoformat()
        meta = {
            "unit_id": unit_id,
            "schema_version": META_SCHEMA_VERSION,
            "source": source,
            "message_id": message_id,
            "source_filename": source_filename,
            "subject": subject,
            "date": date.isoformat(),
            "content_sha": content_sha,
            "status": "pending",
            "attempts": 0,
            "max_attempts": max_attempts,
            "last_error": None,
            "provider_history": [],
            "output_file": None,
            "protocol_type": None,
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        logger.info("build_meta: built meta for unit_id=%s", unit_id)
        return meta
    except Exception as exc:
        logger.error("build_meta: failed for unit_id=%s: %s", unit_id, exc)
        raise


def _content_sha(raw_text: str) -> str:
    """sha256 сырого текста в формате 'sha256:<hex>' (целостность .txt, дедуп local)."""
    digest = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


# --------------------------------------------------------------------------- #
# Постановка в очередь
# --------------------------------------------------------------------------- #
def enqueue(
    vault_path: str | Path,
    *,
    raw_text: str,
    source: str,
    subject: str,
    date: datetime,
    message_id: str | None = None,
    source_filename: str | None = None,
    max_attempts: int | None = None,
) -> Unit | None:
    """Поставить транскрипт в очередь: пара <unit_id>.txt + .meta.json в pending/.

    Поведение (design §3.2, §5):
      - Пустой raw_text (len(raw_text.strip()) == 0) → лог warning, вернуть None
        (юнит НЕ создаётся — нечего обрабатывать). Выбрана семантика None, а не
        исключение: вызывающие watcher/fetcher не должны падать на пустом файле.
      - content_sha = sha256(raw_text) в формате 'sha256:<hex>'.
      - max_attempts None ⇒ settings.get('queue.max_attempts', 5).
      - Порядок записи ВАЖЕН: сначала atomic_write(.meta.json), ПОТОМ
        atomic_write(.txt) — .txt появляется последним, чтобы on_created/claim
        видели уже готовый meta рядом (design §4.4, §5).
      - Idempotent: если <unit_id>.txt уже существует в pending/ — лог info,
        вернуть существующий Unit (не перезаписывать).

    Returns:
        Unit при успешной постановке (или существующий при idempotent-повторе),
        None если raw_text пуст.
    """
    if len(raw_text.strip()) == 0:
        logger.warning(
            "enqueue: empty raw_text (source=%s, subject=%r) — skip, nothing to process",
            source,
            subject,
        )
        return None

    try:
        if max_attempts is None:
            max_attempts = settings.get("queue.max_attempts", 5)

        content_sha = _content_sha(raw_text)
        unit_id = make_unit_id(
            source=source,
            date=date,
            message_id=message_id,
            source_filename=source_filename,
            content_sha=content_sha,
        )

        pending = meeting_queue_pending(vault_path)
        txt_path = pending / f"{unit_id}.txt"
        meta_path = pending / f"{unit_id}.meta.json"

        # Idempotent: .txt — последний записываемый файл, его наличие = юнит готов.
        if txt_path.exists():
            logger.info(
                "enqueue: unit already enqueued (idempotent) unit_id=%s, "
                "returning existing", unit_id,
            )
            try:
                existing_meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning(
                    "enqueue: existing unit_id=%s has unreadable meta (%s), "
                    "returning empty meta", unit_id, exc,
                )
                existing_meta = {}
            return Unit(
                unit_id=unit_id,
                txt_path=txt_path,
                meta_path=meta_path,
                meta=existing_meta,
            )

        meta = build_meta(
            unit_id=unit_id,
            source=source,
            subject=subject,
            date=date,
            message_id=message_id,
            source_filename=source_filename,
            content_sha=content_sha,
            max_attempts=max_attempts,
        )

        # Порядок важен: meta.json первым, .txt — последним (замок для claim).
        atomic_write(meta_path, json.dumps(meta, ensure_ascii=False, indent=2))
        atomic_write(txt_path, raw_text)

        logger.info(
            "enqueue: enqueued unit_id=%s (source=%s, attempts=0, pending/)",
            unit_id,
            source,
        )
        return Unit(
            unit_id=unit_id,
            txt_path=txt_path,
            meta_path=meta_path,
            meta=meta,
        )
    except Exception as exc:
        logger.error(
            "enqueue: failed (source=%s, subject=%r): %s", source, subject, exc
        )
        raise
