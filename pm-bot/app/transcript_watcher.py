import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from shared import meeting_queue, vault_paths

from .rate_limiter import TelegramRateLimiter

_rate_limiter = TelegramRateLimiter()

logger = logging.getLogger(__name__)

INBOX = Path(os.getenv("TRANSCRIPTS_INBOX", "/transcripts/inbox"))
PROCESSED_MARKER = ".processed"


class TranscriptHandler(FileSystemEventHandler):
    """Следит за папкой транскриптов. При появлении .txt файла — кладёт его в
    файловую очередь обработки встреч (raw/meeting-queue/pending/).

    Тонкий локальный источник (design §3.6): НЕ вызывает LLM и НЕ пишет протокол.
    Сырьё ставится в очередь через shared.meeting_queue.enqueue (source='local'),
    а саму обработку (LLM → протокол) выполняет KE Process-воркер, читающий из
    общего /vault. pm-bot не импортирует код knowledge-engine.
    """

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
        logger.info(f"Ставлю транскрипт в очередь: {path.name}")
        try:
            text = path.read_text(encoding="utf-8")
            # mtime файла как дата встречи (design §3.6)
            file_date = datetime.fromtimestamp(path.stat().st_mtime)

            # vault_path берём из shared.vault_paths (env VAULT_PATH) — единый
            # способ получения пути к vault в проекте. enqueue пишет пару
            # <unit_id>.txt + <unit_id>.meta.json атомарно в pending/.
            unit = meeting_queue.enqueue(
                vault_paths.VAULT_PATH,
                raw_text=text,
                source="local",
                subject=path.stem,
                date=file_date,
                source_filename=path.name,
            )

            # Переименовываем оригинал чтобы не обработать повторно (дедуп local).
            path.rename(path.with_stem(path.stem + PROCESSED_MARKER))

            if unit is None:
                logger.warning(
                    f"Транскрипт {path.name} пуст — юнит не создан, файл помечен "
                    f"как .processed"
                )
                return

            logger.info(
                f"Транскрипт поставлен в очередь: unit_id={unit.unit_id} "
                f"(source=local, {path.name} → .processed)"
            )

            # Лёгкое Telegram-уведомление (без деталей обработки — её делает KE).
            if self.bot and self.chat_id:
                await _rate_limiter.acquire()
                await self.bot.send_message(
                    chat_id=self.chat_id,
                    text=(
                        "📥 Транскрипт поставлен в очередь обработки:\n"
                        f"`{path.name}`"
                    ),
                    parse_mode="Markdown",
                )
        except Exception as e:
            logger.error(f"Ошибка постановки транскрипта {path.name} в очередь: {e}")


def start_watcher(bot=None, chat_id: int = 0):
    """Запускает watchdog в фоне."""
    try:
        INBOX.mkdir(parents=True, exist_ok=True)
        handler = TranscriptHandler(bot=bot, chat_id=chat_id)
        observer = Observer()
        observer.schedule(handler, str(INBOX), recursive=False)
        observer.start()
        logger.info(f"Слежу за папкой транскриптов: {INBOX}")
        return observer
    except Exception as e:
        logger.error(f"Не удалось запустить watcher транскриптов ({INBOX}): {e}")
        raise
