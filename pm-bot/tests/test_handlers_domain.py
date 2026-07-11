"""Tests for /domain and /rebuild_index Telegram command handlers."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import requests


def _make_update_context(args=None):
    update = MagicMock()
    update.effective_chat.id = 12345
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.args = args or []
    return update, context


# ---------------------------------------------------------------------------
# handle_domain — list
# ---------------------------------------------------------------------------

class TestDomainList:

    @pytest.mark.asyncio
    async def test_domain_list_success(self, monkeypatch):
        monkeypatch.setattr("app.handlers.ALLOWED_CHAT_ID", 12345)
        from app.handlers import handle_domain

        domains = [
            {"name": "static-metadata", "total": 52, "ideas": 10, "prds": 5,
             "epics": 5, "userstories": 10, "tasks": 20, "bugs": 2, "last_updated": "2026-01-01"},
            {"name": "suggester", "total": 1, "ideas": 1, "prds": 0,
             "epics": 0, "userstories": 0, "tasks": 0, "bugs": 0, "last_updated": "2026-01-01"},
        ]
        mock_result = {"status": "ok", "domains": domains, "count": 2}

        update, context = _make_update_context(args=["list"])

        with patch("app.handlers.ke_client.domain_list", return_value=mock_result):
            await handle_domain(update, context)

        calls = [str(c) for c in update.message.reply_text.call_args_list]
        full_text = " ".join(calls)
        assert "static-metadata" in full_text
        assert "suggester" in full_text

    @pytest.mark.asyncio
    async def test_domain_list_empty(self, monkeypatch):
        monkeypatch.setattr("app.handlers.ALLOWED_CHAT_ID", 12345)
        from app.handlers import handle_domain

        mock_result = {"status": "ok", "domains": [], "count": 0}

        update, context = _make_update_context(args=["list"])

        with patch("app.handlers.ke_client.domain_list", return_value=mock_result):
            await handle_domain(update, context)

        calls = [str(c) for c in update.message.reply_text.call_args_list]
        full_text = " ".join(calls)
        assert "0 доменов" in full_text or "нет" in full_text.lower()


# ---------------------------------------------------------------------------
# handle_domain — create
# ---------------------------------------------------------------------------

class TestDomainCreate:

    @pytest.mark.asyncio
    async def test_domain_create_success(self, monkeypatch):
        monkeypatch.setattr("app.handlers.ALLOWED_CHAT_ID", 12345)
        from app.handlers import handle_domain

        mock_result = {"status": "ok", "domain": "my-domain", "path": "/vault/wiki/domains/my-domain"}

        update, context = _make_update_context(args=["create", "my-domain"])

        with patch("app.handlers.ke_client.domain_create", return_value=mock_result):
            await handle_domain(update, context)

        calls = [str(c) for c in update.message.reply_text.call_args_list]
        full_text = " ".join(calls)
        assert "создан" in full_text

    @pytest.mark.asyncio
    async def test_domain_create_error(self, monkeypatch):
        monkeypatch.setattr("app.handlers.ALLOWED_CHAT_ID", 12345)
        from app.handlers import handle_domain

        mock_result = {"status": "error", "message": "Domain already exists"}

        update, context = _make_update_context(args=["create", "existing-domain"])

        with patch("app.handlers.ke_client.domain_create", return_value=mock_result):
            await handle_domain(update, context)

        calls = [str(c) for c in update.message.reply_text.call_args_list]
        full_text = " ".join(calls)
        assert "already exists" in full_text or "Domain already exists" in full_text


# ---------------------------------------------------------------------------
# handle_domain — no args / unknown subcommand
# ---------------------------------------------------------------------------

class TestDomainNoArgs:

    @pytest.mark.asyncio
    async def test_domain_no_args(self, monkeypatch):
        monkeypatch.setattr("app.handlers.ALLOWED_CHAT_ID", 12345)
        from app.handlers import handle_domain

        update, context = _make_update_context(args=[])

        await handle_domain(update, context)

        update.message.reply_text.assert_called_once()
        reply_text = update.message.reply_text.call_args[0][0]
        assert "/domain list" in reply_text
        assert "/domain create" in reply_text


# ---------------------------------------------------------------------------
# handle_rebuild_index
# ---------------------------------------------------------------------------

class TestRebuildIndex:

    @pytest.mark.asyncio
    async def test_rebuild_index_all(self, monkeypatch):
        monkeypatch.setattr("app.handlers.ALLOWED_CHAT_ID", 12345)
        from app.handlers import handle_rebuild_index

        mock_result = {
            "status": "ok",
            "rebuilt": ["static-metadata", "suggester"],
            "total_indices": 2
        }

        update, context = _make_update_context(args=[])

        with patch("app.handlers.ke_client.rebuild_index", return_value=mock_result):
            await handle_rebuild_index(update, context)

        calls = [str(c) for c in update.message.reply_text.call_args_list]
        full_text = " ".join(calls)
        assert "обновлены" in full_text

    @pytest.mark.asyncio
    async def test_rebuild_index_single_domain(self, monkeypatch):
        monkeypatch.setattr("app.handlers.ALLOWED_CHAT_ID", 12345)
        from app.handlers import handle_rebuild_index

        mock_result = {
            "status": "ok",
            "rebuilt": ["static-metadata"],
            "total_indices": 1
        }

        update, context = _make_update_context(args=["static-metadata"])

        with patch("app.handlers.ke_client.rebuild_index", return_value=mock_result):
            await handle_rebuild_index(update, context)

        calls = [str(c) for c in update.message.reply_text.call_args_list]
        full_text = " ".join(calls)
        assert "static-metadata" in full_text
        assert "обновлены" in full_text

    @pytest.mark.asyncio
    async def test_rebuild_index_error(self, monkeypatch):
        monkeypatch.setattr("app.handlers.ALLOWED_CHAT_ID", 12345)
        from app.handlers import handle_rebuild_index

        update, context = _make_update_context(args=[])

        with patch("app.handlers.ke_client.rebuild_index",
                   side_effect=requests.RequestException("Index rebuild failed: domain not found")):
            await handle_rebuild_index(update, context)

        calls = [str(c) for c in update.message.reply_text.call_args_list]
        full_text = " ".join(calls)
        assert "Ошибка" in full_text or "Index rebuild failed" in full_text


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------

class TestAccessControl:

    @pytest.mark.asyncio
    async def test_domain_not_allowed(self, monkeypatch):
        monkeypatch.setattr("app.handlers.ALLOWED_CHAT_ID", 99999)
        from app.handlers import handle_domain

        update = MagicMock()
        update.effective_chat.id = 12345
        update.message.reply_text = AsyncMock()
        context = MagicMock()
        context.args = ["list"]

        await handle_domain(update, context)

        update.message.reply_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_rebuild_index_not_allowed(self, monkeypatch):
        monkeypatch.setattr("app.handlers.ALLOWED_CHAT_ID", 99999)
        from app.handlers import handle_rebuild_index

        update = MagicMock()
        update.effective_chat.id = 12345
        update.message.reply_text = AsyncMock()
        context = MagicMock()
        context.args = []

        await handle_rebuild_index(update, context)

        update.message.reply_text.assert_not_called()


# ---------------------------------------------------------------------------
# Handler registration
# ---------------------------------------------------------------------------

class TestHandlersRegistered:

    def test_handlers_registered(self):
        from telegram.ext import CommandHandler

        from app.handlers import get_handlers

        handlers = get_handlers()
        command_names = set()
        for h in handlers:
            if isinstance(h, CommandHandler):
                command_names.update(h.commands)

        assert "domain" in command_names, "domain command not registered"
        assert "rebuild_index" in command_names, "rebuild_index command not registered"
