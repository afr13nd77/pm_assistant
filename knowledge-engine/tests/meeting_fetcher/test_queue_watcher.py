"""Tests for meeting_fetcher.queue_watcher (T-09, US-02 near-realtime).

Покрывают логику PendingHandler.on_created без реального Observer-потока:
синтетический event (src_path + is_directory), MeetingQueue.claim и
processor.process_one замоканы. Проверяется:
  - .meta.json и директории игнорируются (claim не вызывается);
  - для .txt вызывается claim(unit_id), при успехе — process_one(...);
  - при claim → None process_one НЕ вызывается;
  - исключение в process_one не пробрасывается (Observer не падает).
"""

from types import SimpleNamespace
from unittest import mock

from watchdog.observers.polling import PollingObserver

from app.meeting_fetcher.queue_watcher import PendingHandler, start_queue_watch


def _event(src_path: str, is_directory: bool = False) -> SimpleNamespace:
    """Синтетический watchdog-подобный event с нужными атрибутами."""
    return SimpleNamespace(src_path=src_path, is_directory=is_directory)


def _moved_event(dest_path: str, is_directory: bool = False) -> SimpleNamespace:
    """Синтетический moved-event (atomic_write делает temp→rename → on_moved)."""
    return SimpleNamespace(
        src_path=dest_path + ".tmp", dest_path=dest_path, is_directory=is_directory
    )


def test_ignores_meta_json(tmp_path):
    """`.meta.json` (suffix .json) не триггерит claim/process."""
    handler = PendingHandler(str(tmp_path))
    meta = tmp_path / "raw" / "meeting-queue" / "pending" / "u1.meta.json"

    with mock.patch(
        "app.meeting_fetcher.queue_watcher.MeetingQueue"
    ) as mq, mock.patch(
        "app.meeting_fetcher.queue_watcher.processor.process_one"
    ) as proc:
        handler.on_created(_event(str(meta)))

    mq.assert_not_called()
    proc.assert_not_called()


def test_ignores_directory(tmp_path):
    """Событие директории игнорируется."""
    handler = PendingHandler(str(tmp_path))
    some_dir = tmp_path / "raw" / "meeting-queue" / "pending" / "subdir"

    with mock.patch(
        "app.meeting_fetcher.queue_watcher.MeetingQueue"
    ) as mq, mock.patch(
        "app.meeting_fetcher.queue_watcher.processor.process_one"
    ) as proc:
        handler.on_created(_event(str(some_dir), is_directory=True))

    mq.assert_not_called()
    proc.assert_not_called()


def test_txt_claims_and_processes(tmp_path):
    """Для `.txt` вызывается claim(unit_id); выигранный claim → process_one(...)."""
    handler = PendingHandler(str(tmp_path), notify=True)
    unit_id = "20260630-120000-local-abc1234567"
    txt = tmp_path / "raw" / "meeting-queue" / "pending" / f"{unit_id}.txt"

    fake_unit = object()
    instance = mock.Mock()
    instance.claim.return_value = fake_unit

    with mock.patch(
        "app.meeting_fetcher.queue_watcher.MeetingQueue", return_value=instance
    ), mock.patch(
        "app.meeting_fetcher.queue_watcher.processor.process_one",
        return_value={"unit_id": unit_id, "result": "done"},
    ) as proc:
        handler.on_created(_event(str(txt)))

    instance.claim.assert_called_once_with(unit_id)
    proc.assert_called_once_with(str(tmp_path), fake_unit, True)


def test_moved_txt_claims_and_processes(tmp_path):
    """on_moved с dest_path=`.txt` (atomic temp→rename) тоже триггерит claim+process."""
    handler = PendingHandler(str(tmp_path))
    unit_id = "20260630-130000-local-1234567890"
    txt = tmp_path / "raw" / "meeting-queue" / "pending" / f"{unit_id}.txt"

    fake_unit = object()
    instance = mock.Mock()
    instance.claim.return_value = fake_unit

    with mock.patch(
        "app.meeting_fetcher.queue_watcher.MeetingQueue", return_value=instance
    ), mock.patch(
        "app.meeting_fetcher.queue_watcher.processor.process_one",
        return_value={"unit_id": unit_id, "result": "done"},
    ) as proc:
        handler.on_moved(_moved_event(str(txt)))

    instance.claim.assert_called_once_with(unit_id)
    proc.assert_called_once_with(str(tmp_path), fake_unit, False)


def test_lost_claim_skips_process(tmp_path):
    """claim → None (проигранная гонка) → process_one НЕ вызывается."""
    handler = PendingHandler(str(tmp_path))
    unit_id = "20260630-120000-email-deadbeef99"
    txt = tmp_path / "raw" / "meeting-queue" / "pending" / f"{unit_id}.txt"

    instance = mock.Mock()
    instance.claim.return_value = None

    with mock.patch(
        "app.meeting_fetcher.queue_watcher.MeetingQueue", return_value=instance
    ), mock.patch(
        "app.meeting_fetcher.queue_watcher.processor.process_one"
    ) as proc:
        handler.on_created(_event(str(txt)))

    instance.claim.assert_called_once_with(unit_id)
    proc.assert_not_called()


def test_process_exception_not_propagated(tmp_path):
    """Исключение в process_one изолируется — on_created не бросает."""
    handler = PendingHandler(str(tmp_path))
    unit_id = "20260630-120000-local-feedface00"
    txt = tmp_path / "raw" / "meeting-queue" / "pending" / f"{unit_id}.txt"

    instance = mock.Mock()
    instance.claim.return_value = object()

    with mock.patch(
        "app.meeting_fetcher.queue_watcher.MeetingQueue", return_value=instance
    ), mock.patch(
        "app.meeting_fetcher.queue_watcher.processor.process_one",
        side_effect=RuntimeError("LLM boom"),
    ):
        # Не должно пробросить исключение.
        handler.on_created(_event(str(txt)))

    instance.claim.assert_called_once_with(unit_id)


def test_start_queue_watch_returns_polling_observer(tmp_path):
    """start_queue_watch возвращает инстанс PollingObserver.

    PollingObserver критичен для bind-mount Windows→Linux: нативный inotify-Observer
    не получает события на смонтированной ФС (BL-145 E2E). Мокаем schedule/start,
    чтобы не поднимать реальный поллинг-поток в юнит-тесте.
    """
    with mock.patch.object(PollingObserver, "schedule") as schedule, mock.patch.object(
        PollingObserver, "start"
    ) as start:
        observer = start_queue_watch(str(tmp_path))

    assert isinstance(observer, PollingObserver)
    schedule.assert_called_once()
    start.assert_called_once()
