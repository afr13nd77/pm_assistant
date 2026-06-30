"""Watchdog-демон near-realtime обработки очереди встреч (BL-145, design §3.5).

Этот модуль даёт near-realtime ветку обработки (US-02): вместо ожидания cron-прохода
`process_pending`, демон реагирует на появление нового юнита в `pending/` сразу.

Как это работает (design §3.5, §4.4, §5):
- `enqueue` пишет пару файлов в порядке `.meta.json` ПОТОМ `.txt` — то есть `.txt`
  появляется последним и его создание = сигнал «юнит готов». Поэтому хендлер
  реагирует ТОЛЬКО на `*.txt` (на `.meta.json` и директории — нет).
- Захват юнита идёт через `MeetingQueue.claim(unit_id)` — атомарный `os.rename`
  pending→processing. Это «замок»: если cron-проход (`process_pending`) или другой
  воркер успел забрать тот же юнит, claim вернёт None (проигравший ловит
  FileNotFoundError внутри claim). Поэтому демон БЕЗОПАСНО сосуществует с cron.
- Выиграл гонку (unit != None) → `processor.process_one(vault_path, unit, notify)`.
- Любое исключение по одному файлу изолируется try/except — Observer не падает.

Запускается как демон в KE-контейнере (CLI `queue-watch`, T-10). Вызывающий код сам
решает join/блокировку возвращённого Observer.

Блокирующее правило проекта: логируем старт демона, каждое срабатывание
(unit_id, won/lost claim), исход обработки и любые ошибки.
"""

from __future__ import annotations

import logging
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver

from shared.meeting_queue import meeting_queue_pending

from . import processor
from .queue import MeetingQueue

logger = logging.getLogger(__name__)


class PendingHandler(FileSystemEventHandler):
    """Реагирует на новые `*.txt` в `pending/` и запускает обработку юнита.

    Тонкий хендлер: вся бизнес-логика обработки — в `processor.process_one`.
    Здесь только распознавание события, атомарный claim и изоляция сбоев.
    """

    def __init__(self, vault_path: str, notify: bool = False) -> None:
        self.vault_path = vault_path
        self.notify = notify
        logger.info(
            "PendingHandler: initialised (vault_path=%s, notify=%s)", vault_path, notify
        )

    def on_created(self, event) -> None:
        """Появился новый файл в pending/ — если это `.txt`, попытаться claim+process.

        Сигнал готовности юнита — появление `.txt` (его `enqueue` пишет последним,
        design §5). Игнорирует директории и не-`.txt` файлы (в т.ч. `.meta.json`).
        """
        if getattr(event, "is_directory", False):
            logger.debug("PendingHandler.on_created: ignoring directory event")
            return
        self._handle_txt(getattr(event, "src_path", None))

    def on_moved(self, event) -> None:
        """Файл переименован В pending/ — реагируем по `dest_path`, если это `.txt`.

        КРИТИЧНО: `enqueue` пишет `.txt` через `shared.file_writer.atomic_write`
        (temp `.tmp` → `os.replace`), поэтому финальный `.txt` появляется как
        ПЕРЕИМЕНОВАНИЕ, а не как create. На большинстве платформ watchdog
        репортит это как moved-событие (dest_path = готовый `.txt`), а не created.
        Без этой ветки демон не реагировал бы на реально поставленные юниты.
        """
        if getattr(event, "is_directory", False):
            logger.debug("PendingHandler.on_moved: ignoring directory event")
            return
        self._handle_txt(getattr(event, "dest_path", None))

    def _handle_txt(self, src_path) -> None:
        """Общая обработка появления файла: если это `.txt` — claim + process_one.

        Игнорирует не-`.txt` (включая `.meta.json`, у которого suffix '.json').
        Всё обёрнуто в try/except: исключение одного файла не должно ронять Observer.
        """
        try:
            if not src_path:
                return

            path = Path(src_path)
            # Реагируем ТОЛЬКО на .txt. .meta.json и любые прочие файлы пропускаются.
            if path.suffix.lower() != ".txt":
                logger.debug(
                    "PendingHandler: ignoring non-.txt file %s", path.name
                )
                return

            unit_id = path.name[: -len(".txt")]
            logger.info("PendingHandler: new .txt detected unit_id=%s", unit_id)

            unit = MeetingQueue(self.vault_path).claim(unit_id)
            if unit is None:
                # Проиграл гонку с cron/другим воркером (или юнита уже нет) — норм.
                logger.debug(
                    "PendingHandler: lost claim for unit_id=%s — skip", unit_id
                )
                return

            logger.info(
                "PendingHandler: won claim for unit_id=%s — processing", unit_id
            )
            result = processor.process_one(self.vault_path, unit, self.notify)
            logger.info(
                "PendingHandler: unit_id=%s processed result=%s",
                unit_id,
                result.get("result") if isinstance(result, dict) else result,
            )
        except Exception as exc:  # noqa: BLE001 — изоляция: не ронять Observer
            logger.error(
                "PendingHandler: error handling event (src=%s): %s", src_path, exc
            )


def start_queue_watch(vault_path: str, notify: bool = False) -> BaseObserver:
    """Запустить watchdog-демон на `pending/` очереди встреч (design §3.5).

    Создаёт Observer, регистрирует `PendingHandler` на `meeting_queue_pending(vault_path)`
    (recursive=False — только верхний уровень pending/), стартует и возвращает Observer.
    Вызывающий решает, как блокироваться (observer.join()) и когда остановить (stop()).

    Returns:
        Запущенный watchdog Observer.
    """
    logger.info(
        "start_queue_watch: starting (vault_path=%s, notify=%s)", vault_path, notify
    )
    try:
        pending_dir = meeting_queue_pending(vault_path)
        handler = PendingHandler(vault_path, notify=notify)
        observer = Observer()
        observer.schedule(handler, str(pending_dir), recursive=False)
        observer.start()
        logger.info("start_queue_watch: watching pending dir %s", pending_dir)
        return observer
    except Exception as exc:
        logger.error("start_queue_watch: failed to start (vault_path=%s): %s", vault_path, exc)
        raise
