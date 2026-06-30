"""Tests for handle_fetch_meetings notification text (queue semantics, T-14)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import app.handlers as h


def _run_fetch(sample_dict):
    msgs = []
    upd = MagicMock()
    upd.message.reply_text = AsyncMock(side_effect=lambda t: msgs.append(t))
    with patch.object(h, "_is_allowed", return_value=True), patch.object(
        h.ke_client, "fetch_meetings", return_value=sample_dict
    ):
        asyncio.run(h.handle_fetch_meetings(upd, MagicMock()))
    return msgs


def test_fetch_meetings_queue_wording():
    sample = {
        "status": "ok",
        "total_emails": 4,
        "newly_processed": 3,
        "enqueued": 3,
        "already_processed": 1,
        "errors": 0,
        "message": "Meeting Fetcher: 3 писем поставлено в очередь",
        "details": [
            {"unit_id": "u1", "subject": "Sync GO-1", "source": "email", "status": "pending"},
            {"unit_id": "u2", "subject": "Planning", "source": "email", "status": "pending"},
            {"unit_id": "u3", "subject": "Retro", "source": "email", "status": "pending"},
        ],
    }
    msgs = _run_fetch(sample)
    body = "\n".join(msgs)
    assert "очеред" in body
    assert "Обработано" not in body
    assert "Поставлено в очередь: 3" in body
    assert "Уже в очереди (пропущено): 1" in body


def test_fetch_meetings_nothing_new():
    sample = {
        "status": "ok",
        "total_emails": 2,
        "newly_processed": 0,
        "enqueued": 0,
        "already_processed": 2,
        "errors": 0,
        "message": "no new",
        "details": [],
    }
    msgs = _run_fetch(sample)
    assert any("не найдено" in m for m in msgs)
    assert not any("Обработано" in m for m in msgs)
