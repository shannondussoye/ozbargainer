import pytest
from ozbargain.db.manager import StorageManager
from ozbargain.models import DealResult


@pytest.fixture
def db(tmp_path):
    # Use a real file in a tmp dir to avoid :memory: connection loss
    db_file = tmp_path / "test.db"
    manager = StorageManager(db_path=str(db_file))
    yield manager


def test_data_integrity_guard_preserves_upvotes(db):
    """
    If incoming upvotes == 0 and stored upvotes > 0, the stored value should be preserved.
    """
    deal_id = "node/123"

    # Insert initial state with real upvotes
    db.upsert_live_deal(
        DealResult(
            id=deal_id,
            url=f"https://www.ozbargain.com.au/{deal_id}",
            title="Test Deal",
            upvotes=50,
            comment_count=10,
        )
    )

    # Simulate a scraper hitting a bot-wall and returning 0 upvotes
    db.upsert_live_deal(
        DealResult(
            id=deal_id,
            url=f"https://www.ozbargain.com.au/{deal_id}",
            title="Test Deal",
            upvotes=0,
            comment_count=0,
        )
    )

    with db._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT upvotes, comment_count FROM live_deals WHERE resolved_id = ?", (deal_id,))
        row = cursor.fetchone()

    assert row is not None
    # Data integrity guard should have preserved the 50 and 10
    assert row[0] == 50
    assert row[1] == 10


def test_data_integrity_guard_updates_real_votes(db):
    """
    If incoming upvotes > 0, the new value should be written.
    """
    deal_id = "node/124"

    db.upsert_live_deal(DealResult(id=deal_id, title="Deal 2", upvotes=50))

    db.upsert_live_deal(DealResult(id=deal_id, title="Deal 2", upvotes=60))

    with db._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT upvotes FROM live_deals WHERE resolved_id = ?", (deal_id,))
        row = cursor.fetchone()

    assert row[0] == 60


def test_alert_history_caching(db):
    """
    has_alerted() should return True only after log_alert() is called for the same deal_id/type.
    """
    deal_id = "node/999"
    alert_type = "trending"

    assert not db.has_alerted(deal_id, alert_type)

    db.log_alert(deal_id, alert_type)

    assert db.has_alerted(deal_id, alert_type)
    # Should be false for a different type
    assert not db.has_alerted(deal_id, "keyword_match")


def test_connection_context_manager_closes_on_error(db):
    """
    Verify that _get_connection closes the connection even if an exception occurs.
    """
    import sqlite3
    from unittest.mock import MagicMock, patch

    mock_conn = MagicMock(spec=sqlite3.Connection)
    with patch("sqlite3.connect", return_value=mock_conn):
        try:
            with db._get_connection():
                raise ValueError("Test error")
        except ValueError:
            pass

    mock_conn.close.assert_called_once()


def test_get_trending_deals(db):
    """
    Verify trending deals retrieval, heat score calculation, and filtering of expired deals.
    """
    deal_a = DealResult(id="node/101", title="Deal A", upvotes=50, comment_count=10)
    deal_b = DealResult(id="node/102", title="Deal B", upvotes=20, comment_count=5)
    deal_c = DealResult(id="node/103", title="Deal C", upvotes=5, comment_count=0, is_expired=True)

    db.upsert_live_deal(deal_a)
    db.upsert_live_deal(deal_b)
    db.upsert_live_deal(deal_c)

    # A: 50 * 2 + 10 = 110, B: 20 * 2 + 5 = 45, C is expired
    results = db.get_trending_deals(hours=24, min_score=40)
    assert len(results) == 2
    assert results[0]["resolved_id"] == "node/101"
    assert results[0]["heat_score"] == 110
    assert results[1]["resolved_id"] == "node/102"
    assert results[1]["heat_score"] == 45

    # min_score = 100 filter
    results_high = db.get_trending_deals(hours=24, min_score=100)
    assert len(results_high) == 1
    assert results_high[0]["resolved_id"] == "node/101"


def test_resolve_node_id_by_title(db):
    """
    Verify that resolve_node_id_by_title performs exact and fuzzy matches.
    """
    db.upsert_live_deal(DealResult(id="node/201", title="Unique Offer Today Only"))
    db.upsert_live_deal(DealResult(id="node/202", title="Another Deal"))

    # Exact
    assert db.resolve_node_id_by_title("Unique Offer Today Only") == "node/201"

    # Fuzzy
    assert db.resolve_node_id_by_title("Unique Offer") == "node/201"

    # Not found
    assert db.resolve_node_id_by_title("Non existent") is None


def test_cleanup_snapshots(db):
    """
    Verify old snapshots are deleted and recent ones are kept.
    """
    with db._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO deal_snapshots (deal_id, timestamp, upvotes, comment_count) VALUES (?, datetime('now', '-240 hours'), ?, ?)",
            ("node/301", 10, 2)
        )
        cursor.execute(
            "INSERT INTO deal_snapshots (deal_id, timestamp, upvotes, comment_count) VALUES (?, datetime('now', '-1 hours'), ?, ?)",
            ("node/302", 20, 5)
        )
        conn.commit()

    db.cleanup_snapshots(hours_retention=168)

    with db._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT deal_id FROM deal_snapshots")
        rows = cursor.fetchall()

    assert len(rows) == 1
    assert rows[0][0] == "node/302"


def test_metadata_preservation_when_incoming_empty(db):
    """
    If a deal already exists in the database, and we upsert a new DealResult with empty/null
    metadata fields (like description, tags, price, etc.), the existing values should be preserved.
    """
    import json
    import sqlite3
    deal_id = "node/555"

    # 1. Insert full metadata
    db.upsert_live_deal(
        DealResult(
            id=deal_id,
            url=f"https://www.ozbargain.com.au/{deal_id}",
            title="Sleek Laptop",
            price="$999",
            description="Super fast laptop.",
            tags=["tech", "laptop"],
            posted_date="08/06/2026 - 10:00",
            external_domain="computerstore.com.au",
            upvotes=15,
            comment_count=5,
        )
    )

    # 2. Upsert with empty/missing values (e.g. from comment scrape or block fallback)
    db.upsert_live_deal(
        DealResult(
            id=deal_id,
            url=f"https://www.ozbargain.com.au/{deal_id}",
            title="",  # Empty/generic
            price=None,
            description=None,
            tags=None,
            posted_date=None,
            external_domain=None,
            upvotes=0,
            comment_count=0,
        )
    )

    # 3. Verify that metadata remains intact
    with db._get_connection() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM live_deals WHERE resolved_id = ?", (deal_id,))
        row = dict(cursor.fetchone())

    assert row["title"] == "Sleek Laptop"
    assert row["price"] == "$999"
    assert row["description"] == "Super fast laptop."
    assert json.loads(row["tags"]) == ["tech", "laptop"]
    assert row["posted_date"] == "08/06/2026 - 10:00"
    assert row["external_domain"] == "computerstore.com.au"
    assert row["upvotes"] == 15
    assert row["comment_count"] == 5


