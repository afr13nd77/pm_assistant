import asyncio
import logging
from datetime import date

from .rate_limiter import TelegramRateLimiter

logger = logging.getLogger(__name__)

_rate_limiter = TelegramRateLimiter()


async def run_daily_alert(bot, chat_id: int) -> None:
    logger.info("daily_alert: start")
    try:
        from shared.system_log import LoggedProcess

        today = date.today()
        if today.weekday() >= 5:
            logger.info("daily_alert: skipping weekend (%s)", today.strftime("%A"))
            return

        from shared.vault_paths import wiki_daily_logs

        with LoggedProcess(process_type="daily-alert", source="pm-bot") as lp:
            daily_dir = wiki_daily_logs()
            today_str = date.today().strftime("%Y.%m.%d")
            pattern = f"{today_str}-*-Daily-summary.md"
            found = list(daily_dir.glob(pattern))

            if found:
                logger.info("daily_alert: daily found for %s — %s", today_str, found[0].name)
                lp.summary = "Daily-протокол найден"
                lp.details = {"daily_exists": True, "alert_sent": False}
                return

            display_date = date.today().strftime("%d.%m.%Y")
            msg = f"⚠️ Daily-протокол за {display_date} не получен"
            logger.info("daily_alert: no daily found for %s, sending alert", today_str)
            await _rate_limiter.acquire()
            await bot.send_message(chat_id=chat_id, text=msg)
            logger.info("daily_alert: alert sent to chat_id=%s", chat_id)

            lp.summary = "Alert отправлен: daily-протокол отсутствует"
            lp.details = {"daily_exists": False, "alert_sent": True}
    except Exception as e:
        logger.error("daily_alert: failed: %s", e, exc_info=True)


def run_daily_alert_sync(bot, chat_id: int) -> None:
    logger.info("daily_alert: cron triggered")
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(run_daily_alert(bot, chat_id))
        else:
            loop.run_until_complete(run_daily_alert(bot, chat_id))
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(run_daily_alert(bot, chat_id))
    logger.info("daily_alert: cron execution dispatched")
