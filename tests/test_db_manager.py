import pytest
from ozbargain.db.manager import StorageManager

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
    db.upsert_live_deal({
        "id": deal_id,
        "url": f"https://www.ozbargain.com.au/{deal_id}",
        "title": "Test Deal",
        "upvotes": 50,
        "comment_count": 10
    })
    
    # Simulate a scraper hitting a bot-wall and returning 0 upvotes
    db.upsert_live_deal({
        "id": deal_id,
        "url": f"https://www.ozbargain.com.au/{deal_id}",
        "title": "Test Deal",
        "upvotes": 0,
        "comment_count": 0
    })
    
    conn = db._get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT upvotes, comment_count FROM live_deals WHERE resolved_id = ?", (deal_id,))
    row = cursor.fetchone()
    conn.close()
    
    assert row is not None
    # Data integrity guard should have preserved the 50 and 10
    assert row[0] == 50
    assert row[1] == 10

def test_data_integrity_guard_updates_real_votes(db):
    """
    If incoming upvotes > 0, the new value should be written.
    """
    deal_id = "node/124"
    
    db.upsert_live_deal({
        "id": deal_id,
        "title": "Deal 2",
        "upvotes": 50
    })
    
    db.upsert_live_deal({
        "id": deal_id,
        "title": "Deal 2",
        "upvotes": 60
    })
    
    conn = db._get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT upvotes FROM live_deals WHERE resolved_id = ?", (deal_id,))
    row = cursor.fetchone()
    conn.close()
    
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
