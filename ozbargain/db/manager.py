import sqlite3
import json
import os
from datetime import datetime
from typing import Dict, List, Optional

class StorageManager:
    def __init__(self, db_path: str = None):
        if db_path is None:
            # Flexible for Docker / Env config
            db_path = os.getenv("OZBARGAIN_DB_PATH", "ozbargain.db")
            
        self.db_path = db_path
        self._initialize_db()

    def _get_connection(self):
        return sqlite3.connect(self.db_path)

    def _initialize_db(self):
        """Creates the single live_deals table and drops old ones."""
        conn = self._get_connection()
        cursor = conn.cursor()

        # Drop legacy tables if they exist
        cursor.execute('DROP TABLE IF EXISTS activities')
        cursor.execute('DROP TABLE IF EXISTS deal_tags')
        cursor.execute('DROP TABLE IF EXISTS deals')
        cursor.execute('DROP TABLE IF EXISTS users')

        # Single Live Deals Table
        # PK is the resolved_id (canonical node ID)
        cursor.execute('''
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
        ''')
        
        # Migration: Add is_expired if missing (for existing users)
        try:
            cursor.execute("ALTER TABLE live_deals ADD COLUMN is_expired BOOLEAN DEFAULT 0")
        except sqlite3.OperationalError:
            pass # Column already exists

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
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                deal_id TEXT,
                activity_ref TEXT UNIQUE, -- e.g. comment-123456 or node/123456
                content TEXT,
                activity_type TEXT,
                timestamp DATETIME
            )
        ''')
        
        # Snapshots Table for Trending/Velocity Analytics
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS deal_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                deal_id TEXT,
                timestamp DATETIME,
                upvotes INTEGER,
                comment_count INTEGER
            )
        ''')
        # Index for fast trending queries
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_snapshots_deal_time ON deal_snapshots(deal_id, timestamp)')

        # Config Table for User Interests (Watched Tags)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS watched_tags (
                tag TEXT PRIMARY KEY
            )
        ''')

        # Alert History (Prevents Duplicate Notifications)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS alert_history (
                deal_id TEXT,
                alert_type TEXT,
                timestamp DATETIME,
                PRIMARY KEY (deal_id, alert_type)
            )
        ''')

        conn.commit()
        conn.close()
        
        # Perform initial cleanup on startup
        self.cleanup_snapshots()

    def upsert_live_deal(self, data: Dict, source: str = "live") -> str:
        """Inserts or updates a deal record, and logs a history snapshot."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Determine PK
        resolved_id = data.get("id") or data.get("url") # Scraper returns 'id'
        resolved_url = data.get("url")
        
        # Serialize tags to JSON array
        tags = data.get("tags", [])
        if isinstance(tags, list):
            tags_str = json.dumps(tags)
        else:
            tags_str = json.dumps([str(tags)]) if tags else "[]"
            
        now_ts = datetime.now()
        
        # 1. Fetch current state to check for "Data Integrity Guard"
        cursor.execute('SELECT upvotes, comment_count FROM live_deals WHERE resolved_id = ?', (resolved_id,))
        existing = cursor.fetchone()
        
        upvotes = data.get("upvotes", 0)
        comment_count = data.get("comment_count", 0)
        
        # Data Integrity Guard: 
        # If scraper hits a bot-wall, it might return 0 upvotes/comments.
        # If we already have higher numbers, keep them unless we explicitly want to "reset"
        if existing:
            orig_upvotes, orig_comments = existing
            if upvotes == 0 and orig_upvotes > 0:
                # print(f"[DB] Preserving upvotes ({orig_upvotes}) for {resolved_id} (Incoming was 0)")
                upvotes = orig_upvotes
            if comment_count == 0 and orig_comments > 0:
                # print(f"[DB] Preserving comment_count ({orig_comments}) for {resolved_id} (Incoming was 0)")
                comment_count = orig_comments

        # 2. Upsert Current State
        cursor.execute('''
            INSERT OR REPLACE INTO live_deals (
                resolved_id, resolved_url, original_url, 
                title, price, description, coupon_code, tags,
                upvotes, downvotes, comment_count,
                timestamp, time_str, user, action, type, is_expired,
                posted_date, external_domain, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            resolved_id,
            resolved_url,
            data.get("url"),
            data.get("title"),
            data.get("price"),
            data.get("description"),
            data.get("coupon_code"),
            tags_str,
            upvotes,
            data.get("downvotes", 0),
            comment_count,
            now_ts,
            data.get("time_str"),
            data.get("user"),
            data.get("action"),
            data.get("type"),
            1 if data.get("is_expired") else 0,
            data.get("posted_date"),
            data.get("external_domain"),
            source
        ))
        
        # 3. Add History Snapshot (For Trending Velocity)
        # We assume data["timestamp"] is the event time, but for snapshots we usually want "recorded at" time
        # Using current system time for the snapshot timestamp makes velocity calcs reliable relative to "now"
        cursor.execute('''
            INSERT INTO deal_snapshots (deal_id, timestamp, upvotes, comment_count)
            VALUES (?, ?, ?, ?)
        ''', (
            resolved_id,
            now_ts,
            upvotes,
            comment_count
        ))
        
        conn.commit()
        conn.close()
        return resolved_id

    def cleanup_snapshots(self, hours_retention: int = 168):
        """Deletes snapshots older than X hours (default 7 days)."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # SQLite 'now', '-X hours' syntax
        cursor.execute(f"DELETE FROM deal_snapshots WHERE timestamp < datetime('now', '-{hours_retention} hours')")
        deleted = cursor.rowcount
        
        conn.commit()
        conn.close()
        # print(f"[DB] Cleaned up {deleted} old snapshots.")

    def get_trending_deals(self, hours: int = 24, limit: int = -1, min_score: int = 0) -> List[Dict]:
        """
        Returns deals with the highest 'Heat Score' in the last X hours.
        Heat Score = (Upvotes * 2) + Comments.
        If limit <= 0, returns ALL matching deals (no limit).
        """
        conn = self._get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # SQL Construction
        limit_sql = f"LIMIT {limit}" if limit > 0 else ""
        
        # Simple Heat Score Query on Current State
        cursor.execute(f'''
            SELECT *, ((upvotes * 2) + comment_count) as heat_score 
            FROM live_deals 
            WHERE timestamp > datetime('now', '-{hours} hours') 
            AND ((upvotes * 2) + comment_count) >= {min_score}
            AND (is_expired = 0 OR is_expired IS NULL)
            AND source = 'live'
            ORDER BY heat_score DESC 
            {limit_sql}
        ''')
        
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def resolve_node_id_by_title(self, title: str) -> Optional[str]:
        """Attempts to find the canonical node ID for a given deal title."""
        if not title:
            return None
        
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Try exact match first
        cursor.execute("SELECT resolved_id FROM live_deals WHERE title = ? AND resolved_id LIKE 'node/%' LIMIT 1", (title,))
        row = cursor.fetchone()
        
        if not row:
            # Try fuzzy match if exact fails (e.g. title has extra whitespace or suffix)
            cursor.execute("SELECT resolved_id FROM live_deals WHERE title LIKE ? AND resolved_id LIKE 'node/%' LIMIT 1", (f"%{title}%",))
            row = cursor.fetchone()
            
        conn.close()
        return row[0] if row else None
        
    # --- Config Methods ---

    def add_watched_tag(self, tag: str):
        """Adds a tag to the watch list."""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT OR IGNORE INTO watched_tags (tag, is_active) VALUES (?, 1)", (tag,))
            conn.commit()
        except Exception as e:
            print(f"[DB] Error adding tag {tag}: {e}")
        finally:
            conn.close()

    def remove_watched_tag(self, tag: str):
        """Removes a tag from the watch list."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM watched_tags WHERE tag = ?", (tag,))
        conn.commit()
        conn.close()

    def get_watched_tags(self) -> List[str]:
        """Returns a list of active watched tags."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT tag FROM watched_tags WHERE is_active = 1")
        rows = cursor.fetchall()
        conn.close()
        return [row[0] for row in rows]

    # --- Alert History Methods ---

    def has_alerted(self, deal_id: str, alert_type: str) -> bool:
        """Checks if an alert of this type has already been sent for the deal."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM alert_history WHERE deal_id = ? AND alert_type = ?", (deal_id, alert_type))
        exists = cursor.fetchone() is not None
        conn.close()
        return exists

    def log_alert(self, deal_id: str, alert_type: str):
        """Logs that an alert has been sent."""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT OR IGNORE INTO alert_history (deal_id, alert_type, timestamp) VALUES (?, ?, ?)", 
                (deal_id, alert_type, datetime.now())
            )
            conn.commit()
        except Exception as e:
            print(f"[DB] Error logging alert: {e}")
        finally:
            conn.close()

    # --- User Archive Methods ---

    def log_user_activity(self, user_id: str, deal_id: str, activity_ref: str, content: str, activity_type: str = "comment"):
        """Logs user activity (comment/post) to the archive."""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT OR REPLACE INTO user_activity (user_id, deal_id, activity_ref, content, activity_type, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (user_id, deal_id, activity_ref, content, activity_type, datetime.now()))
            conn.commit()
        except Exception as e:
            print(f"[DB] Error logging user activity: {e}")
        finally:
            conn.close()
