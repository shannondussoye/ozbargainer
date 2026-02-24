import os
import json
import requests
from datetime import datetime

# Load .env manually to avoid dependencies
env_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(env_path):
    with open(env_path, 'r') as f:
        for line in f:
            if line.strip() and not line.startswith('#'):
                key, _, value = line.partition('=')
                if key and value:
                    os.environ[key.strip()] = value.strip().strip('"').strip("'")

class TelegramNotifier:
    def __init__(self):
        self.bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        self.chat_id = os.environ.get("TELEGRAM_CHAT_ID")
        self.enabled = bool(self.bot_token and self.chat_id)
        
        if not self.enabled:
            print("[Notifier] Telegram Token/Chat ID not found. Running in MOCK mode (Printing to console).")

    def send_message(self, text: str, priority: bool = False):
        """
        Sends a message to Telegram.
        If priority is True, notification is sent with sound (standard).
        If priority is False, sent silently (disable_notification=True).
        """
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        if not self.enabled:
            prefix = "🚨 " if priority else "ℹ️ "
            print(f"\n{prefix} [TELEGRAM MOCK] {timestamp}: {text}\n")
            return

        # Real Send using requests
        api_url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_notification": not priority 
        }
        
        try:
            response = requests.post(api_url, json=payload, timeout=10)
            response.raise_for_status()
        except Exception as e:
            print(f"[Notifier] Error sending message: {e}")

if __name__ == "__main__":
    n = TelegramNotifier()
    n.send_message("<b>Test Message</b> from OzBargain Monitor! 🚀", priority=True)
