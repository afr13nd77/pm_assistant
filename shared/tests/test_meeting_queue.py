"""Tests for shared.meeting_queue (BL-145 enqueue-ядро, T-01).

Покрывает: AC-01 (пара .txt+.meta.json в pending/), AC-03 (status/attempts в meta),
AC-07 (idempotent дедуп), детерминизм/формат unit_id, отклонение пустого raw_text.
"""

import json
import re
from datetime import datetime

import pytest

from shared import meeting_queue
from shared.meeting_queue import (
    META_SCHEMA_VERSION,
    Unit,
    build_meta,
    enqueue,
    make_unit_id,
    meeting_queue_failed,
    meeting_queue_pending,
    meeting_queue_root,
)


@pytest.fixture
def date():
    return datetime(2026, 6, 30, 14, 15, 0)


# --------------------------------------------------------------------------- #
# Хелперы путей
# --------------------------------------------------------------------------- #
class TestQueuePaths:
    def test_root_under_raw_meeting_queue(self, tmp_path):
        root = meeting_queue_root(tmp_path)
        assert root == tmp_path / "raw" / "meeting-queue"
        assert root.is_dir()

    def test_status_dirs_created(self, tmp_path):
        for fn in (meeting_queue_pending, meeting_queue_failed):
            p = fn(tmp_path)
            assert p.is_dir()
            assert p.parent == tmp_path / "raw" / "meeting-queue"


# --------------------------------------------------------------------------- #
# make_unit_id
# --------------------------------------------------------------------------- #
class TestMakeUnitId:
    def test_format(self, date):
        uid = make_unit_id(
            source="email", date=date, message_id="<m@x>", content_sha="sha256:ab"
        )
        # <YYYYMMDD-HHMMSS>-<source>-<10 hex>
        assert re.fullmatch(r"20260630-141500-email-[0-9a-f]{10}", uid)

    def test_deterministic_same_dedup_key(self, date):
        a = make_unit_id(
            source="email", date=date, message_id="<m@x>", content_sha="sha256:ab"
        )
        b = make_unit_id(
            source="email", date=date, message_id="<m@x>", content_sha="sha256:ab"
        )
        assert a == b

    def test_local_dedup_key_uses_filename_and_sha(self, date):
        a = make_unit_id(
            source="local", date=date, source_filename="a.txt", content_sha="sha256:ab"
        )
        b = make_unit_id(
            source="local", date=date, source_filename="a.txt", content_sha="sha256:ab"
        )
        c = make_unit_id(
            source="local", date=date, source_filename="b.txt", content_sha="sha256:ab"
        )
        assert a == b
        assert a != c  # разный filename → разный хеш

    def test_source_in_id(self, date):
        uid = make_unit_id(
            source="local", date=date, source_filename="a.txt", content_sha="sha256:x"
        )
        assert "-local-" in uid


# --------------------------------------------------------------------------- #
# build_meta
# --------------------------------------------------------------------------- #
class TestBuildMeta:
    def test_schema_fields(self, date):
        meta = build_meta(
            unit_id="uid1",
            source="email",
            subject="Sync",
            date=date,
            message_id="<m@x>",
            content_sha="sha256:ab",
            max_attempts=5,
        )
        assert meta["unit_id"] == "uid1"
        assert meta["schema_version"] == META_SCHEMA_VERSION
        assert meta["status"] == "pending"
        assert meta["attempts"] == 0
        assert meta["max_attempts"] == 5
        assert meta["last_error"] is None
        assert meta["provider_history"] == []
        assert meta["output_file"] is None
        assert meta["protocol_type"] is None
        assert meta["date"] == date.isoformat()
        assert meta["created_at"] == meta["updated_at"]
        # все обязательные ключи схемы §2.4 присутствуют
        for key in ("source", "message_id", "source_filename", "subject",
                    "content_sha", "created_at", "updated_at"):
            assert key in meta


# --------------------------------------------------------------------------- #
# enqueue
# --------------------------------------------------------------------------- #
class TestEnqueue:
    def test_creates_pair_in_pending(self, tmp_path, date):
        unit = enqueue(
            tmp_path,
            raw_text="тестовый транскрипт",
            source="local",
            subject="t",
            date=date,
            source_filename="a.txt",
        )
        assert isinstance(unit, Unit)
        pending = meeting_queue_pending(tmp_path)
        files = sorted(p.name for p in pending.iterdir())
        assert files == [f"{unit.unit_id}.meta.json", f"{unit.unit_id}.txt"]
        assert unit.txt_path.read_text(encoding="utf-8") == "тестовый транскрипт"

    def test_meta_status_pending_attempts_zero(self, tmp_path, date):
        unit = enqueue(
            tmp_path,
            raw_text="контент",
            source="email",
            subject="s",
            date=date,
            message_id="<m@x>",
        )
        on_disk = json.loads(unit.meta_path.read_text(encoding="utf-8"))
        assert on_disk["status"] == "pending"
        assert on_disk["attempts"] == 0
        assert on_disk["source"] == "email"
        assert on_disk["content_sha"].startswith("sha256:")
        # max_attempts взят из settings.get('queue.max_attempts', 5)
        assert on_disk["max_attempts"] == 5

    def test_meta_written_before_txt(self, tmp_path, date, monkeypatch):
        """Порядок записи: .meta.json раньше .txt (design §4.4)."""
        order = []
        real_atomic = meeting_queue.atomic_write

        def spy(filepath, content):
            order.append(str(filepath).rsplit(".", 1)[-1])
            return real_atomic(filepath, content)

        monkeypatch.setattr(meeting_queue, "atomic_write", spy)
        enqueue(
            tmp_path,
            raw_text="x" * 10,
            source="local",
            subject="t",
            date=date,
            source_filename="a.txt",
        )
        # .meta.json пишется как ...meta.json → суффикс 'json'; затем 'txt'
        assert order == ["json", "txt"]

    def test_idempotent_no_duplicate(self, tmp_path, date):
        first = enqueue(
            tmp_path,
            raw_text="один и тот же",
            source="local",
            subject="t",
            date=date,
            source_filename="a.txt",
        )
        second = enqueue(
            tmp_path,
            raw_text="один и тот же",
            source="local",
            subject="t",
            date=date,
            source_filename="a.txt",
        )
        assert first.unit_id == second.unit_id
        pending = meeting_queue_pending(tmp_path)
        # ровно одна пара файлов
        assert len(list(pending.iterdir())) == 2

    def test_idempotent_does_not_overwrite(self, tmp_path, date):
        enqueue(
            tmp_path,
            raw_text="original",
            source="local",
            subject="t",
            date=date,
            source_filename="a.txt",
        )
        # повторный enqueue с тем же dedup_key (filename+sha) → тот же id, не перезапишет
        unit = enqueue(
            tmp_path,
            raw_text="original",
            source="local",
            subject="t",
            date=date,
            source_filename="a.txt",
        )
        assert unit.txt_path.read_text(encoding="utf-8") == "original"

    def test_empty_raw_text_returns_none(self, tmp_path, date):
        unit = enqueue(
            tmp_path,
            raw_text="   \n\t  ",
            source="local",
            subject="t",
            date=date,
            source_filename="a.txt",
        )
        assert unit is None
        pending = meeting_queue_pending(tmp_path)
        assert list(pending.iterdir()) == []

    def test_explicit_max_attempts(self, tmp_path, date):
        unit = enqueue(
            tmp_path,
            raw_text="content",
            source="local",
            subject="t",
            date=date,
            source_filename="a.txt",
            max_attempts=9,
        )
        assert unit.meta["max_attempts"] == 9
