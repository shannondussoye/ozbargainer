import requests
import time
import threading
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
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
        sydney_tz = ZoneInfo("Australia/Sydney")
        timestamp = datetime.now(timezone.utc).astimezone(sydney_tz).strftime("%H:%M:%S")

        if not self.enabled:
            prefix = "🚨 " if priority else "ℹ️ "
            logger.info("[TELEGRAM MOCK] %s%s: %s", prefix, timestamp, text)
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


class TelegramListener:
    def __init__(self, db, notifier: TelegramNotifier):
        self.db = db
        self.notifier = notifier
        self.bot_token = notifier.bot_token
        self.chat_id = notifier.chat_id
        self.enabled = notifier.enabled
        self._shutdown = False
        self._thread = None

    def start(self):
        if not self.enabled:
            logger.warning("Telegram notifier is disabled/running in mock mode. Listener will not start.")
            return
        self._thread = threading.Thread(target=self._run_loop, name="TelegramListener", daemon=True)
        self._thread.start()
        logger.info("Telegram command listener thread started.")

    def stop(self):
        self._shutdown = True
        logger.info("Signaled Telegram command listener thread to stop.")

    def _run_loop(self):
        offset = 0
        api_url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates"

        while not self._shutdown:
            try:
                payload = {
                    "offset": offset,
                    "timeout": 20,
                    "allowed_updates": ["message"]
                }
                response = requests.post(api_url, json=payload, timeout=25)
                if response.status_code != 200:
                    logger.error("Telegram getUpdates returned status code %d", response.status_code)
                    time.sleep(5)
                    continue

                data = response.json()
                if not data.get("ok"):
                    logger.error("Telegram getUpdates returned error: %s", data)
                    time.sleep(5)
                    continue

                for update in data.get("result", []):
                    offset = update["update_id"] + 1
                    message = update.get("message")
                    if not message:
                        continue
                    self._process_message(message)

            except Exception as e:
                if self._shutdown:
                    break
                logger.error("Error in Telegram listener loop: %s", e)
                time.sleep(5)

    def _process_message(self, message: dict):
        chat = message.get("chat", {})
        from_user = message.get("from", {})
        chat_id = chat.get("id")
        text = message.get("text", "").strip()

        # Security check: only allow authorized chat ID
        if str(chat_id) != str(self.chat_id):
            logger.warning(
                "Unauthorized access attempt by user %s (chat ID: %s)",
                from_user.get("username", "Unknown"),
                chat_id
            )
            return

        if not text.startswith("/"):
            return

        parts = text.split(maxsplit=1)
        command = parts[0].lower()
        args = parts[1].strip() if len(parts) > 1 else ""

        if command in ("/start", "/help"):
            reply = (
                "<b>🤖 OzBargain Monitor Bot</b>\n\n"
                "Use these commands to manage your watched tags:\n"
                "• /tags - List all currently watched tags\n"
                "• /watch &lt;tag&gt; - Add a tag to the watch list\n"
                "• /unwatch &lt;tag&gt; - Remove a tag from the watch list"
            )
        elif command == "/tags":
            tags = self.db.get_watched_tags()
            if not tags:
                reply = "You are not watching any tags yet."
            else:
                tag_list = "\n".join(f"• <code>{tag}</code>" for tag in sorted(tags))
                reply = f"<b>📋 Watched Tags:</b>\n{tag_list}"
        elif command in ("/watch", "/add"):
            if not args:
                reply = "Please specify a tag. Example: <code>/watch laptop</code>"
            else:
                tag = args.strip().lower()
                self.db.add_watched_tag(tag)
                reply = f"Added tag \"<b>{tag}</b>\" to the watch list."
        elif command in ("/unwatch", "/remove"):
            if not args:
                reply = "Please specify a tag. Example: <code>/unwatch laptop</code>"
            else:
                tag = args.strip().lower()
                self.db.remove_watched_tag(tag)
                reply = f"Removed tag \"<b>{tag}</b>\" from the watch list."
        else:
            reply = "Unknown command. Send /help to see all available commands."

        self.notifier.send_message(reply, priority=True)


if __name__ == "__main__":
    n = TelegramNotifier()
    n.send_message("<b>Test Message</b> from OzBargain Monitor! 🚀", priority=True)
