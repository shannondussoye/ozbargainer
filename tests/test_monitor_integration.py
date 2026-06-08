import pytest
from unittest.mock import patch
from ozbargain.models import DealResult
from ozbargain.core.monitor import LiveMonitor
from ozbargain.db.manager import StorageManager


@pytest.fixture
def monitor_integration(tmp_path):
    db_file = tmp_path / "integration_test.db"
    db_manager = StorageManager(db_path=str(db_file))

    with patch("ozbargain.core.monitor.StorageManager", return_value=db_manager), \
         patch("ozbargain.core.monitor.BrowserScraper"), \
         patch("ozbargain.core.monitor.TelegramNotifier"):

        monitor_instance = LiveMonitor()
        yield monitor_instance, db_manager, monitor_instance.scraper, monitor_instance.notifier


def test_process_deal_upsert_and_alert_deduplication(monitor_integration):
    monitor, db, mock_scraper, mock_notifier = monitor_integration

    # Setup database watched tags
    db.add_watched_tag("laptop")
    db.add_watched_tag("electronic")

    # Mock scraping result
    deal = DealResult(
        id="node/123",
        url="https://www.ozbargain.com.au/node/123",
        title="Cheap Laptop Sale",
        tags=["laptop", "computing"],
        price="$500",
        upvotes=10,
        comment_count=2,
    )
    mock_scraper.scrape_deal_page.return_value = deal
    mock_notifier.send_message.return_value = True

    # Process first time
    deal_id, deal_url = monitor.process_deal("https://www.ozbargain.com.au/node/123")

    assert deal_id == "node/123"
    assert deal_url == "https://www.ozbargain.com.au/node/123"

    # Verify deal upserted in DB
    with db._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT title, upvotes FROM live_deals WHERE resolved_id = ?", ("node/123",))
        row = cursor.fetchone()
    assert row is not None
    assert row[0] == "Cheap Laptop Sale"
    assert row[1] == 10

    # Verify notifier was called (priority alert for tag "laptop")
    mock_notifier.send_message.assert_called_once()
    assert "Watched Tag Found" in mock_notifier.send_message.call_args[0][0]
    assert mock_notifier.send_message.call_args[1].get("priority") is True

    # Reset notifier mock to test deduplication
    mock_notifier.send_message.reset_mock()

    # Process second time
    deal_id_2, deal_url_2 = monitor.process_deal("https://www.ozbargain.com.au/node/123")
    assert deal_id_2 == "node/123"

    # Notifier should NOT be called again (alert deduplication)
    mock_notifier.send_message.assert_not_called()
