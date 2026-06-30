"""Операции обработки файловой очереди встреч (BL-145, design §3.2).

Этот модуль — KE-шная часть очереди. Здесь живут ОПЕРАЦИИ ОБРАБОТКИ, нужные только
Process-воркеру (claim/claim_next/complete/fail/requeue/reclaim_stuck/status_counts).
Постановка в очередь (`enqueue`) и примитивы (`Unit`, схема meta, хелперы путей) живут
в общем ядре `shared.meeting_queue` и импортируются сюда (design §3.2, §4.7).

Ключевые инварианты:
- Статус юнита определяется ПАПКОЙ, в которой лежит пара <id>.txt + <id>.meta.json
  (design §2.2). `meta.status` дублирует папку и обновляется при каждом переходе.
- claim делается по `.txt` через `os.rename` (НЕ `os.replace`) — единичный rename =
  «замок»; проигравший гонку получает FileNotFoundError (design §4.4). `.meta.json`
  переносится следом best-effort.
- Запись meta — только через `shared.file_writer.atomic_write` (temp+rename).
- Повреждённый `meta.json` (JSONDecodeError) → юнит в `failed/` с last_error='corrupt meta',
  проход не падает (изоляция сбоев, design §5).

Блокирующее правило проекта: каждый метод логирует вход (unit_id) и исход (успех/ошибка).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path

from shared.file_writer import atomic_write
from shared.meeting_queue import (
    Unit,
    enqueue,
    meeting_queue_done,
    meeting_queue_failed,
    meeting_queue_pending,
    meeting_queue_processing,
)

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    """Текущий момент в ISO-8601 с таймзоной (как в shared.meeting_queue.build_meta)."""
    return datetime.now().astimezone().isoformat()


def _dump_meta(meta: dict) -> str:
    """Сериализовать meta-dict в JSON в том же формате, что и ядро enqueue."""
    return json.dumps(meta, ensure_ascii=False, indent=2)


class MeetingQueue:
    """Обёртка над папками очереди для Process-воркера (design §3.2).

    enqueue делегируется ядру `shared.meeting_queue`; здесь — переходы статусов.
    """

    def __init__(self, vault_path: str) -> None:
        self.vault_path = vault_path
        self._pending = meeting_queue_pending(vault_path)
        self._processing = meeting_queue_processing(vault_path)
        self._done = meeting_queue_done(vault_path)
        self._failed = meeting_queue_failed(vault_path)
        logger.info("MeetingQueue: initialised on vault_path=%s", vault_path)

    # ------------------------------------------------------------------ #
    # Постановка в очередь — делегируется ядру (design §3.2)
    # ------------------------------------------------------------------ #
    def enqueue(self, **kwargs) -> Unit | None:
        """Тонкая обёртка над shared.meeting_queue.enqueue (vault_path подставляется)."""
        logger.info("enqueue: delegating to core (source=%s)", kwargs.get("source"))
        return enqueue(self.vault_path, **kwargs)

    # ------------------------------------------------------------------ #
    # Внутренние помощники
    # ------------------------------------------------------------------ #
    def _load_meta(self, meta_path: Path) -> dict:
        """Прочитать meta.json. Бросает json.JSONDecodeError при повреждении."""
        return json.loads(meta_path.read_text(encoding="utf-8"))

    def _move_corrupt_to_failed(self, unit_id: str, src_dir: Path) -> None:
        """Повреждённый/потерянный meta → перенести юнит в failed/ (design §5).

        `.txt` сохраняется (не теряется). meta пересоздаётся минимальной с
        last_error='corrupt meta'. Не бросает — изоляция сбоя прохода.
        """
        src_txt = src_dir / f"{unit_id}.txt"
        src_meta = src_dir / f"{unit_id}.meta.json"
        dst_txt = self._failed / f"{unit_id}.txt"
        dst_meta = self._failed / f"{unit_id}.meta.json"
        minimal = {
            "unit_id": unit_id,
            "status": "failed",
            "attempts": 0,
            "last_error": "corrupt meta",
            "updated_at": _now_iso(),
        }
        try:
            if src_txt.exists():
                os.rename(src_txt, dst_txt)
            atomic_write(dst_meta, _dump_meta(minimal))
            if src_meta.exists():
                try:
                    src_meta.unlink()
                except OSError as exc:
                    logger.warning(
                        "_move_corrupt_to_failed: could not unlink %s: %s", src_meta, exc
                    )
            logger.error(
                "_move_corrupt_to_failed: unit_id=%s moved to failed/ (corrupt meta)",
                unit_id,
            )
        except Exception as exc:  # noqa: BLE001 — изоляция: не ронять проход
            logger.error(
                "_move_corrupt_to_failed: failed to quarantine unit_id=%s: %s",
                unit_id,
                exc,
            )

    def _relocate(self, unit: Unit, dst_dir: Path, meta_updates: dict) -> None:
        """Переместить юнит (.txt + .meta.json) из текущей папки в dst_dir.

        Применяет meta_updates к unit.meta, всегда обновляет updated_at, пишет meta
        в целевую папку через atomic_write. `.txt` переносится через os.rename.
        Обновляет unit.txt_path / unit.meta_path / unit.meta in-place.
        """
        unit_id = unit.unit_id
        src_txt = unit.txt_path
        src_meta = unit.meta_path
        dst_txt = dst_dir / f"{unit_id}.txt"
        dst_meta = dst_dir / f"{unit_id}.meta.json"

        unit.meta.update(meta_updates)
        unit.meta["updated_at"] = _now_iso()

        # Сначала переносим .txt (замок/носитель), затем пишем meta в целевую папку.
        if src_txt.exists():
            os.rename(src_txt, dst_txt)
        else:
            logger.warning(
                "_relocate: source .txt missing for unit_id=%s (src=%s)", unit_id, src_txt
            )
        atomic_write(dst_meta, _dump_meta(unit.meta))
        if src_meta.exists() and src_meta != dst_meta:
            try:
                src_meta.unlink()
            except OSError as exc:
                logger.warning("_relocate: could not unlink old meta %s: %s", src_meta, exc)

        unit.txt_path = dst_txt
        unit.meta_path = dst_meta

    # ------------------------------------------------------------------ #
    # claim / claim_next
    # ------------------------------------------------------------------ #
    def claim(self, unit_id: str) -> Unit | None:
        """Атомарно захватить конкретный юнит: rename .txt pending→processing.

        Возвращает Unit при успехе. None, если проиграл гонку / юнита нет
        (FileNotFoundError) или meta повреждён (юнит уходит в failed/).
        """
        logger.info("claim: attempting claim unit_id=%s", unit_id)
        pending_txt = self._pending / f"{unit_id}.txt"
        processing_txt = self._processing / f"{unit_id}.txt"
        pending_meta = self._pending / f"{unit_id}.meta.json"
        processing_meta = self._processing / f"{unit_id}.meta.json"

        # Атомарный замок: os.rename бросает на Windows и POSIX, если source исчез.
        try:
            os.rename(pending_txt, processing_txt)
        except FileNotFoundError:
            logger.info("claim: lost race / absent unit_id=%s (no pending .txt)", unit_id)
            return None
        except OSError as exc:
            logger.error("claim: os.rename failed for unit_id=%s: %s", unit_id, exc)
            return None

        # Замок взят — переносим meta следом (best-effort).
        if pending_meta.exists():
            try:
                os.rename(pending_meta, processing_meta)
            except OSError as exc:
                logger.warning("claim: could not move meta for unit_id=%s: %s", unit_id, exc)

        # Читаем meta; повреждение/отсутствие → карантин в failed/.
        try:
            meta = self._load_meta(processing_meta)
        except FileNotFoundError:
            logger.error("claim: meta lost for unit_id=%s → failed/", unit_id)
            self._move_corrupt_to_failed(unit_id, self._processing)
            return None
        except json.JSONDecodeError:
            logger.error("claim: corrupt meta for unit_id=%s → failed/", unit_id)
            self._move_corrupt_to_failed(unit_id, self._processing)
            return None

        meta["status"] = "processing"
        meta["updated_at"] = _now_iso()
        atomic_write(processing_meta, _dump_meta(meta))

        logger.info("claim: won unit_id=%s (now processing/)", unit_id)
        return Unit(
            unit_id=unit_id,
            txt_path=processing_txt,
            meta_path=processing_meta,
            meta=meta,
        )

    def claim_next(self) -> Unit | None:
        """FIFO: первый доступный юнит из pending/ (sorted по имени = по времени)."""
        logger.info("claim_next: scanning pending/")
        try:
            txts = sorted(self._pending.glob("*.txt"))
        except OSError as exc:
            logger.error("claim_next: failed to list pending/: %s", exc)
            return None

        for txt in txts:
            unit_id = txt.name[: -len(".txt")]
            unit = self.claim(unit_id)
            if unit is not None:
                logger.info("claim_next: claimed unit_id=%s", unit_id)
                return unit

        logger.info("claim_next: nothing to claim (pending empty or all taken)")
        return None

    # ------------------------------------------------------------------ #
    # complete / fail / requeue
    # ------------------------------------------------------------------ #
    def complete(
        self,
        unit: Unit,
        *,
        output_file: str,
        protocol_type: str,
        provider_record: dict,
    ) -> None:
        """Успешное завершение: status=done, проставить результат, move →done."""
        unit_id = unit.unit_id
        logger.info("complete: finalising unit_id=%s → done/", unit_id)
        try:
            history = unit.meta.setdefault("provider_history", [])
            history.append(provider_record)
            self._relocate(
                unit,
                self._done,
                {
                    "status": "done",
                    "output_file": output_file,
                    "protocol_type": protocol_type,
                },
            )
            logger.info(
                "complete: unit_id=%s done (output_file=%s, protocol_type=%s)",
                unit_id,
                output_file,
                protocol_type,
            )
        except Exception as exc:
            logger.error("complete: failed for unit_id=%s: %s", unit_id, exc)
            raise

    def fail(self, unit: Unit, *, error: str, provider_record: dict) -> str:
        """Неудачная попытка: attempts++, last_error, провайдер в историю.

        attempts < max_attempts ⇒ requeue() (→pending), вернуть 'requeued'.
        Иначе status=failed, move →failed, вернуть 'failed'.
        """
        unit_id = unit.unit_id
        logger.info("fail: registering failure for unit_id=%s (error=%r)", unit_id, error)
        try:
            unit.meta["attempts"] = unit.meta.get("attempts", 0) + 1
            unit.meta["last_error"] = error
            history = unit.meta.setdefault("provider_history", [])
            history.append(provider_record)

            attempts = unit.meta["attempts"]
            max_attempts = unit.meta.get("max_attempts", 5)

            if attempts < max_attempts:
                self.requeue(unit)
                logger.info(
                    "fail: unit_id=%s requeued (attempts=%d/%d)",
                    unit_id,
                    attempts,
                    max_attempts,
                )
                return "requeued"

            self._relocate(unit, self._failed, {"status": "failed"})
            logger.error(
                "fail: unit_id=%s exhausted retries → failed/ (attempts=%d/%d)",
                unit_id,
                attempts,
                max_attempts,
            )
            return "failed"
        except Exception as exc:
            logger.error("fail: error handling failure for unit_id=%s: %s", unit_id, exc)
            raise

    def requeue(self, unit: Unit) -> None:
        """Вернуть юнит в pending/ для повторной обработки (status=pending)."""
        unit_id = unit.unit_id
        logger.info("requeue: returning unit_id=%s → pending/", unit_id)
        try:
            self._relocate(unit, self._pending, {"status": "pending"})
            logger.info("requeue: unit_id=%s back in pending/", unit_id)
        except Exception as exc:
            logger.error("requeue: failed for unit_id=%s: %s", unit_id, exc)
            raise

    # ------------------------------------------------------------------ #
    # reclaim_stuck
    # ------------------------------------------------------------------ #
    def reclaim_stuck(self, stuck_threshold_s: int) -> list[str]:
        """Подмести застрявшие в processing/ юниты (краш воркера, design §5, AC-08).

        Для юнитов с updated_at старше порога: attempts++ (списывается как неудачная
        попытка из-за падения), затем requeue() либо →failed при исчерпании max_attempts.
        Повреждённый meta → карантин в failed/. Возвращает список затронутых unit_id.
        """
        logger.info("reclaim_stuck: scanning processing/ (threshold=%ds)", stuck_threshold_s)
        affected: list[str] = []
        now = datetime.now().astimezone()

        try:
            txts = sorted(self._processing.glob("*.txt"))
        except OSError as exc:
            logger.error("reclaim_stuck: failed to list processing/: %s", exc)
            return affected

        for txt in txts:
            unit_id = txt.name[: -len(".txt")]
            meta_path = self._processing / f"{unit_id}.meta.json"

            try:
                meta = self._load_meta(meta_path)
            except (FileNotFoundError, json.JSONDecodeError) as exc:
                logger.error(
                    "reclaim_stuck: bad meta for unit_id=%s (%s) → failed/", unit_id, exc
                )
                self._move_corrupt_to_failed(unit_id, self._processing)
                affected.append(unit_id)
                continue

            updated_raw = meta.get("updated_at")
            try:
                updated = datetime.fromisoformat(updated_raw) if updated_raw else None
            except (TypeError, ValueError):
                updated = None

            if updated is not None and updated.tzinfo is None:
                updated = updated.astimezone()

            # Нет валидного updated_at → считаем застрявшим (безопаснее подмести).
            age_s = (now - updated).total_seconds() if updated is not None else float("inf")
            if age_s <= stuck_threshold_s:
                logger.debug(
                    "reclaim_stuck: unit_id=%s fresh (age=%.0fs) — skip", unit_id, age_s
                )
                continue

            unit = Unit(
                unit_id=unit_id,
                txt_path=txt,
                meta_path=meta_path,
                meta=meta,
            )
            meta["attempts"] = meta.get("attempts", 0) + 1
            meta["last_error"] = "reclaimed: stuck in processing"
            attempts = meta["attempts"]
            max_attempts = meta.get("max_attempts", 5)

            if attempts < max_attempts:
                self.requeue(unit)
                logger.info(
                    "reclaim_stuck: unit_id=%s requeued (age=%.0fs, attempts=%d/%d)",
                    unit_id,
                    age_s,
                    attempts,
                    max_attempts,
                )
            else:
                self._relocate(unit, self._failed, {"status": "failed"})
                logger.error(
                    "reclaim_stuck: unit_id=%s → failed/ (age=%.0fs, attempts=%d/%d)",
                    unit_id,
                    age_s,
                    attempts,
                    max_attempts,
                )
            affected.append(unit_id)

        logger.info("reclaim_stuck: reclaimed %d unit(s): %s", len(affected), affected)
        return affected

    # ------------------------------------------------------------------ #
    # status_counts
    # ------------------------------------------------------------------ #
    def status_counts(self) -> dict:
        """Счётчики по *.txt в каждой папке: {pending,processing,done,failed}."""
        logger.info("status_counts: counting units per folder")
        counts = {
            "pending": sum(1 for _ in self._pending.glob("*.txt")),
            "processing": sum(1 for _ in self._processing.glob("*.txt")),
            "done": sum(1 for _ in self._done.glob("*.txt")),
            "failed": sum(1 for _ in self._failed.glob("*.txt")),
        }
        logger.info("status_counts: %s", counts)
        return counts
