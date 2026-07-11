"""Tests for /lint and /status Telegram command handlers."""


from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import requests


def _make_update_context(chat_id=12345, args=None):
    update = MagicMock()
    update.effective_chat.id = chat_id
    update.effective_user.id = chat_id
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.args = args or []
    return update, context


def _clean_lint_result(total_issues=0):
    return {
        "status": "ok",
        "broken_links": [],
        "orphan_pages": [],
        "stale_drafts": [],
        "unsorted_misc": [],
        "summary": {
            "broken_links_count": 0,
            "orphan_pages_count": 0,
            "stale_drafts_count": 0,
            "unsorted_misc_count": total_issues,
            "total_issues": total_issues,
        },
    }


def _lint_result_with_issues():
    return {
        "status": "ok",
        "broken_links": [
            {"file": "wiki/domains/test/ideas/idea.md", "line": 3, "link": "missing", "reason": "target not found"}
        ],
        "orphan_pages": [
            {"file": "wiki/domains/test/prds/prd-01.md", "domain": "test", "artifact_type": "prds"}
        ],
        "stale_drafts": [
            {"file": "wiki/domains/test/ideas/old.md", "domain": "test", "days_old": 45, "status": "draft"}
        ],
        "unsorted_misc": [
            {"file": "raw/inbound/misc/note.txt", "days_old": 10}
        ],
        "summary": {
            "broken_links_count": 1,
            "orphan_pages_count": 1,
            "stale_drafts_count": 1,
            "unsorted_misc_count": 1,
            "total_issues": 4,
        },
    }


def _status_result(domains=None, raw_counts=None, total_issues=0):
    domains = domains or []
    return {
        "status": "ok",
        "domains": domains,
        "domains_count": len(domains),
        "total_artifacts": sum(d.get("total", 0) for d in domains),
        "raw_counts": raw_counts or {},
        "health": {
            "broken_links_count": 0,
            "orphan_pages_count": 0,
            "stale_drafts_count": 0,
            "unsorted_misc_count": total_issues,
            "total_issues": total_issues,
        },
    }


# ---------------------------------------------------------------------------
# handle_lint — clean vault
# ---------------------------------------------------------------------------


class TestHandleLintClean:

    @pytest.mark.asyncio
    async def test_lint_clean_vault_reply_contains_no_issues(self, monkeypatch):
        monkeypatch.setattr("app.handlers.ALLOWED_CHAT_ID", 12345)
        from app.handlers import handle_lint

        update, context = _make_update_context()

        with patch("app.handlers.ke_client.lint", return_value=_clean_lint_result(0)):
            await handle_lint(update, context)

        reply_calls = update.message.reply_text.call_args_list
        assert len(reply_calls) == 2
        report_text = reply_calls[1][0][0]
        assert "Проблем не найдено" in report_text

    @pytest.mark.asyncio
    async def test_lint_sends_initial_message(self, monkeypatch):
        monkeypatch.setattr("app.handlers.ALLOWED_CHAT_ID", 12345)
        from app.handlers import handle_lint

        update, context = _make_update_context()

        with patch("app.handlers.ke_client.lint", return_value=_clean_lint_result(0)):
            await handle_lint(update, context)

        first_call_text = update.message.reply_text.call_args_list[0][0][0]
        assert "проверку" in first_call_text.lower() or "vault" in first_call_text.lower()


# ---------------------------------------------------------------------------
# handle_lint — issues found
# ---------------------------------------------------------------------------


class TestHandleLintWithIssues:

    @pytest.mark.asyncio
    async def test_lint_reports_total_issues_count(self, monkeypatch):
        monkeypatch.setattr("app.handlers.ALLOWED_CHAT_ID", 12345)
        from app.handlers import handle_lint

        update, context = _make_update_context()

        with patch("app.handlers.ke_client.lint", return_value=_lint_result_with_issues()):
            await handle_lint(update, context)

        report_text = update.message.reply_text.call_args_list[1][0][0]
        assert "4" in report_text

    @pytest.mark.asyncio
    async def test_lint_reports_broken_links(self, monkeypatch):
        monkeypatch.setattr("app.handlers.ALLOWED_CHAT_ID", 12345)
        from app.handlers import handle_lint

        update, context = _make_update_context()

        with patch("app.handlers.ke_client.lint", return_value=_lint_result_with_issues()):
            await handle_lint(update, context)

        report_text = update.message.reply_text.call_args_list[1][0][0]
        assert "Битые ссылки" in report_text or "missing" in report_text

    @pytest.mark.asyncio
    async def test_lint_reports_orphan_pages(self, monkeypatch):
        monkeypatch.setattr("app.handlers.ALLOWED_CHAT_ID", 12345)
        from app.handlers import handle_lint

        update, context = _make_update_context()

        with patch("app.handlers.ke_client.lint", return_value=_lint_result_with_issues()):
            await handle_lint(update, context)

        report_text = update.message.reply_text.call_args_list[1][0][0]
        assert "Сиротские" in report_text or "prd-01" in report_text

    @pytest.mark.asyncio
    async def test_lint_reports_stale_drafts(self, monkeypatch):
        monkeypatch.setattr("app.handlers.ALLOWED_CHAT_ID", 12345)
        from app.handlers import handle_lint

        update, context = _make_update_context()

        with patch("app.handlers.ke_client.lint", return_value=_lint_result_with_issues()):
            await handle_lint(update, context)

        report_text = update.message.reply_text.call_args_list[1][0][0]
        assert "черновики" in report_text.lower() or "45" in report_text

    @pytest.mark.asyncio
    async def test_lint_reports_unsorted_misc(self, monkeypatch):
        monkeypatch.setattr("app.handlers.ALLOWED_CHAT_ID", 12345)
        from app.handlers import handle_lint

        update, context = _make_update_context()

        with patch("app.handlers.ke_client.lint", return_value=_lint_result_with_issues()):
            await handle_lint(update, context)

        report_text = update.message.reply_text.call_args_list[1][0][0]
        assert "misc" in report_text.lower() or "Несортированные" in report_text


# ---------------------------------------------------------------------------
# handle_lint — error / timeout
# ---------------------------------------------------------------------------


class TestHandleLintErrors:

    @pytest.mark.asyncio
    async def test_lint_request_error(self, monkeypatch):
        monkeypatch.setattr("app.handlers.ALLOWED_CHAT_ID", 12345)
        from app.handlers import handle_lint

        update, context = _make_update_context()

        with patch("app.handlers.ke_client.lint",
                   side_effect=requests.RequestException("some error")):
            await handle_lint(update, context)

        reply_calls = update.message.reply_text.call_args_list
        full_text = " ".join(str(c) for c in reply_calls)
        assert "Ошибка" in full_text or "ошибка" in full_text or "some error" in full_text

    @pytest.mark.asyncio
    async def test_lint_general_exception_handled(self, monkeypatch):
        monkeypatch.setattr("app.handlers.ALLOWED_CHAT_ID", 12345)
        from app.handlers import handle_lint

        update, context = _make_update_context()

        with patch("app.handlers.ke_client.lint",
                   side_effect=RuntimeError("unexpected")):
            await handle_lint(update, context)

        reply_calls = update.message.reply_text.call_args_list
        full_text = " ".join(str(c) for c in reply_calls)
        assert "Ошибка" in full_text or "ошибка" in full_text


# ---------------------------------------------------------------------------
# handle_lint — access control
# ---------------------------------------------------------------------------


class TestHandleLintAccessControl:

    @pytest.mark.asyncio
    async def test_lint_not_allowed(self, monkeypatch):
        monkeypatch.setattr("app.handlers.ALLOWED_CHAT_ID", 99999)
        from app.handlers import handle_lint

        update, context = _make_update_context(chat_id=12345)

        await handle_lint(update, context)

        update.message.reply_text.assert_not_called()


# ---------------------------------------------------------------------------
# handle_status — success
# ---------------------------------------------------------------------------


class TestHandleStatusSuccess:

    @pytest.mark.asyncio
    async def test_status_shows_domains_count(self, monkeypatch):
        monkeypatch.setattr("app.handlers.ALLOWED_CHAT_ID", 12345)
        from app.handlers import handle_status

        update, context = _make_update_context()
        domains = [
            {"name": "alpha", "ideas": 2, "prds": 1, "epics": 0, "userstories": 0,
             "tasks": 0, "bugs": 0, "total": 3, "last_updated": "2026-01-01"},
        ]
        mock_result = _status_result(domains=domains)

        with patch("app.handlers.ke_client.status", return_value=mock_result):
            await handle_status(update, context)

        report_text = update.message.reply_text.call_args_list[1][0][0]
        assert "1" in report_text
        assert "Доменов" in report_text

    @pytest.mark.asyncio
    async def test_status_shows_total_artifacts(self, monkeypatch):
        monkeypatch.setattr("app.handlers.ALLOWED_CHAT_ID", 12345)
        from app.handlers import handle_status

        update, context = _make_update_context()
        domains = [
            {"name": "alpha", "ideas": 5, "prds": 0, "epics": 0, "userstories": 0,
             "tasks": 0, "bugs": 0, "total": 5, "last_updated": "2026-01-01"},
        ]
        mock_result = _status_result(domains=domains)

        with patch("app.handlers.ke_client.status", return_value=mock_result):
            await handle_status(update, context)

        report_text = update.message.reply_text.call_args_list[1][0][0]
        assert "5" in report_text
        assert "Артефактов" in report_text

    @pytest.mark.asyncio
    async def test_status_shows_domain_name(self, monkeypatch):
        monkeypatch.setattr("app.handlers.ALLOWED_CHAT_ID", 12345)
        from app.handlers import handle_status

        update, context = _make_update_context()
        domains = [
            {"name": "my-domain", "ideas": 1, "prds": 0, "epics": 0, "userstories": 0,
             "tasks": 0, "bugs": 0, "total": 1, "last_updated": "2026-01-01"},
        ]
        mock_result = _status_result(domains=domains)

        with patch("app.handlers.ke_client.status", return_value=mock_result):
            await handle_status(update, context)

        report_text = update.message.reply_text.call_args_list[1][0][0]
        assert "my-domain" in report_text

    @pytest.mark.asyncio
    async def test_status_shows_health_no_issues(self, monkeypatch):
        monkeypatch.setattr("app.handlers.ALLOWED_CHAT_ID", 12345)
        from app.handlers import handle_status

        update, context = _make_update_context()
        mock_result = _status_result()

        with patch("app.handlers.ke_client.status", return_value=mock_result):
            await handle_status(update, context)

        report_text = update.message.reply_text.call_args_list[1][0][0]
        assert "Проблем не найдено" in report_text

    @pytest.mark.asyncio
    async def test_status_shows_health_with_issues(self, monkeypatch):
        monkeypatch.setattr("app.handlers.ALLOWED_CHAT_ID", 12345)
        from app.handlers import handle_status

        update, context = _make_update_context()
        mock_result = _status_result(total_issues=3)

        with patch("app.handlers.ke_client.status", return_value=mock_result):
            await handle_status(update, context)

        report_text = update.message.reply_text.call_args_list[1][0][0]
        assert "3" in report_text
        assert "lint" in report_text.lower() or "Проблем" in report_text

    @pytest.mark.asyncio
    async def test_status_sends_initial_message(self, monkeypatch):
        monkeypatch.setattr("app.handlers.ALLOWED_CHAT_ID", 12345)
        from app.handlers import handle_status

        update, context = _make_update_context()
        mock_result = _status_result()

        with patch("app.handlers.ke_client.status", return_value=mock_result):
            await handle_status(update, context)

        first_call_text = update.message.reply_text.call_args_list[0][0][0]
        assert "статус" in first_call_text.lower() or "vault" in first_call_text.lower()


# ---------------------------------------------------------------------------
# handle_status — error / timeout
# ---------------------------------------------------------------------------


class TestHandleStatusErrors:

    @pytest.mark.asyncio
    async def test_status_request_error(self, monkeypatch):
        monkeypatch.setattr("app.handlers.ALLOWED_CHAT_ID", 12345)
        from app.handlers import handle_status

        update, context = _make_update_context()

        with patch("app.handlers.ke_client.status",
                   side_effect=requests.RequestException("connection failed")):
            await handle_status(update, context)

        reply_calls = update.message.reply_text.call_args_list
        full_text = " ".join(str(c) for c in reply_calls)
        assert "Ошибка" in full_text or "ошибка" in full_text or "connection failed" in full_text

    @pytest.mark.asyncio
    async def test_status_general_exception_handled(self, monkeypatch):
        monkeypatch.setattr("app.handlers.ALLOWED_CHAT_ID", 12345)
        from app.handlers import handle_status

        update, context = _make_update_context()

        with patch("app.handlers.ke_client.status",
                   side_effect=RuntimeError("boom")):
            await handle_status(update, context)

        reply_calls = update.message.reply_text.call_args_list
        full_text = " ".join(str(c) for c in reply_calls)
        assert "Ошибка" in full_text or "ошибка" in full_text


# ---------------------------------------------------------------------------
# handle_status — access control
# ---------------------------------------------------------------------------


class TestHandleStatusAccessControl:

    @pytest.mark.asyncio
    async def test_status_not_allowed(self, monkeypatch):
        monkeypatch.setattr("app.handlers.ALLOWED_CHAT_ID", 99999)
        from app.handlers import handle_status

        update, context = _make_update_context(chat_id=12345)

        await handle_status(update, context)

        update.message.reply_text.assert_not_called()


# ---------------------------------------------------------------------------
# Handler registration
# ---------------------------------------------------------------------------


class TestHandlerRegistration:

    def test_lint_handler_registered(self):
        from telegram.ext import CommandHandler

        from app.handlers import get_handlers

        handlers = get_handlers()
        command_names = set()
        for h in handlers:
            if isinstance(h, CommandHandler):
                command_names.update(h.commands)

        assert "lint" in command_names, "lint command not registered in get_handlers()"

    def test_status_handler_registered(self):
        from telegram.ext import CommandHandler

        from app.handlers import get_handlers

        handlers = get_handlers()
        command_names = set()
        for h in handlers:
            if isinstance(h, CommandHandler):
                command_names.update(h.commands)

        assert "status" in command_names, "status command not registered in get_handlers()"
