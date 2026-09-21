"""Signals router: Signal Moderator proxy + Signal Triage endpoints (BL-201, BL-203)."""

import json
import logging
import re

import requests
from fastapi import APIRouter, HTTPException, Query

from shared import vault_paths
from shared.frontmatter_utils import read_frontmatter, update_frontmatter
from shared.vault_paths import VAULT_PATH

from .. import ke_client
from ..vault_cache import _cache

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["Signals"])


# ---------------------------------------------------------------------------
# Signal Moderator proxy  (BL-201)
# ---------------------------------------------------------------------------

@router.get("/api/v1/signals/runs")
def signal_runs_proxy(limit: int = Query(default=10, ge=1, le=100)):
    """Proxy: list signal moderator runs from KE."""
    logger.info("GET /api/v1/signals/runs -- start, limit=%s", limit)
    try:
        data = ke_client.signal_runs(limit)
        logger.info(
            "GET /api/v1/signals/runs -- success, count=%s",
            len(data.get("runs", [])),
        )
        return data
    except requests.RequestException as exc:
        logger.error("GET /api/v1/signals/runs -- KE error: %s", exc)
        raise HTTPException(status_code=502, detail=f"KE API error: {exc}")
    except Exception as exc:
        logger.error(
            "GET /api/v1/signals/runs -- error: %s", exc, exc_info=True
        )
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/v1/signals/runs/{run_id}")
def signal_run_detail_proxy(run_id: str):
    """Proxy: get signal run detail from KE."""
    logger.info("GET /api/v1/signals/runs/%s -- start", run_id)
    try:
        data = ke_client.signal_run_detail(run_id)
        logger.info(
            "GET /api/v1/signals/runs/%s -- success, items=%s",
            run_id,
            len(data.get("items", {})),
        )
        return data
    except requests.RequestException as exc:
        logger.error("GET /api/v1/signals/runs/%s -- KE error: %s", run_id, exc)
        raise HTTPException(status_code=502, detail=f"KE API error: {exc}")
    except Exception as exc:
        logger.error(
            "GET /api/v1/signals/runs/%s -- error: %s", run_id, exc, exc_info=True
        )
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Signal Triage: list / detail / approve / dismiss (BL-203)
# ---------------------------------------------------------------------------


def _validate_signal_id(signal_id: str) -> bool:
    """Validate signal_id format: YYYY-MM-DD-slug, no path traversal."""
    logger.info(f"_validate_signal_id: validating '{signal_id}'")
    if not signal_id or ".." in signal_id or "/" in signal_id or "\\" in signal_id:
        logger.warning(f"_validate_signal_id: invalid signal_id '{signal_id}'")
        return False
    if len(signal_id) > 100:
        logger.warning(f"_validate_signal_id: signal_id too long ({len(signal_id)})")
        return False
    return True


@router.get("/api/v1/signals/list")
async def signals_list(
    status: str | None = None,
    date: str | None = None,
    limit: int = 50,
):
    """List Signal artifacts with optional filters (BL-203)."""
    logger.info(f"GET /api/v1/signals/list -- status={status}, date={date}, limit={limit}")
    try:
        signals_dir = vault_paths.wiki_signals()
        signals = []

        if not signals_dir.exists():
            logger.info("signals_list: signals directory does not exist")
            return {"signals": [], "total": 0}

        for md_file in sorted(signals_dir.glob("*.md"), reverse=True):
            # Skip report files (they have -report.md suffix)
            if md_file.name.endswith("-report.md"):
                continue

            try:
                fm, _body = read_frontmatter(md_file)
                if not fm or fm.get("type") != "signal":
                    continue

                # Apply filters
                if status and fm.get("status") != status:
                    continue
                if date and fm.get("signal_date") != date:
                    continue

                signal_id = md_file.stem
                signals.append({
                    "signal_id": signal_id,
                    "title": fm.get("title", ""),
                    "source": fm.get("source", ""),
                    "source_url": fm.get("source_url", ""),
                    "relevance_score": fm.get("relevance_score", 0),
                    "threat_level": fm.get("threat_level", "low"),
                    "status": fm.get("status", "pending"),
                    "signal_date": fm.get("signal_date", ""),
                    "has_draft_idea": False,  # Will check raw JSON below
                    "report_ref": fm.get("report_ref", ""),
                    "result_ref": fm.get("result_ref", ""),
                    "created": fm.get("created", ""),
                })
            except Exception as e:
                logger.warning(f"signals_list: error reading {md_file.name}: {e}")
                continue

        # Check has_draft_idea from raw JSON
        raw_dir = vault_paths.raw_signals()
        for s in signals:
            raw_path = raw_dir / f"{s['signal_id']}.json"
            if raw_path.exists():
                try:
                    raw_data = json.loads(raw_path.read_text(encoding="utf-8"))
                    s["has_draft_idea"] = raw_data.get("draft_idea") is not None
                except Exception:
                    pass

        # Apply limit
        signals = signals[:limit]

        logger.info(f"signals_list: returning {len(signals)} signals")
        return {"signals": signals, "total": len(signals)}

    except Exception as exc:
        logger.error(f"GET /api/v1/signals/list -- error: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/v1/signals/{signal_id}")
async def signal_detail(signal_id: str):
    """Get Signal details by ID (BL-203)."""
    logger.info(f"GET /api/v1/signals/{signal_id}")

    if not _validate_signal_id(signal_id):
        raise HTTPException(status_code=400, detail=f"Invalid signal_id: {signal_id}")

    try:
        wiki_path = vault_paths.wiki_signals() / f"{signal_id}.md"
        if not wiki_path.exists():
            logger.warning(f"signal_detail: not found: {wiki_path}")
            raise HTTPException(status_code=404, detail=f"Signal not found: {signal_id}")

        fm, _body = read_frontmatter(wiki_path)
        body = wiki_path.read_text(encoding="utf-8")

        # Parse body sections
        analysis = ""
        recommended_action = ""
        analysis_match = re.search(r"## Анализ\s*\n(.*?)(?=\n## |\Z)", body, re.DOTALL)
        if analysis_match:
            analysis = analysis_match.group(1).strip()
        rec_match = re.search(r"## Рекомендация\s*\n(.*?)(?=\n## |\Z)", body, re.DOTALL)
        if rec_match:
            recommended_action = rec_match.group(1).strip()

        # Read draft_idea, news_title, news_summary from raw JSON
        draft_idea = None
        news_title = ""
        news_summary = ""
        raw_path = vault_paths.raw_signals() / f"{signal_id}.json"
        if raw_path.exists():
            try:
                raw_data = json.loads(raw_path.read_text(encoding="utf-8"))
                draft_idea = raw_data.get("draft_idea")
                news_title = raw_data.get("original_title", "") or raw_data.get("title", "")
                news_summary = raw_data.get("original_summary", "") or raw_data.get("summary", "")
            except Exception as e:
                logger.warning(f"signal_detail: failed to read raw JSON: {e}")

        # Fallback: look up original news in digest files by source_url
        if not news_summary:
            src_url = fm.get("source_url", "")
            if src_url:
                news_dir = VAULT_PATH / "raw" / "inbound" / "news"
                if news_dir.exists():
                    for digest_file in sorted(news_dir.glob("*-digest.json"), reverse=True):
                        try:
                            digest_data = json.loads(digest_file.read_text(encoding="utf-8"))
                            for di_item in digest_data.get("items", []):
                                if di_item.get("source_url") == src_url:
                                    news_title = news_title or di_item.get("title", "")
                                    news_summary = di_item.get("summary", "")
                                    logger.info(f"signal_detail: found news in digest {digest_file.name}")
                                    break
                            if news_summary:
                                break
                        except Exception as e:
                            logger.warning(f"signal_detail: failed to read digest {digest_file.name}: {e}")

        # Load report content if report_ref exists
        report_content = ""
        report_ref = fm.get("report_ref", "")
        if report_ref:
            report_path = vault_paths.wiki_signals() / report_ref
            if report_path.exists():
                try:
                    report_text = report_path.read_text(encoding="utf-8")
                    # Strip frontmatter
                    fm_end = report_text.find("---", report_text.find("---") + 3)
                    if fm_end != -1:
                        report_content = report_text[fm_end + 3:].strip()
                    else:
                        report_content = report_text.strip()
                    logger.info(f"signal_detail: loaded report content from {report_ref}, len={len(report_content)}")
                except Exception as e:
                    logger.warning(f"signal_detail: failed to read report {report_ref}: {e}")
            else:
                logger.warning(f"signal_detail: report_ref file not found: {report_path}")

        result = {
            "signal_id": signal_id,
            "title": fm.get("title", ""),
            "source": fm.get("source", ""),
            "source_url": fm.get("source_url", ""),
            "relevance_score": fm.get("relevance_score", 0),
            "threat_level": fm.get("threat_level", "low"),
            "status": fm.get("status", "pending"),
            "signal_date": fm.get("signal_date", ""),
            "analysis": analysis,
            "recommended_action": recommended_action,
            "draft_idea": draft_idea,
            "report_ref": fm.get("report_ref", ""),
            "report_content": report_content,
            "news_title": news_title,
            "news_summary": news_summary,
            "result_ref": fm.get("result_ref", ""),
            "created": fm.get("created", ""),
        }

        logger.info(f"signal_detail: returning details for {signal_id}")
        return result

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"GET /api/v1/signals/{signal_id} -- error: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/api/v1/signals/{signal_id}/approve")
async def signal_approve(signal_id: str):
    """Proxy: approve a pending signal via KE (BL-203, BUG-033)."""
    logger.info(f"POST /api/v1/signals/{signal_id}/approve")

    if not _validate_signal_id(signal_id):
        raise HTTPException(status_code=400, detail=f"Invalid signal_id: {signal_id}")

    try:
        data = ke_client.signal_approve(signal_id)
        _cache.invalidate()
        logger.info(
            f"POST /api/v1/signals/{signal_id}/approve -- success, "
            f"idea_ref={data.get('idea_ref')}"
        )
        return data
    except requests.exceptions.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else 502
        detail = str(exc)
        try:
            if exc.response is not None:
                detail = exc.response.json().get("detail", detail)
        except Exception:
            pass
        logger.error(
            f"POST /api/v1/signals/{signal_id}/approve -- KE HTTP {status}: {detail}"
        )
        raise HTTPException(status_code=status, detail=detail)
    except requests.RequestException as exc:
        logger.error(
            f"POST /api/v1/signals/{signal_id}/approve -- KE error: {exc}"
        )
        raise HTTPException(status_code=502, detail=f"KE API error: {exc}")
    except Exception as exc:
        logger.error(
            f"POST /api/v1/signals/{signal_id}/approve -- error: {exc}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/api/v1/signals/{signal_id}/dismiss")
async def signal_dismiss(signal_id: str):
    """Dismiss a pending signal (BL-203, AC-07)."""
    logger.info(f"POST /api/v1/signals/{signal_id}/dismiss")

    if not _validate_signal_id(signal_id):
        raise HTTPException(status_code=400, detail=f"Invalid signal_id: {signal_id}")

    try:
        wiki_path = vault_paths.wiki_signals() / f"{signal_id}.md"
        if not wiki_path.exists():
            raise HTTPException(status_code=404, detail=f"Signal not found: {signal_id}")

        fm, _body = read_frontmatter(wiki_path)
        current_status = fm.get("status", "")
        if current_status != "pending":
            raise HTTPException(
                status_code=409,
                detail=f"Signal status is '{current_status}', expected 'pending'"
            )

        # Update wiki frontmatter only (raw JSON is immutable — C-0002)
        update_frontmatter(wiki_path, {"status": "dismissed"})

        _cache.invalidate()
        logger.info(f"signal_dismiss: dismissed {signal_id}")

        return {
            "status": "ok",
            "signal_id": signal_id,
            "new_status": "dismissed",
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            f"POST /api/v1/signals/{signal_id}/dismiss -- error: {exc}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail=str(exc))
