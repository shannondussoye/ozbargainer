import sqlite3
from ..utils.logger import setup_logger

logger = setup_logger("db_schema")


def run_migrations(conn: sqlite3.Connection):
    """
    Initializes database tables and runs schema migrations.
    """
    cursor = conn.cursor()

    # Single Live Deals Table
    # PK is the resolved_id (canonical node ID)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS live_deals (
            resolved_id TEXT PRIMARY KEY,
            resolved_url TEXT,
            original_url TEXT,
            title TEXT,
            price TEXT,
            description TEXT,
            coupon_code TEXT,
            tags TEXT,
            upvotes INTEGER,
            downvotes INTEGER,
            comment_count INTEGER,
            timestamp DATETIME,
            time_str TEXT,
            user TEXT,
            action TEXT,
            type TEXT,
            is_expired BOOLEAN DEFAULT 0,
            posted_date TEXT,
            external_domain TEXT,
            source TEXT DEFAULT 'live'
        )
    """)

    # Indexes for fast trending queries and title resolution lookup
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_live_deals_timestamp_source ON live_deals(timestamp, source, is_expired)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_live_deals_title ON live_deals(title)")


    # Migration: Add is_expired if missing (for existing users)
    try:
        cursor.execute("ALTER TABLE live_deals ADD COLUMN is_expired BOOLEAN DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Migration: Add posted_date and external_domain
    try:
        cursor.execute("ALTER TABLE live_deals ADD COLUMN posted_date TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE live_deals ADD COLUMN external_domain TEXT")
    except sqlite3.OperationalError:
        pass

    # Migration: Add source column
    try:
        cursor.execute("ALTER TABLE live_deals ADD COLUMN source TEXT DEFAULT 'live'")
        # Backfill existing records as 'live'
        cursor.execute("UPDATE live_deals SET source = 'live' WHERE source IS NULL")
    except sqlite3.OperationalError:
        pass

    # User Activity Archive
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_activity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            deal_id TEXT,
            activity_ref TEXT UNIQUE, -- e.g. comment-123456 or node/123456
            content TEXT,
            activity_type TEXT,
            timestamp DATETIME
        )
    """)

    # Snapshots Table for Trending/Velocity Analytics
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS deal_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            deal_id TEXT,
            timestamp DATETIME,
            upvotes INTEGER,
            comment_count INTEGER
        )
    """)
    # Index for fast trending queries
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_deal_time ON deal_snapshots(deal_id, timestamp)")

    # Config Table for User Interests (Watched Tags)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS watched_tags (
            tag TEXT PRIMARY KEY,
            is_active BOOLEAN DEFAULT 1
        )
    """)

    # Migration: Add is_active to watched_tags if missing
    try:
        cursor.execute("ALTER TABLE watched_tags ADD COLUMN is_active BOOLEAN DEFAULT 1")
        cursor.execute("UPDATE watched_tags SET is_active = 1 WHERE is_active IS NULL")
    except sqlite3.OperationalError:
        pass

    # Alert History (Prevents Duplicate Notifications)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS alert_history (
            deal_id TEXT,
            alert_type TEXT,
            timestamp DATETIME,
            PRIMARY KEY (deal_id, alert_type)
        )
    """)

    conn.commit()
