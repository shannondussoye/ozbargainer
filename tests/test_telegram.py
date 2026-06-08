from unittest.mock import MagicMock, patch
from ozbargain.notifier.telegram import TelegramNotifier


def test_telegram_mock_mode():
    with patch("ozbargain.notifier.telegram.settings") as mock_settings:
        mock_settings.telegram_bot_token = None
        mock_settings.telegram_chat_id = None

        notifier = TelegramNotifier()
        assert notifier.enabled is False
        assert notifier.send_message("Test message", priority=True) is True


def test_telegram_real_mode_success():
    with patch("ozbargain.notifier.telegram.settings") as mock_settings, \
         patch("requests.post") as mock_post:
        mock_settings.telegram_bot_token = "fake_token"
        mock_settings.telegram_chat_id = "fake_chat_id"

        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        notifier = TelegramNotifier()
        assert notifier.enabled is True

        res = notifier.send_message("<b>Alert</b>", priority=True)
        assert res is True

        # Verify payload and call arguments
        mock_post.assert_called_once_with(
            "https://api.telegram.org/botfake_token/sendMessage",
            json={
                "chat_id": "fake_chat_id",
                "text": "<b>Alert</b>",
                "parse_mode": "HTML",
                "disable_notification": False,
            },
            timeout=10,
        )


def test_telegram_real_mode_failure():
    with patch("ozbargain.notifier.telegram.settings") as mock_settings, \
         patch("requests.post") as mock_post:
        mock_settings.telegram_bot_token = "fake_token"
        mock_settings.telegram_chat_id = "fake_chat_id"

        mock_post.side_effect = Exception("Connection Timeout")

        notifier = TelegramNotifier()
        res = notifier.send_message("Failed message", priority=False)

        assert res is False
        mock_post.assert_called_once()
