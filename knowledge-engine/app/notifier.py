import logging
import os

import requests

logger = logging.getLogger(__name__)


def send_telegram(message: str, bot_token: str | None = None, chat_id: str | None = None, parse_mode: str | None = "Markdown") -> bool:
    bot_token = bot_token or os.getenv("BOT_TOKEN")
    chat_id = chat_id or os.getenv("ALLOWED_CHAT_ID")

    if not bot_token or not chat_id:
        logger.error("Cannot send Telegram notification: BOT_TOKEN or ALLOWED_CHAT_ID not set")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
    }
    if parse_mode is not None:
        payload["parse_mode"] = parse_mode

    logger.info(f"Sending Telegram notification to chat_id={chat_id}")
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        logger.info("Telegram notification sent OK")
        return True
    except requests.RequestException as e:
        logger.error(f"Failed to send Telegram notification: {e}")
        return False
