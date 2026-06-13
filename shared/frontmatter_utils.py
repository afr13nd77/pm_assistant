import logging
from pathlib import Path

import frontmatter

logger = logging.getLogger(__name__)


def read_frontmatter(filepath: str | Path) -> tuple[dict, str]:
    filepath = Path(filepath)
    logger.info(f"Reading frontmatter: {filepath.name}")
    try:
        post = frontmatter.load(str(filepath), encoding="utf-8")
        metadata = dict(post.metadata)
        body = post.content
        logger.info(f"Frontmatter read OK: {filepath.name}, keys={list(metadata.keys())}")
        return metadata, body
    except Exception as e:
        logger.error(f"Failed to read frontmatter from {filepath.name}: {e}")
        raise


def update_frontmatter(filepath: str | Path, updates: dict) -> None:
    filepath = Path(filepath)
    logger.info(f"Updating frontmatter: {filepath.name}, updates={list(updates.keys())}")
    try:
        post = frontmatter.load(str(filepath), encoding="utf-8")
        for key, value in updates.items():
            post[key] = value

        tmp_path = filepath.with_suffix(".tmp")
        content = frontmatter.dumps(post)
        tmp_path.write_text(content, encoding="utf-8")

        import os
        os.replace(str(tmp_path), str(filepath))
        logger.info(f"Frontmatter updated OK: {filepath.name}")
    except Exception as e:
        logger.error(f"Failed to update frontmatter for {filepath.name}: {e}")
        tmp_path = filepath.with_suffix(".tmp")
        if tmp_path.exists():
            tmp_path.unlink()
        raise
