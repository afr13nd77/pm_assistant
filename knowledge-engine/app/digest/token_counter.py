"""Token counting via tiktoken cl100k_base tokenizer."""

import logging
import re

import tiktoken

logger = logging.getLogger(__name__)

_encoder = None


def _get_encoder():
    global _encoder
    if _encoder is None:
        logger.info("token_counter: initializing tiktoken cl100k_base encoder")
        _encoder = tiktoken.get_encoding("cl100k_base")
    return _encoder


def count_tokens(text: str) -> int:
    """Count tokens in text using tiktoken cl100k_base."""
    return len(_get_encoder().encode(text))


def count_sections(digest_body: str) -> dict:
    """Parse digest body into sections and count tokens for each.

    Returns dict with keys: one_liner, core_digest, extended_digest,
    changelog, total.
    """
    sections = {
        "one_liner": "",
        "core_digest": "",
        "extended_digest": "",
        "changelog": "",
    }

    current_section = None
    lines = digest_body.split("\n")

    section_map = {
        "# one-liner": "one_liner",
        "# core-digest": "core_digest",
        "# extended-digest": "extended_digest",
        "# changelog": "changelog",
    }

    for line in lines:
        stripped = line.strip().lower()
        if stripped in section_map:
            current_section = section_map[stripped]
            continue
        if current_section:
            sections[current_section] += line + "\n"

    encoder = _get_encoder()
    counts = {}
    total = 0
    for key, text in sections.items():
        text = text.strip()
        c = len(encoder.encode(text)) if text else 0
        counts[key] = c
        total += c
        logger.debug("token_counter: section %s = %d tokens", key, c)

    counts["total"] = total
    return counts
