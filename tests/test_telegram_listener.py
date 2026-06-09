import pytest
from unittest.mock import MagicMock
from ozbargain.db.manager import StorageManager
from ozbargain.notifier.telegram import TelegramNotifier, TelegramListener


@pytest.fixture
def test_db(tmp_path):
    db_file = tmp_path / "test_listener.db"
    db_manager = StorageManager(db_path=str(db_file))
    return db_manager


@pytest.fixture
def mock_notifier():
    notifier = MagicMock(spec=TelegramNotifier)
    notifier.bot_token = "12345:mock_token"
    notifier.chat_id = "987654321"
    notifier.enabled = True
    return notifier


def test_listener_disabled(test_db):
    notifier = MagicMock(spec=TelegramNotifier)
    notifier.bot_token = None
    notifier.chat_id = None
    notifier.enabled = False
    listener = TelegramListener(test_db, notifier)
    listener.start()
    assert listener._thread is None


def test_process_message_security(test_db, mock_notifier):
    listener = TelegramListener(test_db, mock_notifier)

    # Unauthorized chat ID should be ignored
    unauthorized_msg = {
        "chat": {"id": "111111111"},
        "from": {"username": "hacker"},
        "text": "/tags"
    }
    listener._process_message(unauthorized_msg)
    mock_notifier.send_message.assert_not_called()


def test_process_message_non_command(test_db, mock_notifier):
    listener = TelegramListener(test_db, mock_notifier)

    # Message that is not a command should be ignored
    msg = {
        "chat": {"id": "987654321"},
        "from": {"username": "owner"},
        "text": "hello bot"
    }
    listener._process_message(msg)
    mock_notifier.send_message.assert_not_called()


def test_command_start_help(test_db, mock_notifier):
    listener = TelegramListener(test_db, mock_notifier)

    msg = {
        "chat": {"id": "987654321"},
        "from": {"username": "owner"},
        "text": "/help"
    }
    listener._process_message(msg)
    mock_notifier.send_message.assert_called_once()
    assert "Use these commands to manage your watched tags" in mock_notifier.send_message.call_args[0][0]


def test_command_tags_empty(test_db, mock_notifier):
    listener = TelegramListener(test_db, mock_notifier)

    msg = {
        "chat": {"id": "987654321"},
        "from": {"username": "owner"},
        "text": "/tags"
    }
    listener._process_message(msg)
    mock_notifier.send_message.assert_called_once()
    assert "You are not watching any tags yet" in mock_notifier.send_message.call_args[0][0]


def test_command_watch_and_unwatch(test_db, mock_notifier):
    listener = TelegramListener(test_db, mock_notifier)

    # 1. Watch a tag
    msg_watch = {
        "chat": {"id": "987654321"},
        "from": {"username": "owner"},
        "text": "/watch laptop"
    }
    listener._process_message(msg_watch)
    mock_notifier.send_message.assert_called_once()
    assert 'Added tag "<b>laptop</b>"' in mock_notifier.send_message.call_args[0][0]
    assert "laptop" in test_db.get_watched_tags()

    # Reset mock
    mock_notifier.send_message.reset_mock()

    # 2. Check tags list
    msg_list = {
        "chat": {"id": "987654321"},
        "from": {"username": "owner"},
        "text": "/tags"
    }
    listener._process_message(msg_list)
    mock_notifier.send_message.assert_called_once()
    assert "laptop" in mock_notifier.send_message.call_args[0][0]

    # Reset mock
    mock_notifier.send_message.reset_mock()

    # 3. Unwatch a tag
    msg_unwatch = {
        "chat": {"id": "987654321"},
        "from": {"username": "owner"},
        "text": "/unwatch laptop"
    }
    listener._process_message(msg_unwatch)
    mock_notifier.send_message.assert_called_once()
    assert 'Removed tag "<b>laptop</b>"' in mock_notifier.send_message.call_args[0][0]
    assert "laptop" not in test_db.get_watched_tags()


def test_command_watch_missing_arguments(test_db, mock_notifier):
    listener = TelegramListener(test_db, mock_notifier)

    msg = {
        "chat": {"id": "987654321"},
        "from": {"username": "owner"},
        "text": "/watch"
    }
    listener._process_message(msg)
    mock_notifier.send_message.assert_called_once()
    assert "Please specify a tag" in mock_notifier.send_message.call_args[0][0]


def test_command_unknown(test_db, mock_notifier):
    listener = TelegramListener(test_db, mock_notifier)

    msg = {
        "chat": {"id": "987654321"},
        "from": {"username": "owner"},
        "text": "/unknown_cmd"
    }
    listener._process_message(msg)
    mock_notifier.send_message.assert_called_once()
    assert "Unknown command" in mock_notifier.send_message.call_args[0][0]
