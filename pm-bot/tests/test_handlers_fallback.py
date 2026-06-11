"""Tests for Claude API fallback behaviour in handlers.

When process_idea / process_jira_ticket raise (e.g. credit balance too low),
the handler should save the raw text via a fallback template instead of
surfacing an error to the user.
"""

from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.handlers import _fallback_idea_data, _fallback_jira_content


# ---------------------------------------------------------------------------
# Helper content format tests
# ---------------------------------------------------------------------------

class TestFallbackIdeaContentFormat:
    def test_contains_required_keys(self):
        result = _fallback_idea_data("my raw idea text")
        for key in ("title", "domain", "problem", "solution", "usp", "metric", "tags"):
            assert key in result, f"Missing key: {key}"

    def test_default_domain_is_general(self):
        result = _fallback_idea_data("my raw idea text")
        assert result["domain"] == "general"

    def test_contains_raw_text_in_problem(self):
        raw = "Integrate payment gateway with Stripe"
        result = _fallback_idea_data(raw)
        assert result["problem"] == raw

    def test_title_truncated_at_word_boundary(self):
        long_text = "Implement a distributed caching layer for the microservices architecture"
        result = _fallback_idea_data(long_text)
        assert len(result["title"]) <= 50
        # Title should be truncated at the last space before 50 chars
        assert result["title"] == "Implement a distributed caching layer for the"


class TestFallbackJiraContentFormat:
    def test_contains_frontmatter_fields(self):
        content = _fallback_jira_content("my raw jira text")
        assert "title: Без LLM анализа" in content
        assert "status: draft" in content
        assert "domain: general" in content
        assert f"created: {date.today().isoformat()}" in content
        assert "llm_processed: false" in content

    def test_contains_raw_text(self):
        raw = "Fix bug in checkout flow"
        content = _fallback_jira_content(raw)
        assert raw in content

    def test_has_markdown_heading(self):
        content = _fallback_jira_content("anything")
        assert "# Без LLM анализа" in content

    def test_starts_with_frontmatter_delimiters(self):
        content = _fallback_jira_content("anything")
        assert content.startswith("---\n")
        assert "\n---\n" in content


# ---------------------------------------------------------------------------
# handle_text fallback integration tests
# ---------------------------------------------------------------------------

def _make_update(chat_id: int = 12345, text: str = "test idea"):
    """Build a minimal mock Update with a text message."""
    update = MagicMock()
    update.effective_chat.id = chat_id
    update.message.text = text
    update.message.reply_text = AsyncMock()
    return update


def _make_context(mode: str = "idea"):
    """Build a minimal mock context with user_data and chat_data."""
    ctx = MagicMock()
    ctx.user_data = {"mode": mode}
    ctx.chat_data = {}
    return ctx


@pytest.mark.asyncio
@patch("app.handlers.ALLOWED_CHAT_ID", 12345)
@patch("app.handlers._send_idea_with_prompt", new_callable=AsyncMock)
@patch("app.handlers._run_enrichment", return_value=None)
@patch("app.handlers.process_idea", side_effect=Exception("credit balance is too low"))
@patch("app.handlers.write_idea")
async def test_idea_claude_error_saves_fallback(
    mock_write_idea, mock_process_idea, mock_enrich, mock_send_prompt
):
    mock_write_idea.return_value = Path("/fake/vault/IDEA-0001.md")
    update = _make_update(text="My brilliant idea")
    ctx = _make_context(mode="idea")

    from app.handlers import handle_text
    await handle_text(update, ctx)

    # process_idea was called and raised
    mock_process_idea.assert_called_once_with("My brilliant idea")

    # write_idea was called with fallback content and raw text
    assert mock_write_idea.call_count == 1
    written_content = mock_write_idea.call_args[0][0]
    raw_text_arg = mock_write_idea.call_args[0][1]

    assert written_content["title"] == "My brilliant idea"
    assert written_content["domain"] == "general"
    assert written_content["problem"] == "My brilliant idea"
    assert raw_text_arg == "My brilliant idea"

    # The prompt was still sent (no error message)
    mock_send_prompt.assert_called_once()


@pytest.mark.asyncio
@patch("app.handlers.ALLOWED_CHAT_ID", 12345)
@patch("app.handlers.process_jira_ticket", side_effect=Exception("rate limit exceeded"))
@patch("app.handlers.write_jira_draft")
async def test_jira_claude_error_saves_fallback(
    mock_write_jira, mock_process_jira
):
    mock_write_jira.return_value = Path("/fake/vault/JIRA-0001.md")
    update = _make_update(text="Fix login page crash")
    ctx = _make_context(mode="jira")

    from app.handlers import handle_text
    await handle_text(update, ctx)

    # process_jira_ticket was called and raised
    mock_process_jira.assert_called_once_with("Fix login page crash")

    # write_jira_draft was called with fallback content
    assert mock_write_jira.call_count == 1
    written_content = mock_write_jira.call_args[0][0]

    assert "Без LLM анализа" in written_content
    assert "llm_processed: false" in written_content
    assert "status: draft" in written_content
    assert "Fix login page crash" in written_content

    # User saw a success message, not an error
    reply_calls = update.message.reply_text.call_args_list
    last_reply = reply_calls[-1]
    assert "Черновик Jira сохранён" in last_reply[0][0]


@pytest.mark.asyncio
@patch("app.handlers.ALLOWED_CHAT_ID", 12345)
@patch("app.handlers._send_idea_with_prompt", new_callable=AsyncMock)
@patch("app.handlers._run_enrichment", return_value=None)
@patch("app.handlers.process_idea", return_value="# Great Idea\n\nProcessed content")
@patch("app.handlers.write_idea")
async def test_idea_claude_success_normal_flow(
    mock_write_idea, mock_process_idea, mock_enrich, mock_send_prompt
):
    mock_write_idea.return_value = Path("/fake/vault/IDEA-0001.md")
    update = _make_update(text="Normal idea text")
    ctx = _make_context(mode="idea")

    from app.handlers import handle_text
    await handle_text(update, ctx)

    mock_process_idea.assert_called_once_with("Normal idea text")

    # write_idea was called with LLM-processed content, not fallback
    written_content = mock_write_idea.call_args[0][0]
    assert written_content == "# Great Idea\n\nProcessed content"
    assert "Без LLM анализа" not in written_content

    mock_send_prompt.assert_called_once()
