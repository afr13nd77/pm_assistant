"""Tests for file_writer module: file_lock, locked_append, append_section."""
import multiprocessing
import os
import sys
import pytest
from pathlib import Path
from unittest.mock import patch

from shared.file_writer import (
    atomic_write,
    append_section,
    file_lock,
    locked_append,
    FileLockTimeout,
)


# Module-level helpers for multiprocessing (must be picklable)
def _worker_locked_append(filepath_str, text):
    from shared.file_writer import locked_append
    locked_append(filepath_str, text)


def _worker_append_section(filepath_str, section_text):
    from shared.file_writer import append_section
    append_section(filepath_str, section_text)


class TestFileLock:
    def test_file_lock_context_manager_yields(self, tmp_path):
        target = tmp_path / "test.md"
        target.write_text("content", encoding="utf-8")
        with file_lock(target):
            assert True

    def test_file_lock_no_leftover_lock_file(self, tmp_path):
        target = tmp_path / "test.md"
        target.write_text("content", encoding="utf-8")
        lock_path = target.with_suffix(".md.lock")
        with file_lock(target):
            pass
        if os.name != "nt":
            assert not lock_path.exists()

    def test_file_lock_allows_operations_inside(self, tmp_path):
        target = tmp_path / "test.md"
        target.write_text("original", encoding="utf-8")
        with file_lock(target):
            target.write_text("modified", encoding="utf-8")
        assert target.read_text(encoding="utf-8") == "modified"

    @pytest.mark.skipif(sys.platform == "win32", reason="fcntl not available on Windows")
    def test_file_lock_timeout(self, tmp_path):
        import fcntl

        target = tmp_path / "test.md"
        target.write_text("content", encoding="utf-8")
        lock_path = target.with_suffix(".md.lock")

        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            with pytest.raises(FileLockTimeout):
                with file_lock(target, timeout=0.3):
                    pass
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)


class TestLockedAppend:
    def test_locked_append_creates_content(self, tmp_path):
        target = tmp_path / "test.md"
        target.write_text("line1\n", encoding="utf-8")
        locked_append(target, "line2")
        content = target.read_text(encoding="utf-8")
        assert content == "line1\nline2\n"

    def test_locked_append_adds_newline_if_missing(self, tmp_path):
        target = tmp_path / "test.md"
        target.write_text("", encoding="utf-8")
        locked_append(target, "no newline at end")
        content = target.read_text(encoding="utf-8")
        assert content.endswith("\n")

    def test_locked_append_preserves_existing_newline(self, tmp_path):
        target = tmp_path / "test.md"
        target.write_text("", encoding="utf-8")
        locked_append(target, "has newline\n")
        content = target.read_text(encoding="utf-8")
        assert content == "has newline\n"
        assert not content.endswith("\n\n")

    def test_locked_append_multiple_calls(self, tmp_path):
        target = tmp_path / "test.md"
        target.write_text("", encoding="utf-8")
        locked_append(target, "first")
        locked_append(target, "second")
        locked_append(target, "third")
        content = target.read_text(encoding="utf-8")
        assert "first\n" in content
        assert "second\n" in content
        assert "third\n" in content


class TestAppendSectionWithLock:
    def test_append_section_adds_new_section(self, tmp_path):
        target = tmp_path / "test.md"
        target.write_text("# Title\n\nSome content\n", encoding="utf-8")
        append_section(target, "## New Section\n\nNew content here")
        content = target.read_text(encoding="utf-8")
        assert "## New Section" in content
        assert "New content here" in content

    def test_append_section_replaces_existing(self, tmp_path):
        target = tmp_path / "test.md"
        target.write_text("# Title\n\n## Existing\n\nOld content\n", encoding="utf-8")
        append_section(target, "## Existing\n\nUpdated content")
        content = target.read_text(encoding="utf-8")
        assert "Updated content" in content
        assert "Old content" not in content

    def test_append_section_inserts_before_footer(self, tmp_path):
        target = tmp_path / "test.md"
        target.write_text(
            "# Title\n\nBody\n\n---\n*Источник: test*\n",
            encoding="utf-8",
        )
        append_section(target, "## Added\n\nExtra")
        content = target.read_text(encoding="utf-8")
        footer_pos = content.find("---\n*Источник:")
        section_pos = content.find("## Added")
        assert section_pos < footer_pos


class TestAtomicWrite:
    def test_atomic_write_creates_file(self, tmp_path):
        target = tmp_path / "new.md"
        atomic_write(target, "hello world")
        assert target.read_text(encoding="utf-8") == "hello world"

    def test_atomic_write_overwrites_existing(self, tmp_path):
        target = tmp_path / "existing.md"
        target.write_text("old", encoding="utf-8")
        atomic_write(target, "new")
        assert target.read_text(encoding="utf-8") == "new"

    def test_atomic_write_creates_parent_dirs(self, tmp_path):
        target = tmp_path / "sub" / "dir" / "file.md"
        atomic_write(target, "nested")
        assert target.read_text(encoding="utf-8") == "nested"

    def test_atomic_write_no_tmp_on_success(self, tmp_path):
        target = tmp_path / "clean.md"
        atomic_write(target, "content")
        tmp_file = target.with_suffix(".tmp")
        assert not tmp_file.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="fcntl not available on Windows")
class TestConcurrentFileLock:
    def test_concurrent_locked_append(self, tmp_path):
        target = tmp_path / "concurrent.md"
        target.write_text("", encoding="utf-8")

        processes = []
        for i in range(10):
            p = multiprocessing.Process(
                target=_worker_locked_append,
                args=(str(target), f"line-{i}"),
            )
            processes.append(p)

        for p in processes:
            p.start()
        for p in processes:
            p.join(timeout=10)

        content = target.read_text(encoding="utf-8")
        for i in range(10):
            assert f"line-{i}" in content, f"line-{i} missing from file"

    def test_concurrent_append_section(self, tmp_path):
        target = tmp_path / "sections.md"
        target.write_text("# Title\n\nContent\n", encoding="utf-8")

        processes = []
        for i in range(5):
            p = multiprocessing.Process(
                target=_worker_append_section,
                args=(str(target), f"## Section {i}\n\nBody {i}"),
            )
            processes.append(p)

        for p in processes:
            p.start()
        for p in processes:
            p.join(timeout=10)

        content = target.read_text(encoding="utf-8")
        for i in range(5):
            assert f"Body {i}" in content, f"Body {i} missing from file"
