"""Тесты MeetingQueue — операции обработки очереди встреч (T-04, AC-02/05/08).

Юниты в pending/ готовятся через РЕАЛЬНОЕ ядро shared.meeting_queue.enqueue
(а не вручную) — чтобы тесты бились о фактический формат meta.json.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.meeting_fetcher.queue import MeetingQueue
from shared.meeting_queue import (
    enqueue,
    meeting_queue_done,
    meeting_queue_failed,
    meeting_queue_pending,
    meeting_queue_processing,
)


def _enqueue_unit(vault: Path, *, text: str = "Длинный транскрипт встречи. " * 10,
                  subject: str = "Sync", filename: str = "a.txt"):
    """Поставить локальный юнит в pending/ и вернуть его Unit."""
    unit = enqueue(
        str(vault),
        raw_text=text,
        source="local",
        subject=subject,
        date=datetime.now(),
        source_filename=filename,
        max_attempts=3,
    )
    assert unit is not None
    return unit


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    return tmp_path / "vault"


@pytest.fixture
def queue(vault: Path) -> MeetingQueue:
    return MeetingQueue(str(vault))


# --------------------------------------------------------------------------- #
# claim / claim_next
# --------------------------------------------------------------------------- #
def test_claim_next_moves_to_processing(vault: Path, queue: MeetingQueue):
    u = _enqueue_unit(vault)

    claimed = queue.claim_next()

    assert claimed is not None
    assert claimed.unit_id == u.unit_id
    # Файлы переехали в processing/, исчезли из pending/.
    assert (meeting_queue_processing(vault) / f"{u.unit_id}.txt").exists()
    assert (meeting_queue_processing(vault) / f"{u.unit_id}.meta.json").exists()
    assert not (meeting_queue_pending(vault) / f"{u.unit_id}.txt").exists()
    assert claimed.meta["status"] == "processing"


def test_claim_same_unit_twice_loses_race(vault: Path, queue: MeetingQueue):
    u = _enqueue_unit(vault)

    first = queue.claim(u.unit_id)
    second = queue.claim(u.unit_id)  # уже не в pending/ — гонка проиграна

    assert first is not None
    assert second is None


def test_claim_next_empty_returns_none(queue: MeetingQueue):
    assert queue.claim_next() is None


def test_claim_next_fifo_order(vault: Path, queue: MeetingQueue):
    # Два юнита с разными именами файлов → разные unit_id; имена сортируемы.
    u1 = _enqueue_unit(vault, filename="aaa.txt", text="первый транскрипт " * 10)
    u2 = _enqueue_unit(vault, filename="bbb.txt", text="второй транскрипт " * 10)
    ids_by_name = sorted([u1.unit_id, u2.unit_id])

    first = queue.claim_next()
    assert first is not None
    assert first.unit_id == ids_by_name[0]


# --------------------------------------------------------------------------- #
# complete
# --------------------------------------------------------------------------- #
def test_complete_moves_to_done(vault: Path, queue: MeetingQueue):
    _enqueue_unit(vault)
    unit = queue.claim_next()
    assert unit is not None

    queue.complete(
        unit,
        output_file="Meetings/2026-06-30-sync.md",
        protocol_type="sync",
        provider_record={"providers": ["claude"], "used": "claude", "errors": []},
    )

    done_meta = meeting_queue_done(vault) / f"{unit.unit_id}.meta.json"
    assert (meeting_queue_done(vault) / f"{unit.unit_id}.txt").exists()
    assert done_meta.exists()
    assert not (meeting_queue_processing(vault) / f"{unit.unit_id}.txt").exists()

    meta = json.loads(done_meta.read_text(encoding="utf-8"))
    assert meta["status"] == "done"
    assert meta["output_file"] == "Meetings/2026-06-30-sync.md"
    assert meta["protocol_type"] == "sync"
    assert len(meta["provider_history"]) == 1
    assert meta["provider_history"][0]["used"] == "claude"


# --------------------------------------------------------------------------- #
# fail → requeued → failed (AC-05)
# --------------------------------------------------------------------------- #
def test_fail_requeues_then_fails_after_max_attempts(vault: Path, queue: MeetingQueue):
    # max_attempts=3 (см. _enqueue_unit).
    _enqueue_unit(vault)
    pr = {"providers": ["claude"], "used": None, "errors": [("claude", "boom")]}

    # attempt 1 → requeued
    unit = queue.claim_next()
    assert queue.fail(unit, error="err1", provider_record=pr) == "requeued"
    assert (meeting_queue_pending(vault) / f"{unit.unit_id}.txt").exists()

    # attempt 2 → requeued
    unit = queue.claim_next()
    assert queue.fail(unit, error="err2", provider_record=pr) == "requeued"
    assert (meeting_queue_pending(vault) / f"{unit.unit_id}.txt").exists()

    # attempt 3 → failed (исчерпан max_attempts=3)
    unit = queue.claim_next()
    result = queue.fail(unit, error="err3", provider_record=pr)
    assert result == "failed"

    failed_txt = meeting_queue_failed(vault) / f"{unit.unit_id}.txt"
    failed_meta = meeting_queue_failed(vault) / f"{unit.unit_id}.meta.json"
    # .txt физически на месте (сырьё не теряется) — AC-05.
    assert failed_txt.exists()
    meta = json.loads(failed_meta.read_text(encoding="utf-8"))
    assert meta["status"] == "failed"
    assert meta["attempts"] == 3
    assert meta["last_error"] == "err3"
    assert len(meta["provider_history"]) == 3
    # Больше не в pending/processing.
    assert not (meeting_queue_pending(vault) / f"{unit.unit_id}.txt").exists()
    assert not (meeting_queue_processing(vault) / f"{unit.unit_id}.txt").exists()


# --------------------------------------------------------------------------- #
# reclaim_stuck (AC-08)
# --------------------------------------------------------------------------- #
def _backdate_updated_at(meta_path: Path, minutes: int):
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    old = datetime.now().astimezone() - timedelta(minutes=minutes)
    meta["updated_at"] = old.isoformat()
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def test_reclaim_stuck_requeues_old_unit(vault: Path, queue: MeetingQueue):
    _enqueue_unit(vault)
    unit = queue.claim_next()
    assert unit is not None
    # Состарить updated_at на 60 мин.
    _backdate_updated_at(unit.meta_path, minutes=60)

    affected = queue.reclaim_stuck(stuck_threshold_s=1800)  # 30 мин

    assert unit.unit_id in affected
    # attempts был 0 → requeue (max_attempts=3) → в pending/.
    assert (meeting_queue_pending(vault) / f"{unit.unit_id}.txt").exists()
    assert not (meeting_queue_processing(vault) / f"{unit.unit_id}.txt").exists()
    meta = json.loads(
        (meeting_queue_pending(vault) / f"{unit.unit_id}.meta.json").read_text(encoding="utf-8")
    )
    assert meta["status"] == "pending"
    assert meta["attempts"] == 1


def test_reclaim_stuck_fresh_unit_untouched(vault: Path, queue: MeetingQueue):
    _enqueue_unit(vault)
    unit = queue.claim_next()
    assert unit is not None

    affected = queue.reclaim_stuck(stuck_threshold_s=1800)

    assert affected == []
    assert (meeting_queue_processing(vault) / f"{unit.unit_id}.txt").exists()


def test_reclaim_stuck_fails_when_exhausted(vault: Path, queue: MeetingQueue):
    # Довести attempts до max-1=2, чтобы reclaim (+1) исчерпал лимит → failed/.
    _enqueue_unit(vault)
    pr = {"providers": [], "used": None, "errors": []}
    for _ in range(2):
        u = queue.claim_next()
        queue.fail(u, error="x", provider_record=pr)  # requeued дважды → attempts=2

    unit = queue.claim_next()
    _backdate_updated_at(unit.meta_path, minutes=60)

    affected = queue.reclaim_stuck(stuck_threshold_s=1800)

    assert unit.unit_id in affected
    assert (meeting_queue_failed(vault) / f"{unit.unit_id}.txt").exists()
    meta = json.loads(
        (meeting_queue_failed(vault) / f"{unit.unit_id}.meta.json").read_text(encoding="utf-8")
    )
    assert meta["status"] == "failed"
    assert meta["attempts"] == 3


# --------------------------------------------------------------------------- #
# status_counts
# --------------------------------------------------------------------------- #
def test_status_counts(vault: Path, queue: MeetingQueue):
    # 2 в pending, затем 1 заклеймить и завершить → 1 done, 1 pending.
    _enqueue_unit(vault, filename="aaa.txt", text="aaa транскрипт " * 10)
    _enqueue_unit(vault, filename="bbb.txt", text="bbb транскрипт " * 10)

    assert queue.status_counts() == {"pending": 2, "processing": 0, "done": 0, "failed": 0}

    unit = queue.claim_next()
    assert queue.status_counts()["processing"] == 1
    assert queue.status_counts()["pending"] == 1

    queue.complete(
        unit,
        output_file="Meetings/x.md",
        protocol_type="sync",
        provider_record={"providers": ["claude"], "used": "claude", "errors": []},
    )
    assert queue.status_counts() == {"pending": 1, "processing": 0, "done": 1, "failed": 0}


# --------------------------------------------------------------------------- #
# corrupt meta (design §5)
# --------------------------------------------------------------------------- #
def test_corrupt_meta_goes_to_failed_without_crashing(vault: Path, queue: MeetingQueue):
    u = _enqueue_unit(vault)
    # Повредить meta.json в pending/.
    (meeting_queue_pending(vault) / f"{u.unit_id}.meta.json").write_text(
        "{ это не валидный json ", encoding="utf-8"
    )

    # claim_next захватывает .txt (замок), читает битый meta → карантин в failed/.
    result = queue.claim_next()

    assert result is None  # юнит не отдан в обработку
    failed_txt = meeting_queue_failed(vault) / f"{u.unit_id}.txt"
    failed_meta = meeting_queue_failed(vault) / f"{u.unit_id}.meta.json"
    assert failed_txt.exists()  # сырьё сохранено
    meta = json.loads(failed_meta.read_text(encoding="utf-8"))
    assert meta["status"] == "failed"
    assert meta["last_error"] == "corrupt meta"
