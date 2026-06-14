import asyncio
import logging
import os
import shutil
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from shared import vault_paths

from .claude_client import process_meeting
from .obsidian_writer import write_meeting
from .rate_limiter import TelegramRateLimiter

_rate_limiter = TelegramRateLimiter()

logger = logging.getLogger(__name__)

INBOX = Path(os.getenv("TRANSCRIPTS_INBOX", "/transcripts/inbox"))
PROCESSED_MARKER = ".processed"


class TranscriptHandler(FileSystemEventHandler):
    """Следит за папкой транскриптов. При появлении .txt файла — обрабатывает."""

    def __init__(self, bot=None, chat_id: int = 0):
        self.bot = bot
        self.chat_id = chat_id

    def on_created(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix.lower() == ".txt" and not path.stem.endswith(PROCESSED_MARKER):
            asyncio.run(self._process(path))

    async def _process(self, path: Path):
        logger.info(f"Обрабатываю транскрипт: {path.name}")
        try:
            # Копируем оригинал в raw/ для сохранения неизменной копии
            try:
                raw_dest = vault_paths.raw_meetings() / path.name
                shutil.copy2(path, raw_dest)
                logger.info(f"Оригинал скопирован в raw: {raw_dest}")
            except Exception as copy_err:
                logger.error(f"Не удалось скопировать в raw: {copy_err}")

            text = path.read_text(encoding="utf-8")
            result = process_meeting(text)
            filepath = write_meeting(result, path.name)

            # Переименовываем оригинал чтобы не обработать повторно
            path.rename(path.with_stem(path.stem + PROCESSED_MARKER))

            logger.info(f"Заметка встречи сохранена: {filepath}")

            # Уведомляем в Telegram если бот передан
            if self.bot and self.chat_id:
                await _rate_limiter.acquire()
                await self.bot.send_message(
                    chat_id=self.chat_id,
                    text=f"✅ Транскрипт обработан:\n`{filepath.name}`",
                    parse_mode="Markdown"
                )
        except Exception as e:
            logger.error(f"Ошибка обработки транскрипта {path.name}: {e}")


def start_watcher(bot=None, chat_id: int = 0):
    """Запускает watchdog в фоне."""
    INBOX.mkdir(parents=True, exist_ok=True)
    handler = TranscriptHandler(bot=bot, chat_id=chat_id)
    observer = Observer()
    observer.schedule(handler, str(INBOX), recursive=False)
    observer.start()
    logger.info(f"Слежу за папкой транскриптов: {INBOX}")
    return observer
