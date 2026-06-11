import logging
import os
from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)

scheduler = None


def start_scheduler(bot, chat_id: int):
    """Start APScheduler with weekly report job."""
    global scheduler
    logger.info("Starting scheduler, chat_id=%s", chat_id)

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        func=lambda: _run_weekly_report(bot, chat_id),
        trigger="cron",
        day_of_week="mon",
        hour=9,
        minute=0,
        id="weekly_report",
        replace_existing=True,
    )

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
    logger.info("Scheduler started: weekly_report job registered for Monday 09:00")
    return scheduler


async def _run_weekly_report_async(bot, chat_id: int):
    """Async implementation of weekly report generation and notification."""
    logger.info("Running scheduled weekly report")
    try:
        from .reporter import generate_weekly_report
        from .obsidian_writer import write_report

        report_md = generate_weekly_report()
        logger.info("Weekly report generated, length=%d", len(report_md))

        filepath = write_report(report_md)
        logger.info("Weekly report saved to %s", filepath)

        await bot.send_message(
            chat_id=chat_id,
            text=f"Еженедельный отчёт готов:\n`{filepath.name}`\n\nОткрой: http://localhost:8080/report.html",
            parse_mode="Markdown",
        )
        logger.info("Weekly report notification sent to chat_id=%s", chat_id)
    except Exception as e:
        logger.error("Weekly report generation failed: %s", e, exc_info=True)
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=f"Ошибка генерации отчёта: {e}",
            )
        except Exception as send_err:
            logger.error("Failed to send error notification: %s", send_err)


def _run_weekly_report(bot, chat_id: int):
    """Sync wrapper that runs the async report in the bot's event loop."""
    import asyncio

    logger.info("Weekly report cron triggered")
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(_run_weekly_report_async(bot, chat_id))
        else:
            loop.run_until_complete(_run_weekly_report_async(bot, chat_id))
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_run_weekly_report_async(bot, chat_id))
    logger.info("Weekly report cron execution dispatched")
