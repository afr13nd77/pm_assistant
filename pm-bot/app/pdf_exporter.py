import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_MAX_INPUT_LENGTH = 1_000_000


def _strip_frontmatter(text: str) -> str:
    """Remove YAML frontmatter (---...---) from the beginning of the text."""
    logger.debug(f"_strip_frontmatter: start, input_length={len(text)}")
    result = re.sub(r'^---\n.*?\n---\n', '', text, count=1, flags=re.DOTALL)
    logger.debug(f"_strip_frontmatter: done, output_length={len(result)}")
    return result


def _replace_wikilinks(text: str) -> str:
    """Convert [[some text]] wikilinks to plain text."""
    logger.debug("_replace_wikilinks: start")
    result = re.sub(r'\[\[([^\]]+)\]\]', r'\1', text)
    logger.debug("_replace_wikilinks: done")
    return result


def _safe_url_fetcher(url, timeout=10, ssl_context=None):
    """URL fetcher that blocks external URLs for security."""
    logger.debug(f"_safe_url_fetcher: url={url}")
    if url.startswith('file://') or url.startswith('data:'):
        from weasyprint import default_url_fetcher
        return default_url_fetcher(url, timeout=timeout, ssl_context=ssl_context)
    logger.error(f"_safe_url_fetcher: external URL blocked — {url}")
    raise ValueError(f"External URL blocked: {url}")


def _build_html(body_html: str, css_path: Path) -> str:
    """Wrap rendered HTML body in a full HTML document with CSS."""
    logger.debug(f"_build_html: start, css_path={css_path}")
    try:
        css_content = css_path.read_text(encoding="utf-8")
        logger.debug(f"_build_html: CSS loaded, length={len(css_content)}")
    except Exception as exc:
        logger.error(f"_build_html: failed to read CSS — {exc}")
        raise

    html_doc = (
        "<!DOCTYPE html>\n"
        "<html>\n"
        "<head>\n"
        '<meta charset="utf-8">\n'
        "<style>\n"
        f"{css_content}\n"
        "</style>\n"
        "</head>\n"
        "<body>\n"
        f"{body_html}\n"
        "</body>\n"
        "</html>"
    )
    logger.debug(f"_build_html: done, html_length={len(html_doc)}")
    return html_doc


def render_pdf(markdown_text: str, css_path: Path) -> bytes:
    """Convert markdown text to PDF bytes.

    Args:
        markdown_text: Raw markdown content (may include YAML frontmatter and wikilinks).
        css_path: Path to the CSS file for styling the PDF.

    Returns:
        PDF content as bytes.

    Raises:
        ValueError: If the input exceeds 1MB size limit.
    """
    logger.info(f"render_pdf: start, input_length={len(markdown_text)}")

    if len(markdown_text) > _MAX_INPUT_LENGTH:
        logger.error(f"render_pdf: input too large — {len(markdown_text)} bytes (limit {_MAX_INPUT_LENGTH})")
        raise ValueError("Report too large for PDF export")

    try:
        from markdown_it import MarkdownIt
        from weasyprint import HTML

        # Clean up markdown
        cleaned = _strip_frontmatter(markdown_text)
        cleaned = _replace_wikilinks(cleaned)

        # Render markdown to HTML
        logger.debug("render_pdf: rendering markdown to HTML")
        md = MarkdownIt("gfm-like", {"linkify": False})
        html_body = md.render(cleaned)

        # Build full HTML document
        html_doc = _build_html(html_body, css_path)

        # Render HTML to PDF
        logger.debug("render_pdf: rendering HTML to PDF")
        pdf_bytes = HTML(string=html_doc, url_fetcher=_safe_url_fetcher).write_pdf()

        logger.info(f"render_pdf: done, pdf_size={len(pdf_bytes)} bytes")
        return pdf_bytes

    except ValueError:
        raise
    except Exception as exc:
        logger.error(f"render_pdf: failed — {exc}")
        raise
