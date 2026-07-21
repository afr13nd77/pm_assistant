"""Singleton Langfuse client with graceful degradation."""

import logging
import os

logger = logging.getLogger(__name__)

_langfuse = None
_init_attempted = False


def get_langfuse():
    """Return Langfuse client instance or None if unavailable.

    Thread-safe singleton. On import failure or init error, returns None
    and logs a warning -- LLM calls continue without observability.
    """
    global _langfuse, _init_attempted

    if _init_attempted:
        return _langfuse

    _init_attempted = True

    if not os.getenv("LANGFUSE_PUBLIC_KEY"):
        logger.info("get_langfuse: LANGFUSE_PUBLIC_KEY not set, Langfuse disabled")
        return None

    if os.getenv("LANGFUSE_ENABLED", "true").lower() != "true":
        logger.info("get_langfuse: Langfuse disabled via LANGFUSE_ENABLED")
        return None

    try:
        from langfuse import Langfuse

        _langfuse = Langfuse(
            public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
            secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
            host=os.getenv("LANGFUSE_HOST", "http://langfuse:3000"),
            flush_at=10,
            flush_interval=5,
        )
        logger.info("get_langfuse: Langfuse client initialized, host=%s", os.getenv("LANGFUSE_HOST", "http://langfuse:3000"))
        return _langfuse

    except ImportError:
        logger.warning("get_langfuse: langfuse package not installed, observability disabled")
        return None
    except Exception as exc:
        logger.warning("get_langfuse: failed to initialize Langfuse: %s", exc)
        return None


def shutdown():
    """Flush pending events on application shutdown."""
    global _langfuse
    if _langfuse is not None:
        try:
            _langfuse.flush()
            logger.info("shutdown: Langfuse flushed successfully")
        except Exception as exc:
            logger.warning("shutdown: Langfuse flush failed: %s", exc)
