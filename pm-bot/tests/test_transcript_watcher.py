"""Tests for the thin local transcript watcher (T-12, design §3.6).

The watcher must NOT call the LLM or write a protocol. It only enqueues the
raw .txt into the file-based meeting queue (source='local') and renames the
original to *.processed for local dedup.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app import transcript_watcher
from app.transcript_watcher import TranscriptHandler


@pytest.fixture
def inbox(tmp_path: Path) -> Path:
    d = tmp_path / "inbox"
    d.mkdir()
    return d


@pytest.mark.asyncio
async def test_process_enqueues_and_renames(inbox: Path):
    """.txt в inbox → вызывается enqueue(source='local') и файл → .processed."""
    txt = inbox / "telemost-2026.txt"
    txt.write_text("содержимое встречи", encoding="utf-8")

    fake_unit = MagicMock()
    fake_unit.unit_id = "20260630-141500-local-abc1234567"

    with patch.object(
        transcript_watcher.meeting_queue, "enqueue", return_value=fake_unit
    ) as mock_enqueue:
        handler = TranscriptHandler(bot=None, chat_id=0)
        await handler._process(txt)

    # enqueue вызван ровно один раз с source='local'
    mock_enqueue.assert_called_once()
    _args, kwargs = mock_enqueue.call_args
    assert kwargs["source"] == "local"
    assert kwargs["raw_text"] == "содержимое встречи"
    assert kwargs["subject"] == "telemost-2026"
    assert kwargs["source_filename"] == "telemost-2026.txt"
    assert kwargs["date"] is not None

    # Оригинал переименован в .processed, исходного .txt больше нет
    assert not txt.exists()
    assert (inbox / "telemost-2026.processed.txt").exists()


@pytest.mark.asyncio
async def test_process_does_not_call_llm_or_writer(inbox: Path):
    """Watcher не вызывает LLM-обработку и не пишет протокол."""
    txt = inbox / "note.txt"
    txt.write_text("текст", encoding="utf-8")

    with patch.object(
        transcript_watcher.meeting_queue, "enqueue", return_value=MagicMock()
    ):
        handler = TranscriptHandler(bot=None, chat_id=0)
        await handler._process(txt)

    # Модуль не должен импортировать локальную LLM-обработку / запись протокола.
    assert not hasattr(transcript_watcher, "process_meeting")
    assert not hasattr(transcript_watcher, "write_meeting")


@pytest.mark.asyncio
async def test_process_empty_file_renamed_no_unit(inbox: Path):
    """Пустой транскрипт: enqueue вернул None → файл всё равно помечен .processed."""
    txt = inbox / "empty.txt"
    txt.write_text("   ", encoding="utf-8")

    with patch.object(
        transcript_watcher.meeting_queue, "enqueue", return_value=None
    ) as mock_enqueue:
        handler = TranscriptHandler(bot=None, chat_id=0)
        await handler._process(txt)

    mock_enqueue.assert_called_once()
    assert not txt.exists()
    assert (inbox / "empty.processed.txt").exists()


@pytest.mark.asyncio
async def test_process_sends_telegram_notification(inbox: Path):
    """Если bot/chat_id заданы — отправляется лёгкое уведомление об очереди."""
    txt = inbox / "meeting.txt"
    txt.write_text("текст встречи", encoding="utf-8")

    bot = MagicMock()

    async def _send(*_a, **_k):
        return None

    bot.send_message = MagicMock(side_effect=_send)

    with patch.object(
        transcript_watcher.meeting_queue, "enqueue", return_value=MagicMock()
    ), patch.object(transcript_watcher._rate_limiter, "acquire") as mock_acq:
        async def _acq():
            return None

        mock_acq.side_effect = _acq
        handler = TranscriptHandler(bot=bot, chat_id=12345)
        await handler._process(txt)

    bot.send_message.assert_called_once()
    _args, kwargs = bot.send_message.call_args
    assert kwargs["chat_id"] == 12345
    assert "очередь" in kwargs["text"].lower()
