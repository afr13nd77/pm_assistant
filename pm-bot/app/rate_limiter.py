"""Telegram Bot API rate limiter (token bucket)."""

from __future__ import annotations

import asyncio
import logging
import time

from shared.settings import get as get_setting

logger = logging.getLogger(__name__)


class TelegramRateLimiter:
    """Token bucket rate limiter for Telegram Bot API.

    Telegram limits:
    - 1 msg/sec to private chats
    - 30 msg/sec globally
    - 20 msg/min to a single group
    """

    def __init__(
        self,
        rate: float | None = None,
        max_queue: int | None = None,
    ):
        if rate is None:
            rate = get_setting("rate_limits.telegram_messages_per_second", 1)
        if max_queue is None:
            max_queue = get_setting("rate_limits.telegram_max_queue_size", 50)

        self.min_interval: float = 1.0 / rate
        self.max_queue: int = max_queue
        self._last_sent: float = 0.0
        self._pending: int = 0

    async def acquire(self) -> None:
        """Wait until sending is allowed."""
        if self._pending >= self.max_queue:
            logger.warning(
                "rate_limiter: queue overflow (%d/%d), dropping oldest",
                self._pending, self.max_queue,
            )
            self._pending = self.max_queue - 1

        self._pending += 1
        try:
            now = time.monotonic()
            elapsed = now - self._last_sent
            if elapsed < self.min_interval:
                wait = self.min_interval - elapsed
                logger.debug("rate_limiter: throttling %.2fs", wait)
                await asyncio.sleep(wait)
            self._last_sent = time.monotonic()
        finally:
            self._pending -= 1

    def on_retry_after(self, retry_after: int) -> None:
        """Handle 429 from Telegram — push back the send window."""
        logger.warning(
            "rate_limiter: Telegram 429, retry_after=%d", retry_after
        )
        self._last_sent = time.monotonic() + retry_after
