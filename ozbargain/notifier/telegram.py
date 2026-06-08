import requests
from datetime import datetime
from ..config import settings
from ..utils.logger import setup_logger

logger = setup_logger("notifier")


class TelegramNotifier:
    def __init__(self):
        self.bot_token = settings.telegram_bot_token
        self.chat_id = settings.telegram_chat_id
        self.enabled = bool(self.bot_token and self.chat_id)

        if not self.enabled:
            logger.info("Telegram Token/Chat ID not found. Running in MOCK mode (printing to console).")

    def send_message(self, text: str, priority: bool = False):
        """
        Sends a message to Telegram.
        If priority is True, notification is sent with sound (standard).
        If priority is False, sent silently (disable_notification=True).
        """
        timestamp = datetime.now().strftime("%H:%M:%S")

        if not self.enabled:
            prefix = "🚨 " if priority else "ℹ️ "
            logger.info("[TELEGRAM MOCK] %s: %s", timestamp, text)
            return True

        # Real Send using requests
        api_url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

        payload = {"chat_id": self.chat_id, "text": text, "parse_mode": "HTML", "disable_notification": not priority}

        try:
            response = requests.post(api_url, json=payload, timeout=10)
            response.raise_for_status()
            return True
        except Exception as e:
            logger.error("Error sending Telegram message: %s", e)
            return False


if __name__ == "__main__":
    n = TelegramNotifier()
    n.send_message("<b>Test Message</b> from OzBargain Monitor! 🚀", priority=True)
