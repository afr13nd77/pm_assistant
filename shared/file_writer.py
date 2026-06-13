import logging
import os
import re
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)


class FileLockTimeout(Exception):
    pass


try:
    import fcntl

    @contextmanager
    def file_lock(filepath: str | Path, timeout: float = 5.0) -> Iterator[None]:
        """Acquire an exclusive file lock using a .lock sidecar file."""
        lock_path = Path(filepath).with_suffix(Path(filepath).suffix + ".lock")
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
        logger.debug(f"Acquiring file lock: {lock_path}")
        deadline = time.monotonic() + timeout
        try:
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except (OSError, BlockingIOError):
                    if time.monotonic() >= deadline:
                        logger.error(f"File lock timeout after {timeout}s: {lock_path}")
                        raise FileLockTimeout(f"Could not acquire lock on {filepath} within {timeout}s")
                    time.sleep(0.1)
            logger.debug(f"File lock acquired: {lock_path}")
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
            try:
                lock_path.unlink()
            except OSError:
                pass
            logger.debug(f"File lock released: {lock_path}")

except ImportError:

    @contextmanager
    def file_lock(filepath: str | Path, timeout: float = 5.0) -> Iterator[None]:
        """No-op file lock fallback for platforms without fcntl (Windows)."""
        logger.warning(f"File locking not available on this platform, proceeding without lock: {filepath}")
        yield


def atomic_write(filepath: str | Path, content: str) -> None:
    filepath = Path(filepath)
    tmp_path = filepath.with_suffix(".tmp")
    logger.info(f"Atomic write: {filepath.name}")
    try:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        tmp_path.write_text(content, encoding="utf-8")
        os.replace(str(tmp_path), str(filepath))
        logger.info(f"Atomic write OK: {filepath.name}")
    except Exception as e:
        logger.error(f"Atomic write failed for {filepath.name}: {e}")
        if tmp_path.exists():
            tmp_path.unlink()
        raise


def locked_append(filepath: str | Path, text: str) -> None:
    """Append text to a file under an exclusive file lock."""
    filepath = Path(filepath)
    logger.info(f"Locked append to: {filepath.name}")
    with file_lock(filepath):
        with open(filepath, "a", encoding="utf-8") as f:
            if text and not text.endswith("\n"):
                text = text + "\n"
            f.write(text)
    logger.info(f"Locked append OK: {filepath.name}")


def append_section(filepath: str | Path, section_text: str) -> None:
    filepath = Path(filepath)
    logger.info(f"Appending section to: {filepath.name}")
    try:
        with file_lock(filepath):
            original = filepath.read_text(encoding="utf-8")

            section_header = section_text.strip().split("\n", 1)[0].strip()
            existing_pattern = re.compile(
                re.escape(section_header) + r".*?(?=\n## |\n---\s*\n\*Источник:|\Z)",
                re.DOTALL,
            )
            if section_header.startswith("## ") and existing_pattern.search(original):
                logger.info(f"Replacing existing section '{section_header}' in {filepath.name}")
                new_content = existing_pattern.sub(section_text.strip(), original, count=1)
            else:
                footer_pattern = re.compile(r"\n---\s*\n\*Источник:.*\*\s*$", re.DOTALL)
                match = footer_pattern.search(original)

                if match:
                    insert_pos = match.start()
                    new_content = original[:insert_pos] + "\n\n" + section_text.strip() + "\n" + original[insert_pos:]
                else:
                    new_content = original.rstrip() + "\n\n" + section_text.strip() + "\n"

            atomic_write(filepath, new_content)
        logger.info(f"Section appended OK: {filepath.name}")
    except Exception as e:
        logger.error(f"Failed to append section to {filepath.name}: {e}")
        raise
