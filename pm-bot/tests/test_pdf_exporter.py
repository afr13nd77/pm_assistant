"""Unit tests for pdf_exporter.py: _build_html (fontconfig-based, no @font-face)."""

from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# _build_html (simplified — relies on fontconfig, no @font-face embedding)
# ---------------------------------------------------------------------------

class TestBuildHtml:
    """Tests that _build_html properly wraps body HTML with CSS."""

    def test_build_html_includes_css_and_body(self, tmp_path):
        """_build_html output includes CSS content and body HTML."""
        from app.pdf_exporter import _build_html

        css_file = tmp_path / "test.css"
        css_file.write_text("body { color: black; }", encoding="utf-8")

        result = _build_html("<p>Hello</p>", css_file)

        assert "body { color: black; }" in result
        assert "<p>Hello</p>" in result
        assert "<!DOCTYPE html>" in result
        assert '<meta charset="utf-8">' in result

    def test_build_html_no_font_face_rules(self, tmp_path):
        """_build_html should NOT contain @font-face rules (fontconfig handles fonts)."""
        from app.pdf_exporter import _build_html

        css_file = tmp_path / "test.css"
        css_file.write_text("body { margin: 0; }", encoding="utf-8")

        result = _build_html("<p>Test</p>", css_file)

        assert "@font-face" not in result
        assert "base64" not in result

    def test_build_html_css_read_error(self, tmp_path):
        """_build_html raises when CSS file cannot be read."""
        from app.pdf_exporter import _build_html

        missing_css = tmp_path / "nonexistent.css"

        with pytest.raises(Exception):
            _build_html("<p>Test</p>", missing_css)

    def test_build_html_signature_unchanged(self):
        """Verify _build_html still accepts (body_html, css_path) signature."""
        import inspect

        from app.pdf_exporter import _build_html

        sig = inspect.signature(_build_html)
        params = list(sig.parameters.keys())
        assert params == ["body_html", "css_path"]

    def test_build_html_structure(self, tmp_path):
        """Verify the HTML document has correct structure."""
        from app.pdf_exporter import _build_html

        css_file = tmp_path / "test.css"
        css_file.write_text("h1 { font-size: 2em; }", encoding="utf-8")

        result = _build_html("<h1>Title</h1>", css_file)

        # Check overall structure
        assert result.startswith("<!DOCTYPE html>")
        assert "<html>" in result
        assert "</html>" in result
        assert "<head>" in result
        assert "</head>" in result
        assert "<body>" in result
        assert "</body>" in result
        assert "<style>" in result
        assert "</style>" in result

        # CSS is inside <style>
        style_start = result.index("<style>")
        style_end = result.index("</style>")
        style_content = result[style_start:style_end]
        assert "h1 { font-size: 2em; }" in style_content

        # Body content is inside <body>
        body_start = result.index("<body>")
        body_end = result.index("</body>")
        body_content = result[body_start:body_end]
        assert "<h1>Title</h1>" in body_content


# ---------------------------------------------------------------------------
# Module-level checks — no removed exports leak
# ---------------------------------------------------------------------------

class TestModuleExports:
    """Verify removed base64/font-face artifacts are gone from the module."""

    def test_no_font_configs(self):
        """_FONT_CONFIGS should no longer exist in the module."""
        import app.pdf_exporter as mod
        assert not hasattr(mod, "_FONT_CONFIGS")

    def test_no_load_font_faces(self):
        """_load_font_faces should no longer exist in the module."""
        import app.pdf_exporter as mod
        assert not hasattr(mod, "_load_font_faces")

    def test_no_base64_import(self):
        """The module should not import base64 anymore."""
        import app.pdf_exporter as mod
        source = Path(mod.__file__).read_text(encoding="utf-8")
        assert "import base64" not in source
