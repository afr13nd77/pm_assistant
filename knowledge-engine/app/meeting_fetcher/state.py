"""State tracker for Meeting Fetcher.

Manages `.meeting-fetcher-state.json` in the vault root to track
which emails have already been processed (dedup by message-id).
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from shared.file_writer import atomic_write

logger = logging.getLogger(__name__)

STATE_FILENAME = ".meeting-fetcher-state.json"
STATE_VERSION = 1


def _empty_state() -> dict:
    """Return a fresh empty state dict."""
    return {
        "version": STATE_VERSION,
        "last_run": None,
        "processed": {},
        "failed": {},
    }


class State:
    """Persistent state for meeting-fetcher deduplication.

    State is stored as JSON at ``{vault_path}/.meeting-fetcher-state.json``.
    The ``.`` prefix hides it from the Obsidian file explorer.
    """

    def __init__(self, vault_path: str) -> None:
        """Load state from disk. Create empty state if file missing or corrupt.

        Args:
            vault_path: Absolute path to the Obsidian vault root.
        """
        self._path = Path(vault_path) / STATE_FILENAME
        self._data: dict = _empty_state()

        logger.info("State.__init__: loading state from %s", self._path)
        try:
            self._load()
            logger.info(
                "State.__init__: loaded OK, %d processed entries",
                len(self._data.get("processed", {})),
            )
        except Exception as exc:
            logger.error(
                "State.__init__: failed to load state from %s: %s", self._path, exc
            )
            self._data = _empty_state()
            logger.info("State.__init__: recreated empty state after load failure")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_processed(self, message_id: str) -> bool:
        """Check if a message-id was already processed.

        Args:
            message_id: RFC-822 Message-ID of the email.

        Returns:
            True if already processed, False otherwise.
        """
        result = message_id in self._data["processed"]
        logger.info(
            "State.is_processed: message_id=%s result=%s", message_id, result
        )
        return result

    def mark_processed(
        self,
        message_id: str,
        subject: str,
        date: str,
        attachment: str,
        output_file: str,
        protocol_type: str,
    ) -> None:
        """Record a processed email and persist state to disk.

        Args:
            message_id:    RFC-822 Message-ID of the email.
            subject:       Email subject line.
            date:          ISO-8601 date string of the meeting email.
            attachment:    Filename of the transcript attachment.
            output_file:   Relative path to the generated markdown note.
            protocol_type: Meeting type classification (e.g. ``"daily"``).
        """
        logger.info(
            "State.mark_processed: message_id=%s subject=%s", message_id, subject
        )
        try:
            self._data["processed"][message_id] = {
                "subject": subject,
                "date": date,
                "attachment": attachment,
                "output_file": output_file,
                "type": protocol_type,
                "processed_at": datetime.now().isoformat(),
            }
            self._save()
            logger.info(
                "State.mark_processed: OK, total processed=%d",
                len(self._data["processed"]),
            )
        except Exception as exc:
            logger.error(
                "State.mark_processed: failed for message_id=%s: %s",
                message_id,
                exc,
            )
            raise

    def mark_failed(self, message_id: str, subject: str, error: str) -> None:
        """Increment failure count for a message. Persist to disk.

        If the message is already tracked in "failed", increments its attempt
        counter. Otherwise creates a new entry.

        Args:
            message_id: RFC-822 Message-ID of the email.
            subject:    Email subject line.
            error:      Error description from the failed processing attempt.
        """
        logger.info(
            "State.mark_failed: message_id=%s subject=%s error=%s",
            message_id,
            subject,
            error,
        )
        try:
            now = datetime.now().isoformat()
            entry = self._data["failed"].get(message_id)
            if entry:
                entry["attempts"] += 1
                entry["last_error"] = error
                entry["last_seen"] = now
                logger.info(
                    "State.mark_failed: incremented attempts to %d for message_id=%s",
                    entry["attempts"],
                    message_id,
                )
            else:
                self._data["failed"][message_id] = {
                    "subject": subject,
                    "attempts": 1,
                    "last_error": error,
                    "first_seen": now,
                    "last_seen": now,
                }
                logger.info(
                    "State.mark_failed: created new failed entry for message_id=%s",
                    message_id,
                )
            self._save()
            logger.info(
                "State.mark_failed: OK, total failed=%d",
                len(self._data["failed"]),
            )
        except Exception as exc:
            logger.error(
                "State.mark_failed: failed for message_id=%s: %s",
                message_id,
                exc,
            )
            raise

    def is_max_retried(self, message_id: str, max_retries: int = 3) -> bool:
        """Return True if message has failed >= max_retries times.

        Args:
            message_id:  RFC-822 Message-ID of the email.
            max_retries: Threshold for permanent failure (default 3).

        Returns:
            True if the message has reached or exceeded the retry limit.
        """
        entry = self._data["failed"].get(message_id)
        if not entry:
            return False
        result = entry["attempts"] >= max_retries
        logger.info(
            "State.is_max_retried: message_id=%s attempts=%d max=%d result=%s",
            message_id,
            entry["attempts"],
            max_retries,
            result,
        )
        return result

    def get_failed_count(self) -> int:
        """Return number of permanently failed (max-retried) messages.

        Returns:
            Count of messages with attempts >= 3 in the failed dict.
        """
        count = sum(
            1
            for entry in self._data["failed"].values()
            if entry["attempts"] >= 3
        )
        logger.info("State.get_failed_count: %d permanently failed", count)
        return count

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Read and parse the state file from disk.

        Raises:
            FileNotFoundError: If the state file does not exist.
            json.JSONDecodeError: If the file contains invalid JSON.
        """
        if not self._path.exists():
            logger.info("State._load: state file not found, using empty state")
            return

        raw = self._path.read_text(encoding="utf-8")
        self._data = json.loads(raw)

        # Backwards compat: old state files may lack the "failed" key
        if "failed" not in self._data:
            logger.info("State._load: migrating state — adding missing 'failed' key")
            self._data["failed"] = {}

        logger.info("State._load: parsed state file OK")

    def _save(self) -> None:
        """Atomic-write state to disk. Updates ``last_run`` timestamp."""
        logger.info("State._save: writing state to %s", self._path)
        try:
            self._data["last_run"] = datetime.now().isoformat()
            content = json.dumps(self._data, ensure_ascii=False, indent=2)
            atomic_write(str(self._path), content)
            logger.info("State._save: OK")
        except Exception as exc:
            logger.error("State._save: failed: %s", exc)
            raise
