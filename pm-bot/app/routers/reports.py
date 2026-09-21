"""Reports: список/чтение отчётов из wiki/reports/, экспорт в PDF, регенерация."""

import logging
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from shared.vault_paths import wiki_reports

from ..vault_cache import _cache
from ..vault_scanner import _is_service_file

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["Reports"])


# ---------------------------------------------------------------------------
# Reports helpers
# ---------------------------------------------------------------------------

def _extract_report_title(text: str) -> str | None:
    """Extract the first markdown heading from text after stripping frontmatter.

    Returns the heading text (without the ``# `` prefix), or None if no
    heading is found.
    """
    body = text
    stripped = text.lstrip()
    if stripped.startswith("---"):
        end = stripped.find("---", 3)
        if end != -1:
            body = stripped[end + 3:].lstrip("\n")

    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return None


def _extract_report_type(text: str) -> str:
    """Extract ``type`` from YAML frontmatter, defaulting to ``other``."""
    stripped = text.lstrip()
    if not stripped.startswith("---"):
        return "other"

    end = stripped.find("---", 3)
    if end == -1:
        return "other"

    frontmatter = stripped[3:end]
    for line in frontmatter.splitlines():
        if line.strip().startswith("type:"):
            value = line.split(":", 1)[1].strip().strip("'\"")
            if value:
                logger.debug(f"_extract_report_type — found type: {value}")
                return value

    return "other"


_DATE_IN_FILENAME_RE = re.compile(r"(\d{4})[.\-](\d{2})[.\-](\d{2})")


def _extract_report_date(text: str, stem: str, path: Path | None = None) -> str:
    """Extract report date. Priority: frontmatter ``date:``/``created:`` → filename."""
    stripped = text.lstrip()
    if stripped.startswith("---"):
        end = stripped.find("---", 3)
        if end != -1:
            for field in ("date:", "created:"):
                for line in stripped[3:end].splitlines():
                    if line.strip().startswith(field):
                        val = line.split(":", 1)[1].strip().strip("'\"")
                        fm = _DATE_IN_FILENAME_RE.search(val)
                        if fm:
                            date_str = f"{fm.group(1)}-{fm.group(2)}-{fm.group(3)}"
                            logger.debug(f"_extract_report_date — frontmatter {field} {date_str} for '{stem}'")
                            return date_str

    m = _DATE_IN_FILENAME_RE.search(stem)
    if m:
        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= month <= 12 and 1 <= day <= 31:
            date_str = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
            logger.debug(f"_extract_report_date — filename date {date_str} for '{stem}'")
            return date_str
        logger.debug(f"_extract_report_date — invalid filename date {year}-{month}-{day} in '{stem}'")

    logger.debug(f"_extract_report_date — no date found for '{stem}'")
    return "0000-00-00"


# ---------------------------------------------------------------------------
# Reports endpoints
# ---------------------------------------------------------------------------

@router.get("/api/v1/reports")
def list_reports(type: str | None = None):
    """Return a list of all available reports from wiki/reports/.

    Each entry contains ``filename``, ``date`` (extracted from frontmatter or
    filename), and ``title`` (first ``# `` heading in the file body, or
    the filename stem when no heading is found).

    Reports are sorted by date descending (newest first).
    Service files (index.md, log.md) are excluded.

    Optional query parameter ``type`` filters by comma-separated report types,
    e.g. ``?type=weekly-status-report,feature-analysis-report``.
    """
    type_filter = {t.strip() for t in type.split(",")} if type else None
    logger.info(f"GET /api/v1/reports — start (type_filter={type_filter})")
    folder = wiki_reports()

    if not folder.exists():
        logger.info(
            "GET /api/v1/reports — reports folder not found, returning empty list"
        )
        return {"reports": []}

    try:
        files = [f for f in folder.glob("*.md") if not _is_service_file(f)]
        signals_dir = folder / "signals"
        if signals_dir.exists():
            files.extend(f for f in signals_dir.glob("*.md") if not _is_service_file(f))
        logger.info(f"GET /api/v1/reports — found {len(files)} files total")
    except Exception as exc:
        logger.error(f"GET /api/v1/reports — error listing files: {exc}")
        return {"reports": []}

    results: list[dict] = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
            report_type = _extract_report_type(text)
            if type_filter and report_type not in type_filter:
                continue
            date = _extract_report_date(text, f.stem, f)
            title = _extract_report_title(text) or f.stem
            results.append(
                {"filename": f.name, "date": date, "title": title, "type": report_type}
            )
            logger.info(
                f"GET /api/v1/reports — parsed {f.name} (date={date}, title={title}, type={report_type})"
            )
        except Exception as exc:
            logger.error(
                f"GET /api/v1/reports — failed to parse {f.name}: {exc}"
            )
            continue

    results.sort(key=lambda r: r["date"], reverse=True)
    logger.info(f"GET /api/v1/reports — returning {len(results)} reports (sorted by date)")
    return {"reports": results}


@router.get("/api/v1/reports/{filename}")
def get_report_by_filename(filename: str):
    """Return the full content of a specific report file.

    ``filename`` must end with ``.md`` and must not contain path separators
    (security check).  Returns 404 when the file does not exist.
    """
    logger.info("GET /api/v1/reports/%s — start", filename)

    # --- Security validation ---
    if not filename.endswith(".md"):
        logger.error(
            "GET /api/v1/reports/%s — rejected: filename does not end with .md",
            filename,
        )
        raise HTTPException(
            status_code=400,
            detail="Filename must end with .md",
        )

    if "/" in filename or "\\" in filename:
        logger.error(
            "GET /api/v1/reports/%s — rejected: path separators in filename",
            filename,
        )
        raise HTTPException(
            status_code=400,
            detail="Filename must not contain path separators",
        )

    folder = wiki_reports()
    filepath = folder / filename

    if not filepath.exists():
        filepath = folder / "signals" / filename
    if not filepath.exists():
        logger.info(
            "GET /api/v1/reports/%s — file not found", filename
        )
        raise HTTPException(status_code=404, detail="Report not found")

    try:
        content = filepath.read_text(encoding="utf-8")
        date = filepath.stem[:10] if len(filepath.stem) >= 10 else filepath.stem
        logger.info(
            "GET /api/v1/reports/%s — returning report (%d chars)",
            filename, len(content),
        )
        return {"filename": filename, "content": content, "date": date}
    except Exception as exc:
        logger.error(
            "GET /api/v1/reports/%s — failed to read file: %s",
            filename, exc,
        )
        raise HTTPException(status_code=500, detail="Failed to read report")


@router.post("/api/v1/reports/{filename}/pdf")
def export_report_pdf(filename: str):
    """Export a report as PDF.

    Reads the markdown report, renders it to PDF via WeasyPrint,
    and returns the PDF file as a downloadable attachment.
    """
    logger.info("POST /api/v1/reports/%s/pdf — start", filename)

    if not filename.endswith(".md"):
        raise HTTPException(status_code=400, detail="Filename must end with .md")
    if "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Filename must not contain path separators")

    folder = wiki_reports()
    filepath = folder / filename

    if not filepath.exists():
        logger.error("POST /api/v1/reports/%s/pdf — file not found", filename)
        raise HTTPException(status_code=404, detail="Report not found")

    try:
        from shared.system_log import LoggedProcess

        content = filepath.read_text(encoding="utf-8")

        with LoggedProcess(process_type="pdf-export", source="pm-bot") as lp:
            from pathlib import Path as _Path

            from app.pdf_exporter import render_pdf

            pdf_bytes = render_pdf(content, _Path("/web/pdf-export.css"))
            lp.summary = f"PDF exported: {filename}"
            lp.details = {"filename": filename, "size_bytes": len(pdf_bytes)}

        pdf_name = filename.rsplit(".", 1)[0] + ".pdf"
        logger.info("POST /api/v1/reports/%s/pdf — done, size=%d", filename, len(pdf_bytes))

        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{pdf_name}"'},
        )
    except ImportError as exc:
        logger.error("POST /api/v1/reports/%s/pdf — WeasyPrint not installed: %s", filename, exc)
        raise HTTPException(status_code=500, detail="PDF export unavailable: WeasyPrint not installed")
    except ValueError as exc:
        logger.error("POST /api/v1/reports/%s/pdf — validation error: %s", filename, exc)
        raise HTTPException(status_code=413, detail=str(exc))
    except Exception as exc:
        logger.error("POST /api/v1/reports/%s/pdf — error: %s", filename, exc)
        raise HTTPException(status_code=500, detail="PDF export failed")


# ---------------------------------------------------------------------------
# Report regeneration
# ---------------------------------------------------------------------------

@router.post("/api/v1/report/regenerate")
def regenerate_report():
    """Regenerate the weekly report."""
    logger.info("POST /api/v1/report/regenerate — start")
    try:
        from app.obsidian_writer import write_report
        from app.reporter import generate_weekly_report

        logger.info(
            "POST /api/v1/report/regenerate — calling generate_weekly_report"
        )
        report_md = generate_weekly_report()
        logger.info(
            "POST /api/v1/report/regenerate — generated %d chars", len(report_md)
        )

        logger.info("POST /api/v1/report/regenerate — calling write_report")
        filepath = write_report(report_md)
        _cache.invalidate()
        logger.info(
            "POST /api/v1/report/regenerate — saved to %s", filepath.name
        )

        return {"filename": filepath.name, "content": report_md}
    except Exception as exc:
        logger.error(
            "POST /api/v1/report/regenerate — error: %s", exc, exc_info=True
        )
        raise HTTPException(status_code=500, detail=str(exc))
