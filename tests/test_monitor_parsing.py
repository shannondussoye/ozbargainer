from datetime import datetime, timedelta
import pytest
from unittest.mock import patch
from ozbargain.core.monitor import LiveMonitor


@pytest.fixture
def monitor():
    with patch("ozbargain.core.monitor.StorageManager"), \
         patch("ozbargain.core.monitor.BrowserScraper"), \
         patch("ozbargain.core.monitor.TelegramNotifier"):
        monitor_instance = LiveMonitor()
        yield monitor_instance


def test_parse_relative_time_now(monitor):
    res = monitor.parse_relative_time("now")
    assert (datetime.now() - res).total_seconds() < 2


def test_parse_relative_time_minutes(monitor):
    res = monitor.parse_relative_time("5 min ago")
    expected = datetime.now() - timedelta(minutes=5)
    assert abs((expected - res).total_seconds()) < 2


def test_parse_relative_time_hours(monitor):
    res = monitor.parse_relative_time("2 hours ago")
    expected = datetime.now() - timedelta(hours=2)
    assert abs((expected - res).total_seconds()) < 2


def test_parse_relative_time_days(monitor):
    res = monitor.parse_relative_time("3 days ago")
    expected = datetime.now() - timedelta(days=3)
    assert abs((expected - res).total_seconds()) < 2


def test_parse_relative_time_seconds(monitor):
    res = monitor.parse_relative_time("30 sec ago")
    expected = datetime.now() - timedelta(seconds=30)
    assert abs((expected - res).total_seconds()) < 2


def test_parse_relative_time_malformed(monitor):
    # Should fallback to now
    res = monitor.parse_relative_time("weird_string")
    assert (datetime.now() - res).total_seconds() < 2


def test_should_scrape_cooldown(monitor):
    monitor.scrape_cooldown = 10  # 10 seconds cooldown
    url = "https://www.ozbargain.com.au/node/123"

    # First call should succeed
    assert monitor._should_scrape(url, "Test Title") is True

    # Immediate second call should be blocked by cooldown
    assert monitor._should_scrape(url, "Test Title") is False

    # Mock time passing by setting the stored time in last_scraped_times back by 11 seconds
    monitor.last_scraped_times["node/123"] = datetime.now() - timedelta(seconds=11)

    # Now it should be allowed again
    assert monitor._should_scrape(url, "Test Title") is True


def test_should_scrape_deduplication_by_node(monitor):
    monitor.scrape_cooldown = 10
    # Different URLs but same node ID
    url1 = "https://www.ozbargain.com.au/node/123/redir"
    url2 = "https://www.ozbargain.com.au/node/123"

    assert monitor._should_scrape(url1, "Test Title") is True
    # Second URL should hit the cooldown because node/123 is the same key
    assert monitor._should_scrape(url2, "Test Title") is False


def test_should_scrape_deduplication_by_comment_title(monitor):
    monitor.scrape_cooldown = 10
    # Different comment links on the same deal
    url1 = "https://www.ozbargain.com.au/comment/123"
    url2 = "https://www.ozbargain.com.au/comment/456"
    title = "Super Cheap Laptop Deal"

    assert monitor._should_scrape(url1, title) is True
    # Second should hit cooldown because title is used for comments grouping
    assert monitor._should_scrape(url2, title) is False
