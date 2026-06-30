"""Tests for meeting_fetcher.processor.

T-06 (US-05, AC-06): validate_protocol — чистый валидатор.
T-07 (US-02/04/05, AC-02/04/05/06): process_one / process_pending — Process-воркер.
"""

from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from unittest import mock

import pytest

from app.meeting_fetcher.processor import (
    MIN_PROTOCOL_LEN,
    REQUIRED_FM,
    process_one,
    process_pending,
    validate_protocol,
)
from app.meeting_fetcher.queue import MeetingQueue
from shared.meeting_queue import (
    enqueue,
    meeting_queue_done,
    meeting_queue_failed,
    meeting_queue_pending,
)


def _valid_protocol() -> str:
    """Полноценный валидный протокол по схеме промпта meeting_protocol.txt:

    frontmatter (tags/date/type/participants/source/status) + H1 '# Название' +
    '## ' секции + длина > 200. Поля 'title' во frontmatter НЕТ — название это H1.
    """
    return (
        "---\n"
        "tags: [meeting, протокол]\n"
        "date: 2026-06-30\n"
        "type: sync\n"
        "participants: [Иван, Пётр]\n"
        "source: telemost-transcript\n"
        "status: inbox\n"
        "---\n\n"
        "# Sync команды\n\n"
        "## Решения\n"
        "- Договорились о сроках релиза.\n\n"
        "## Action items\n"
        "- Иван готовит дизайн до пятницы.\n"
        + "Дополнительный контекст обсуждения. " * 10
    )


class TestValidateProtocol:
    def test_constants(self):
        assert MIN_PROTOCOL_LEN == 200
        assert REQUIRED_FM == ("type", "date")

    def test_too_short(self):
        ok, reason = validate_protocol("коротко")
        assert ok is False
        assert "short" in reason

    def test_no_frontmatter(self):
        # Длинный текст без frontmatter.
        md = "Просто длинный текст без метаданных. " * 10
        assert len(md) >= MIN_PROTOCOL_LEN
        ok, reason = validate_protocol(md)
        assert ok is False
        assert "frontmatter" in reason

    def test_missing_required_field_type(self):
        # Нет 'type' во frontmatter (есть только date) → invalid.
        md = (
            "---\n"
            "date: 2026-06-30\n"
            "---\n\n"
            "# Название\n\n"
            "## Решения\n" + "x" * 250
        )
        ok, reason = validate_protocol(md)
        assert ok is False
        assert "type" in reason

    def test_missing_required_field_date(self):
        # Нет 'date' во frontmatter (есть только type) → invalid.
        md = (
            "---\n"
            "type: sync\n"
            "---\n\n"
            "# Название\n\n"
            "## Решения\n" + "x" * 250
        )
        ok, reason = validate_protocol(md)
        assert ok is False
        assert "date" in reason

    def test_empty_required_field(self):
        md = (
            "---\n"
            "type: ''\n"
            "date: 2026-06-30\n"
            "---\n\n"
            "# Название\n\n"
            "## Решения\n" + "x" * 250
        )
        ok, reason = validate_protocol(md)
        assert ok is False
        assert "type" in reason

    def test_missing_h1_title_heading(self):
        # Frontmatter валиден, '## ' секция есть, но H1 '# ' отсутствует → invalid.
        md = (
            "---\n"
            "type: sync\n"
            "date: 2026-06-30\n"
            "---\n\n"
            "## Решения\n"
            "- Договорились о сроках.\n" + "x" * 250
        )
        assert len(md) >= MIN_PROTOCOL_LEN
        ok, reason = validate_protocol(md)
        assert ok is False
        assert reason == "missing H1 title heading"

    def test_body_without_section_heading(self):
        # H1 есть, но нет ни одного '## ' подзаголовка → invalid.
        md = (
            "---\n"
            "type: sync\n"
            "date: 2026-06-30\n"
            "---\n\n"
            "# Sync\n\n"
            "Просто текст без markdown-заголовка второго уровня. " * 6
        )
        assert len(md) >= MIN_PROTOCOL_LEN
        ok, reason = validate_protocol(md)
        assert ok is False
        assert "##" in reason or "heading" in reason

    def test_valid_protocol(self):
        ok, reason = validate_protocol(_valid_protocol())
        assert ok is True
        assert reason == ""

    def test_garbage_input_does_not_raise(self):
        # Мусорный/некорректный ввод не роняет функцию.
        for bad in [
            None,
            123,
            b"bytes",
            "---\nnot: [valid: yaml\n---\nbody",
            "---\n" * 50,
            "\x00\x01\x02 binary-ish " * 30,
        ]:
            ok, reason = validate_protocol(bad)  # type: ignore[arg-type]
            assert ok is False
            assert isinstance(reason, str)


# --------------------------------------------------------------------------- #
# T-07 — process_one / process_pending
# --------------------------------------------------------------------------- #
_OK_RECORD = {"providers": ["claude"], "used": "claude", "errors": []}


@contextmanager
def _patch_nonfatal():
    """Замокать тяжёлые non-fatal шаги (enrich / jira / LOG.md) как no-op."""
    with mock.patch(
        "app.enricher.enrich", return_value={"status": "skip", "links_found": 0}
    ), mock.patch(
        "app.jira_key_sync.sync_jira_keys",
        return_value={"keys": [], "keys_map": {}, "imported": [], "missing": [], "failed": []},
    ), mock.patch(
        "app.jira_key_sync.patch_jira_links", return_value=None
    ), mock.patch(
        "app.ingest._append_root_log", return_value=None
    ):
        yield


def _valid_md() -> str:
    return _valid_protocol()


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    return tmp_path / "vault"


def _enqueue_and_claim(vault: Path, *, subject="Sync команды", text=None,
                       filename="a.txt", max_attempts=5):
    """Поставить локальный юнит и сразу заклеймить (он попадает в processing/)."""
    enqueue(
        str(vault),
        raw_text=text or ("Транскрипт обсуждения релиза. " * 20),
        source="local",
        subject=subject,
        date=datetime.now(),
        source_filename=filename,
        max_attempts=max_attempts,
    )
    q = MeetingQueue(str(vault))
    unit = q.claim_next()
    assert unit is not None
    return unit


class TestProcessOne:
    def test_happy_path_writes_protocol_and_completes(self, vault: Path):
        unit = _enqueue_and_claim(vault)
        with _patch_nonfatal(), mock.patch(
            "app.meeting_fetcher.processor.call_detailed",
            return_value=(_valid_md(), _OK_RECORD),
        ):
            res = process_one(str(vault), unit)

        assert res["result"] == "done"
        # Юнит переехал в done/ (постоянный сырой архив).
        assert (meeting_queue_done(vault) / f"{unit.unit_id}.txt").exists()
        assert not (meeting_queue_pending(vault) / f"{unit.unit_id}.txt").exists()
        # Протокол записан в wiki (type=sync → wiki/meetings).
        wiki_dir = vault / "wiki" / "meetings"
        md_files = list(wiki_dir.glob("*.md"))
        assert len(md_files) == 1
        assert res["output_file"].startswith("wiki/meetings/")
        # provider_record зафиксирован в provider_history (AC-04).
        import json
        meta = json.loads(
            (meeting_queue_done(vault) / f"{unit.unit_id}.meta.json").read_text("utf-8")
        )
        assert meta["status"] == "done"
        assert len(meta["provider_history"]) == 1
        assert meta["provider_history"][0]["used"] == "claude"

    def test_provider_fallback_recorded(self, vault: Path):
        # AC-04: первый провайдер упал, второй ок — provider_record отражает перебор.
        unit = _enqueue_and_claim(vault)
        record = {
            "providers": ["claude", "ollama"],
            "used": "ollama",
            "errors": [("claude", "timeout")],
        }
        with _patch_nonfatal(), mock.patch(
            "app.meeting_fetcher.processor.call_detailed",
            return_value=(_valid_md(), record),
        ):
            res = process_one(str(vault), unit)

        assert res["result"] == "done"
        assert (meeting_queue_done(vault) / f"{unit.unit_id}.txt").exists()
        import json
        meta = json.loads(
            (meeting_queue_done(vault) / f"{unit.unit_id}.meta.json").read_text("utf-8")
        )
        ph = meta["provider_history"][0]
        assert ph["used"] == "ollama"
        assert ph["providers"] == ["claude", "ollama"]
        assert len(ph["errors"]) == 1  # испробовано >1 провайдера

    def test_invalid_llm_response_no_wiki_write(self, vault: Path):
        # AC-06: невалидный ответ НЕ пишется в wiki, юнит уходит в fail.
        unit = _enqueue_and_claim(vault, max_attempts=1)  # 1 попытка → сразу failed
        with _patch_nonfatal(), mock.patch(
            "app.meeting_fetcher.processor.call_detailed",
            return_value=("короткий мусор", _OK_RECORD),
        ):
            res = process_one(str(vault), unit)

        assert res["result"] == "failed"
        assert "error" in res
        # В wiki ничего не записано.
        assert not (vault / "wiki" / "meetings").exists() or \
            list((vault / "wiki" / "meetings").glob("*.md")) == []
        # Юнит в failed/, сырьё на месте.
        assert (meeting_queue_failed(vault) / f"{unit.unit_id}.txt").exists()

    def test_llm_exception_requeues_with_empty_record(self, vault: Path):
        # Полный отказ LLM-цепочки → fail; при max_attempts>1 → requeued.
        unit = _enqueue_and_claim(vault, max_attempts=5)
        with _patch_nonfatal(), mock.patch(
            "app.meeting_fetcher.processor.call_detailed",
            side_effect=RuntimeError("all providers failed"),
        ):
            res = process_one(str(vault), unit)

        assert res["result"] == "requeued"
        # Вернулся в pending/ для повторной попытки.
        assert (meeting_queue_pending(vault) / f"{unit.unit_id}.txt").exists()


class TestProcessPending:
    def test_all_providers_fail_eventually_failed(self, vault: Path):
        # AC-05: все провайдеры падают → после исчерпания max_attempts → failed/.
        enqueue(
            str(vault),
            raw_text="Транскрипт. " * 20,
            source="local",
            subject="Sync",
            date=datetime.now(),
            source_filename="x.txt",
            max_attempts=2,
        )
        with _patch_nonfatal(), mock.patch(
            "app.meeting_fetcher.processor.call_detailed",
            side_effect=RuntimeError("all providers failed"),
        ):
            summary = process_pending(str(vault))

        # Full-drain: requeued (попытка 1) → failed (попытка 2).
        assert summary["failed"] == 1
        assert summary["requeued"] == 1
        failed_txt = list(meeting_queue_failed(vault).glob("*.txt"))
        assert len(failed_txt) == 1  # .txt сохранён (AC-05)
        assert list(meeting_queue_pending(vault).glob("*.txt")) == []

    def test_one_failure_does_not_block_others(self, vault: Path):
        # AC-02: сбой одного юнита не мешает обработке остальных; reclaim_stuck вызван.
        for fn, text in [
            ("good1.txt", "Хороший транскрипт один. " * 20),
            ("bad.txt", "BADUNIT плохой транскрипт. " * 20),
            ("good2.txt", "Хороший транскрипт два. " * 20),
        ]:
            enqueue(
                str(vault),
                raw_text=text,
                source="local",
                subject="Sync",
                date=datetime.now(),
                source_filename=fn,
                max_attempts=1,  # плохой юнит сразу в failed/, без retry-петли
            )

        def fake_call(operation, messages, max_tokens, timeout=None, **kwargs):
            if "BADUNIT" in messages[0]["content"]:
                raise RuntimeError("all providers failed")
            return _valid_md(), _OK_RECORD

        with _patch_nonfatal(), mock.patch.object(
            MeetingQueue, "reclaim_stuck", return_value=[]
        ) as reclaim_spy, mock.patch(
            "app.meeting_fetcher.processor.call_detailed", side_effect=fake_call
        ):
            summary = process_pending(str(vault))

        reclaim_spy.assert_called_once()
        assert summary["processed"] == 2  # два хороших обработаны
        assert summary["failed"] == 1  # один упал, но не заблокировал
        assert len(list(meeting_queue_done(vault).glob("*.txt"))) == 2
        assert len(list(meeting_queue_failed(vault).glob("*.txt"))) == 1
        assert list(meeting_queue_pending(vault).glob("*.txt")) == []
