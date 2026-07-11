"""Tests for /jira_sync Telegram command handler."""


from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import requests


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

        mock_result = {
            "status": "ok",
            "new": 3,
            "updated": 5,
            "closed": 1,
            "errors": 0,
        }

        update, context = _make_update_context()

        with patch("app.handlers.ke_client.jira_sync", return_value=mock_result):
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

        mock_result = {
            "status": "ok",
            "new": 1,
            "updated": 2,
            "closed": 0,
            "errors": 4,
        }

        update, context = _make_update_context()

        with patch("app.handlers.ke_client.jira_sync", return_value=mock_result):
            await handle_jira_sync(update, context)

        calls = [str(c) for c in update.message.reply_text.call_args_list]
        full_text = " ".join(calls)
        assert "4 errors" in full_text


# ---------------------------------------------------------------------------
# handle_jira_sync — error
# ---------------------------------------------------------------------------

class TestJiraSyncError:

    @pytest.mark.asyncio
    async def test_jira_sync_request_error(self, monkeypatch):
        """When ke_client.jira_sync raises RequestException, error is shown."""
        monkeypatch.setattr("app.handlers.ALLOWED_CHAT_ID", 12345)
        from app.handlers import handle_jira_sync

        update, context = _make_update_context()

        with patch("app.handlers.ke_client.jira_sync",
                   side_effect=requests.RequestException("Connection refused")):
            await handle_jira_sync(update, context)

        calls = [str(c) for c in update.message.reply_text.call_args_list]
        full_text = " ".join(calls)
        assert "Connection refused" in full_text

    @pytest.mark.asyncio
    async def test_jira_sync_generic_exception(self, monkeypatch):
        """When ke_client.jira_sync raises a generic exception, error is shown."""
        monkeypatch.setattr("app.handlers.ALLOWED_CHAT_ID", 12345)
        from app.handlers import handle_jira_sync

        update, context = _make_update_context()

        with patch("app.handlers.ke_client.jira_sync",
                   side_effect=RuntimeError("Jira API token expired")):
            await handle_jira_sync(update, context)

        calls = [str(c) for c in update.message.reply_text.call_args_list]
        full_text = " ".join(calls)
        assert "Jira API token expired" in full_text


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
        from telegram.ext import CommandHandler

        from app.handlers import get_handlers

        handlers = get_handlers()
        command_names = set()
        for h in handlers:
            if isinstance(h, CommandHandler):
                command_names.update(h.commands)

        assert "jira_sync" in command_names, "jira_sync command not registered"
