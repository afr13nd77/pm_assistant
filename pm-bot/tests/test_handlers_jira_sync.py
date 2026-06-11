"""Tests for /jira_sync Telegram command handler."""

import json
import subprocess

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_update_context(chat_id=12345, args=None):
    update = MagicMock()
    update.effective_chat.id = chat_id
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.args = args or []
    return update, context


# ---------------------------------------------------------------------------
# handle_jira_sync — success
# ---------------------------------------------------------------------------

class TestJiraSyncSuccess:

    @pytest.mark.asyncio
    async def test_jira_sync_success(self, monkeypatch):
        monkeypatch.setattr("app.handlers.ALLOWED_CHAT_ID", 12345)
        from app.handlers import handle_jira_sync

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({
            "new": 3,
            "updated": 5,
            "closed": 1,
            "errors": 0,
        })
        mock_result.stderr = ""

        update, context = _make_update_context()

        with patch("subprocess.run", return_value=mock_result):
            await handle_jira_sync(update, context)

        calls = [str(c) for c in update.message.reply_text.call_args_list]
        full_text = " ".join(calls)
        assert "Jira sync" in full_text
        assert "3 new" in full_text
        assert "5 updated" in full_text
        assert "1 closed" in full_text

    @pytest.mark.asyncio
    async def test_jira_sync_success_with_errors(self, monkeypatch):
        monkeypatch.setattr("app.handlers.ALLOWED_CHAT_ID", 12345)
        from app.handlers import handle_jira_sync

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({
            "new": 1,
            "updated": 2,
            "closed": 0,
            "errors": 4,
        })
        mock_result.stderr = ""

        update, context = _make_update_context()

        with patch("subprocess.run", return_value=mock_result):
            await handle_jira_sync(update, context)

        calls = [str(c) for c in update.message.reply_text.call_args_list]
        full_text = " ".join(calls)
        assert "4 errors" in full_text

    @pytest.mark.asyncio
    async def test_jira_sync_success_invalid_json(self, monkeypatch):
        """When subprocess succeeds but stdout is not valid JSON, fallback message."""
        monkeypatch.setattr("app.handlers.ALLOWED_CHAT_ID", 12345)
        from app.handlers import handle_jira_sync

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "not json"
        mock_result.stderr = ""

        update, context = _make_update_context()

        with patch("subprocess.run", return_value=mock_result):
            await handle_jira_sync(update, context)

        calls = [str(c) for c in update.message.reply_text.call_args_list]
        full_text = " ".join(calls)
        assert "завершена" in full_text


# ---------------------------------------------------------------------------
# handle_jira_sync — error
# ---------------------------------------------------------------------------

class TestJiraSyncError:

    @pytest.mark.asyncio
    async def test_jira_sync_error_stderr(self, monkeypatch):
        monkeypatch.setattr("app.handlers.ALLOWED_CHAT_ID", 12345)
        from app.handlers import handle_jira_sync

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "Connection refused"

        update, context = _make_update_context()

        with patch("subprocess.run", return_value=mock_result):
            await handle_jira_sync(update, context)

        calls = [str(c) for c in update.message.reply_text.call_args_list]
        full_text = " ".join(calls)
        assert "Connection refused" in full_text

    @pytest.mark.asyncio
    async def test_jira_sync_error_json_message(self, monkeypatch):
        """When subprocess fails but stdout has JSON with message field."""
        monkeypatch.setattr("app.handlers.ALLOWED_CHAT_ID", 12345)
        from app.handlers import handle_jira_sync

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = json.dumps({"message": "Jira API token expired"})
        mock_result.stderr = "some stderr"

        update, context = _make_update_context()

        with patch("subprocess.run", return_value=mock_result):
            await handle_jira_sync(update, context)

        calls = [str(c) for c in update.message.reply_text.call_args_list]
        full_text = " ".join(calls)
        assert "Jira API token expired" in full_text


# ---------------------------------------------------------------------------
# handle_jira_sync — timeout
# ---------------------------------------------------------------------------

class TestJiraSyncTimeout:

    @pytest.mark.asyncio
    async def test_jira_sync_timeout(self, monkeypatch):
        monkeypatch.setattr("app.handlers.ALLOWED_CHAT_ID", 12345)
        from app.handlers import handle_jira_sync

        update, context = _make_update_context()

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="test", timeout=120)):
            await handle_jira_sync(update, context)

        calls = [str(c) for c in update.message.reply_text.call_args_list]
        full_text = " ".join(calls)
        assert "2 минуты" in full_text


# ---------------------------------------------------------------------------
# handle_jira_sync — access control
# ---------------------------------------------------------------------------

class TestJiraSyncAccessControl:

    @pytest.mark.asyncio
    async def test_jira_sync_not_allowed(self, monkeypatch):
        monkeypatch.setattr("app.handlers.ALLOWED_CHAT_ID", 99999)
        from app.handlers import handle_jira_sync

        update, context = _make_update_context(chat_id=12345)

        await handle_jira_sync(update, context)

        update.message.reply_text.assert_not_called()


# ---------------------------------------------------------------------------
# Handler registration
# ---------------------------------------------------------------------------

class TestJiraSyncRegistered:

    def test_jira_sync_handler_registered(self):
        from app.handlers import get_handlers
        from telegram.ext import CommandHandler

        handlers = get_handlers()
        command_names = set()
        for h in handlers:
            if isinstance(h, CommandHandler):
                command_names.update(h.commands)

        assert "jira_sync" in command_names, "jira_sync command not registered"
