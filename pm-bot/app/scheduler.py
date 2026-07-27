import logging
import os

from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)

scheduler = None


def start_scheduler(bot, chat_id: int):
    """Start APScheduler with enrichment and daily alert jobs."""
    global scheduler
    logger.info("Starting scheduler, chat_id=%s", chat_id)

    scheduler = BackgroundScheduler()

    from .enrichment_reminder import run_enrichment_check_sync

    reminder_hour = int(os.getenv("ENRICHMENT_REMINDER_HOUR", "10"))
    reminder_minute = int(os.getenv("ENRICHMENT_REMINDER_MINUTE", "0"))

    scheduler.add_job(
        func=lambda: run_enrichment_check_sync(bot, chat_id),
        trigger="cron",
        hour=reminder_hour,
        minute=reminder_minute,
        id="enrichment_reminder",
        replace_existing=True,
    )
    logger.info(
        "Scheduler: enrichment_reminder registered for daily %02d:%02d",
        reminder_hour, reminder_minute,
    )

    from .daily_alert import run_daily_alert_sync

    daily_alert_hour = int(os.getenv("DAILY_ALERT_HOUR", "18"))
    daily_alert_minute = int(os.getenv("DAILY_ALERT_MINUTE", "0"))

    scheduler.add_job(
        func=lambda: run_daily_alert_sync(bot, chat_id),
        trigger="cron",
        hour=daily_alert_hour,
        minute=daily_alert_minute,
        id="daily_alert",
        replace_existing=True,
    )
    logger.info(
        "Scheduler: daily_alert registered for daily %02d:%02d",
        daily_alert_hour, daily_alert_minute,
    )

    scheduler.start()
    logger.info("Scheduler started")
    return scheduler
