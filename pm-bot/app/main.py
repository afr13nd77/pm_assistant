import logging
import os
import threading

import uvicorn
from dotenv import load_dotenv
from telegram.ext import ApplicationBuilder

from .handlers import get_handlers
from .stt import init_model as init_stt
from .transcript_watcher import start_watcher

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


def start_api():
    port = int(os.getenv("VAULT_API_PORT", "8000"))
    logger.info("Starting Vault API on port %d", port)
    uvicorn.run("app.vault_api:app", host="0.0.0.0", port=port, log_level="info")


async def post_init(application):
    """Set bot command menu visible in Telegram UI."""
    from telegram import BotCommand
    commands = [
        BotCommand("idea", "Записать идею"),
        BotCommand("daily", "Дневная заметка"),
        BotCommand("jira", "Черновик Jira-тикета"),
        BotCommand("progress", "Отчёт о ходе проекта"),
        BotCommand("pipeline", "Запустить проработку идеи"),
        BotCommand("jira_sync", "Синхронизация с Jira"),
        BotCommand("jira_import", "Импорт задачи из Jira"),
        BotCommand("jira_create", "Создать задачу в Jira"),
        BotCommand("fetch_meetings", "Загрузить протоколы из почты"),
        BotCommand("synthesize", "Запустить синтез идей"),
        BotCommand("status", "Статус хранилища"),
        BotCommand("lint", "Проверка хранилища"),
        BotCommand("domain", "Управление доменами"),
        BotCommand("creative", "Случайные забытые идеи"),
        BotCommand("test_enrichment", "Тест напоминаний"),
    ]
    await application.bot.set_my_commands(commands)
    logger.info("Bot command menu set: %d commands", len(commands))


def main():
    token = os.getenv("BOT_TOKEN")
    chat_id = int(os.getenv("ALLOWED_CHAT_ID") or "0")

    if not token:
        raise ValueError("BOT_TOKEN не задан в .env")

    logger.info("Инициализация STT модели...")
    try:
        init_stt()
    except Exception as e:
        logger.warning("STT модель не загружена, голосовые сообщения недоступны: %s", e)

    app = ApplicationBuilder().token(token).post_init(post_init).build()

    for handler in get_handlers():
        app.add_handler(handler)

    # Запускаем watcher транскриптов в фоне
    observer = start_watcher(bot=app.bot, chat_id=chat_id)

    # Start vault_api in daemon thread
    api_thread = threading.Thread(target=start_api, daemon=True)
    api_thread.start()
    logger.info("Vault API thread started")

    # Запускаем планировщик еженедельных отчётов
    from .scheduler import start_scheduler
    sched = start_scheduler(bot=app.bot, chat_id=chat_id)

    logger.info("PM Bot запущен")
    try:
        app.run_polling()
    finally:
        if sched:
            sched.shutdown(wait=False)
        observer.stop()
        observer.join()


if __name__ == "__main__":
    main()
