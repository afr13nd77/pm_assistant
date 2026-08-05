"""Tests for signal triage endpoints.

BL-203 T-23 (signal-level triage):
  GET  /api/v1/signals/list
  GET  /api/v1/signals/{signal_id}
  POST /api/v1/signals/{signal_id}/approve
  POST /api/v1/signals/{signal_id}/dismiss
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _create_signal_files(
    tmp_path: Path,
    signal_id: str,
    status: str = "pending",
    title: str = "Test Signal",
    threat_level: str = "medium",
    draft_idea: dict | None = None,
    source: str = "TestSource",
    relevance_score: int = 7,
    signal_date: str = "2026-08-01",
) -> None:
    """Create wiki MD + raw JSON for a test signal."""
    signals_dir = tmp_path / "wiki" / "reports" / "signals"
    signals_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = tmp_path / "raw" / "inbound" / "signals"
    raw_dir.mkdir(parents=True, exist_ok=True)

    fm = (
        f"---\n"
        f"type: signal\n"
        f"title: {title}\n"
        f"source: {source}\n"
        f"source_url: https://example.com\n"
        f"relevance_score: {relevance_score}\n"
        f"threat_level: {threat_level}\n"
        f"status: {status}\n"
        f'signal_date: "{signal_date}"\n'
        f"report_ref: report.md\n"
        f'result_ref: ""\n'
        f'created: "2026-08-01T10:00:00"\n'
        f"---\n"
        f"\n"
        f"## Анализ\n"
        f"Test analysis content.\n"
        f"\n"
        f"## Рекомендация\n"
        f"Test recommendation.\n"
    )
    (signals_dir / f"{signal_id}.md").write_text(fm, encoding="utf-8")

    raw_data = {
        "title": title,
        "analysis": "Test analysis",
        "threat_level": threat_level,
        "recommended_action": "Monitor",
        "draft_idea": draft_idea,
        "domain": "general",
        "priority_hint": "medium",
        "rationale": "Test rationale",
        "source": source,
        "source_url": "https://example.com",
        "relevance_score": relevance_score,
        "report_ref": "report.md",
        "run_id": "test-run",
    }
    (raw_dir / f"{signal_id}.json").write_text(
        json.dumps(raw_data, ensure_ascii=False), encoding="utf-8"
    )


@pytest.fixture
def signal_vault(tmp_path):
    """Create a temporary vault with signal directories pre-created."""
    (tmp_path / "wiki" / "reports" / "signals").mkdir(parents=True, exist_ok=True)
    (tmp_path / "raw" / "inbound" / "signals").mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.fixture
def signal_client(signal_vault):
    """TestClient for pm-bot's vault_api with vault_paths patched for signals.

    Patches both the vault_api module-level VAULT_PATH and the shared
    vault_paths.VAULT_PATH so that vault_paths.wiki_signals() and
    vault_paths.raw_signals() resolve to the temporary directory.
    """
    import shared.vault_paths as _vp

    with (
        patch("app.vault_api.VAULT_PATH", signal_vault),
        patch.object(_vp, "VAULT_PATH", signal_vault),
        patch(
            "app.vault_api.wiki_meetings",
            return_value=signal_vault / "wiki" / "meetings",
        ),
        patch(
            "app.vault_api.wiki_reports",
            return_value=signal_vault / "wiki" / "reports",
        ),
        patch(
            "app.vault_api.all_domains",
            return_value=[],
        ),
        patch(
            "app.vault_api.wiki_domain_dir",
            side_effect=lambda domain, at: signal_vault
            / "wiki"
            / "domains"
            / domain
            / at,
        ),
    ):
        from fastapi.testclient import TestClient

        from app.vault_api import _cache, app

        _cache.invalidate()
        yield TestClient(app)


# ---------------------------------------------------------------------------
# GET /api/v1/signals/list
# ---------------------------------------------------------------------------


class TestSignalsList:
    """Tests for GET /api/v1/signals/list (BL-203)."""

    def test_empty(self, signal_client):
        """No signal files -> empty list with total=0."""
        resp = signal_client.get("/api/v1/signals/list")
        assert resp.status_code == 200
        data = resp.json()
        assert data["signals"] == []
        assert data["total"] == 0

    def test_with_pending(self, signal_client, signal_vault):
        """Two pending signals -> list with 2 items."""
        _create_signal_files(signal_vault, "2026-08-01-sig-alpha", status="pending")
        _create_signal_files(
            signal_vault, "2026-08-01-sig-beta", status="pending", title="Beta Signal"
        )

        resp = signal_client.get("/api/v1/signals/list")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["signals"]) == 2
        assert data["total"] == 2

    def test_filter_by_status(self, signal_client, signal_vault):
        """status=pending should exclude approved signals."""
        _create_signal_files(
            signal_vault, "2026-08-01-sig-pend", status="pending", title="Pending one"
        )
        _create_signal_files(
            signal_vault, "2026-08-01-sig-appr", status="approved", title="Approved one"
        )

        resp = signal_client.get("/api/v1/signals/list?status=pending")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["signals"]) == 1
        assert data["signals"][0]["signal_id"] == "2026-08-01-sig-pend"

    def test_filter_by_date(self, signal_client, signal_vault):
        """date filter should match signal_date frontmatter."""
        _create_signal_files(
            signal_vault,
            "2026-08-01-sig-today",
            signal_date="2026-08-01",
            title="Today",
        )
        _create_signal_files(
            signal_vault,
            "2026-07-30-sig-old",
            signal_date="2026-07-30",
            title="Old",
        )

        resp = signal_client.get("/api/v1/signals/list?date=2026-08-01")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["signals"]) == 1
        assert data["signals"][0]["signal_id"] == "2026-08-01-sig-today"

    def test_has_draft_idea(self, signal_client, signal_vault):
        """has_draft_idea should be True when raw JSON has draft_idea."""
        draft = {"title": "Draft idea", "problem": "P", "solution": "S"}
        _create_signal_files(
            signal_vault,
            "2026-08-01-sig-draft",
            draft_idea=draft,
        )
        _create_signal_files(
            signal_vault,
            "2026-08-01-sig-nodraft",
            draft_idea=None,
        )

        resp = signal_client.get("/api/v1/signals/list")
        assert resp.status_code == 200
        signals_by_id = {s["signal_id"]: s for s in resp.json()["signals"]}
        assert signals_by_id["2026-08-01-sig-draft"]["has_draft_idea"] is True
        assert signals_by_id["2026-08-01-sig-nodraft"]["has_draft_idea"] is False

    def test_skips_report_files(self, signal_client, signal_vault):
        """Files ending with -report.md should be excluded."""
        _create_signal_files(signal_vault, "2026-08-01-sig-normal")
        # Write a report file manually
        signals_dir = signal_vault / "wiki" / "reports" / "signals"
        report_content = (
            "---\n"
            "type: signal\n"
            "title: Report\n"
            "status: pending\n"
            "---\n"
        )
        (signals_dir / "2026-08-01-sig-normal-report.md").write_text(
            report_content, encoding="utf-8"
        )

        resp = signal_client.get("/api/v1/signals/list")
        assert resp.status_code == 200
        ids = [s["signal_id"] for s in resp.json()["signals"]]
        assert "2026-08-01-sig-normal" in ids
        assert "2026-08-01-sig-normal-report" not in ids

    def test_limit(self, signal_client, signal_vault):
        """limit parameter should cap the number of returned signals."""
        for i in range(5):
            _create_signal_files(
                signal_vault,
                f"2026-08-01-sig-lim-{i:02d}",
                title=f"Signal {i}",
            )

        resp = signal_client.get("/api/v1/signals/list?limit=2")
        assert resp.status_code == 200
        assert len(resp.json()["signals"]) == 2

    def test_response_fields(self, signal_client, signal_vault):
        """Verify all expected fields are present in each signal entry."""
        _create_signal_files(signal_vault, "2026-08-01-sig-fields")

        resp = signal_client.get("/api/v1/signals/list")
        assert resp.status_code == 200
        sig = resp.json()["signals"][0]

        expected_keys = {
            "signal_id",
            "title",
            "source",
            "source_url",
            "relevance_score",
            "threat_level",
            "status",
            "signal_date",
            "has_draft_idea",
            "report_ref",
            "result_ref",
            "created",
        }
        assert expected_keys.issubset(sig.keys())


# ---------------------------------------------------------------------------
# GET /api/v1/signals/{signal_id}
# ---------------------------------------------------------------------------


class TestSignalDetail:
    """Tests for GET /api/v1/signals/{signal_id} (BL-203)."""

    def test_success(self, signal_client, signal_vault):
        """Existing signal_id -> 200 with full details."""
        draft = {"title": "Idea draft", "problem": "P"}
        _create_signal_files(
            signal_vault,
            "2026-08-01-detail-test",
            title="Detail Test Signal",
            draft_idea=draft,
        )

        resp = signal_client.get("/api/v1/signals/2026-08-01-detail-test")
        assert resp.status_code == 200
        data = resp.json()
        assert data["signal_id"] == "2026-08-01-detail-test"
        assert data["title"] == "Detail Test Signal"
        assert data["analysis"] == "Test analysis content."
        assert data["recommended_action"] == "Test recommendation."
        assert data["draft_idea"] == draft

    def test_not_found(self, signal_client):
        """Non-existent signal_id -> 404."""
        resp = signal_client.get("/api/v1/signals/nonexistent-signal")
        assert resp.status_code == 404

    def test_without_raw_json(self, signal_client, signal_vault):
        """Signal with wiki MD but no raw JSON -> draft_idea is None."""
        signals_dir = signal_vault / "wiki" / "reports" / "signals"
        fm = (
            "---\n"
            "type: signal\n"
            "title: No Raw\n"
            "source: TestSource\n"
            "source_url: https://example.com\n"
            "relevance_score: 5\n"
            "threat_level: low\n"
            "status: pending\n"
            'signal_date: "2026-08-01"\n'
            'created: "2026-08-01T10:00:00"\n'
            "---\n"
            "\n"
            "## Анализ\n"
            "Some analysis.\n"
        )
        (signals_dir / "2026-08-01-no-raw.md").write_text(fm, encoding="utf-8")

        resp = signal_client.get("/api/v1/signals/2026-08-01-no-raw")
        assert resp.status_code == 200
        assert resp.json()["draft_idea"] is None

    def test_path_traversal_rejected(self, signal_client):
        """Path traversal in signal_id -> 400."""
        resp = signal_client.get("/api/v1/signals/..%2F..%2Fetc%2Fpasswd")
        assert resp.status_code in (400, 404)

    def test_backslash_rejected(self, signal_client):
        """Backslash in signal_id -> 400."""
        resp = signal_client.get("/api/v1/signals/test\\evil")
        assert resp.status_code == 400

    def test_response_includes_all_fields(self, signal_client, signal_vault):
        """Detail response should include analysis, recommended_action, draft_idea."""
        _create_signal_files(signal_vault, "2026-08-01-full-detail")

        resp = signal_client.get("/api/v1/signals/2026-08-01-full-detail")
        assert resp.status_code == 200
        data = resp.json()

        expected_keys = {
            "signal_id",
            "title",
            "source",
            "source_url",
            "relevance_score",
            "threat_level",
            "status",
            "signal_date",
            "analysis",
            "recommended_action",
            "draft_idea",
            "report_ref",
            "result_ref",
            "created",
        }
        assert expected_keys.issubset(data.keys())


# ---------------------------------------------------------------------------
# POST /api/v1/signals/{signal_id}/approve
# ---------------------------------------------------------------------------


def _mock_ke_signal_moderator():
    """Context manager that stubs knowledge_engine.app.signal_moderator in sys.modules.

    The approve endpoint does a lazy import:
        from knowledge_engine.app.signal_moderator import AnalysisResult, dispatch_idea
    Since knowledge_engine is not on PYTHONPATH in pm-bot tests, we need to
    pre-populate sys.modules with a mock before the endpoint runs.
    """
    mock_mod = MagicMock()
    mock_mod.dispatch_idea = MagicMock(return_value="/wiki/ideas/test.md")
    mock_mod.AnalysisResult = MagicMock()

    modules_to_stub = {
        "knowledge_engine": MagicMock(),
        "knowledge_engine.app": MagicMock(),
        "knowledge_engine.app.signal_moderator": mock_mod,
    }
    return patch.dict(sys.modules, modules_to_stub), mock_mod


class TestSignalApprove:
    """Tests for POST /api/v1/signals/{signal_id}/approve (BL-203, AC-06)."""

    def test_success(self, signal_client, signal_vault):
        """Pending signal with draft_idea -> approved, dispatch_idea called."""
        draft = {
            "title": "New Idea",
            "problem": "Problem desc",
            "solution": "Solution desc",
            "domain": "general",
        }
        _create_signal_files(
            signal_vault,
            "2026-08-01-approve-ok",
            status="pending",
            draft_idea=draft,
        )

        modules_patch, mock_mod = _mock_ke_signal_moderator()
        with modules_patch:
            resp = signal_client.post("/api/v1/signals/2026-08-01-approve-ok/approve")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["signal_id"] == "2026-08-01-approve-ok"
        assert data["new_status"] == "approved"
        assert "idea_ref" in data
        mock_mod.dispatch_idea.assert_called_once()

    def test_conflict_already_approved(self, signal_client, signal_vault):
        """Already approved signal -> 409."""
        _create_signal_files(
            signal_vault,
            "2026-08-01-already-approved",
            status="approved",
            draft_idea={"title": "X"},
        )

        resp = signal_client.post(
            "/api/v1/signals/2026-08-01-already-approved/approve"
        )
        assert resp.status_code == 409
        assert "approved" in resp.json()["detail"].lower()

    def test_conflict_dismissed(self, signal_client, signal_vault):
        """Dismissed signal -> 409."""
        _create_signal_files(
            signal_vault,
            "2026-08-01-was-dismissed",
            status="dismissed",
            draft_idea={"title": "X"},
        )

        resp = signal_client.post(
            "/api/v1/signals/2026-08-01-was-dismissed/approve"
        )
        assert resp.status_code == 409

    def test_no_draft_idea(self, signal_client, signal_vault):
        """Pending signal without draft_idea -> 400."""
        _create_signal_files(
            signal_vault,
            "2026-08-01-no-draft",
            status="pending",
            draft_idea=None,
        )

        resp = signal_client.post("/api/v1/signals/2026-08-01-no-draft/approve")
        assert resp.status_code == 400
        assert "draft_idea" in resp.json()["detail"].lower()

    def test_not_found(self, signal_client):
        """Non-existent signal -> 404."""
        resp = signal_client.post("/api/v1/signals/2026-08-01-ghost/approve")
        assert resp.status_code == 404

    def test_path_traversal(self, signal_client):
        """Path traversal attempt -> 400."""
        resp = signal_client.post("/api/v1/signals/..%2F..%2Fetc%2Fpasswd/approve")
        assert resp.status_code in (400, 404)

    def test_updates_frontmatter(self, signal_client, signal_vault):
        """After approve, wiki file frontmatter should have status=approved."""
        draft = {"title": "Idea", "problem": "P", "domain": "general"}
        _create_signal_files(
            signal_vault,
            "2026-08-01-approve-fm",
            status="pending",
            draft_idea=draft,
        )

        modules_patch, _mock_mod = _mock_ke_signal_moderator()
        with modules_patch:
            resp = signal_client.post("/api/v1/signals/2026-08-01-approve-fm/approve")

        assert resp.status_code == 200

        from shared.frontmatter_utils import read_frontmatter

        wiki_path = (
            signal_vault / "wiki" / "reports" / "signals" / "2026-08-01-approve-fm.md"
        )
        metadata, _ = read_frontmatter(wiki_path)
        assert metadata["status"] == "approved"


# ---------------------------------------------------------------------------
# POST /api/v1/signals/{signal_id}/dismiss
# ---------------------------------------------------------------------------


class TestSignalDismiss:
    """Tests for POST /api/v1/signals/{signal_id}/dismiss (BL-203, AC-07)."""

    def test_success(self, signal_client, signal_vault):
        """Pending signal -> dismissed."""
        _create_signal_files(
            signal_vault,
            "2026-08-01-dismiss-ok",
            status="pending",
        )

        resp = signal_client.post("/api/v1/signals/2026-08-01-dismiss-ok/dismiss")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["signal_id"] == "2026-08-01-dismiss-ok"
        assert data["new_status"] == "dismissed"

    def test_conflict_already_dismissed(self, signal_client, signal_vault):
        """Already dismissed -> 409."""
        _create_signal_files(
            signal_vault,
            "2026-08-01-dismiss-dup",
            status="dismissed",
        )

        resp = signal_client.post("/api/v1/signals/2026-08-01-dismiss-dup/dismiss")
        assert resp.status_code == 409

    def test_conflict_approved(self, signal_client, signal_vault):
        """Approved signal cannot be dismissed -> 409."""
        _create_signal_files(
            signal_vault,
            "2026-08-01-dismiss-approved",
            status="approved",
        )

        resp = signal_client.post(
            "/api/v1/signals/2026-08-01-dismiss-approved/dismiss"
        )
        assert resp.status_code == 409

    def test_not_found(self, signal_client):
        """Non-existent signal -> 404."""
        resp = signal_client.post("/api/v1/signals/2026-08-01-ghost/dismiss")
        assert resp.status_code == 404

    def test_path_traversal(self, signal_client):
        """Path traversal in signal_id -> 400."""
        resp = signal_client.post("/api/v1/signals/..%2F..%2Fetc%2Fpasswd/dismiss")
        assert resp.status_code in (400, 404)

    def test_updates_frontmatter(self, signal_client, signal_vault):
        """After dismiss, wiki file frontmatter should have status=dismissed."""
        _create_signal_files(
            signal_vault,
            "2026-08-01-dismiss-fm",
            status="pending",
        )

        resp = signal_client.post("/api/v1/signals/2026-08-01-dismiss-fm/dismiss")
        assert resp.status_code == 200

        from shared.frontmatter_utils import read_frontmatter

        wiki_path = (
            signal_vault
            / "wiki"
            / "reports"
            / "signals"
            / "2026-08-01-dismiss-fm.md"
        )
        metadata, _ = read_frontmatter(wiki_path)
        assert metadata["status"] == "dismissed"

    def test_signal_id_validation(self, signal_client):
        """Various invalid signal_id formats -> 400."""
        # Empty-ish
        resp = signal_client.post("/api/v1/signals//dismiss")
        assert resp.status_code in (307, 400, 404, 405)

        # Backslash
        resp = signal_client.post("/api/v1/signals/test\\evil/dismiss")
        assert resp.status_code == 400
