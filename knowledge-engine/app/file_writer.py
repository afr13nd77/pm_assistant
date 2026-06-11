import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)


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


def append_section(filepath: str | Path, section_text: str) -> None:
    filepath = Path(filepath)
    logger.info(f"Appending section to: {filepath.name}")
    try:
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
