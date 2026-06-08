import sqlite3
import json
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Dict, Iterator, List, Optional
from ..utils.logger import setup_logger
from ..config import settings
from ..models import DealResult
from .schema import run_migrations

logger = setup_logger("db_manager")


class StorageManager:
    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            # Flexible for Docker / Env config
            db_path = settings.ozbargain_db_path

        self.db_path = db_path
        self._initialize_db()

    @contextmanager
    def _get_connection(self) -> Iterator[sqlite3.Connection]:
        """Context manager for database connections. Guarantees cleanup on exception."""
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
        finally:
            conn.close()

    def _initialize_db(self):
        """Creates the database schema and runs migrations."""
        with self._get_connection() as conn:
            run_migrations(conn)

        # Perform initial cleanup on startup
        self.cleanup_snapshots()

    def upsert_live_deal(self, deal: "DealResult", source: str = "live") -> str:
        """Inserts or updates a deal record, and logs a history snapshot."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Determine PK
            resolved_id = deal.id or deal.url
            resolved_url = deal.url

            # Serialize tags to JSON array
            tags_str = json.dumps(deal.tags) if isinstance(deal.tags, list) else json.dumps([])

            now_ts = datetime.now(timezone.utc)

            # 1. Fetch current state to check for "Data Integrity Guard"
            cursor.execute("SELECT upvotes, comment_count FROM live_deals WHERE resolved_id = ?", (resolved_id,))
            existing = cursor.fetchone()

            upvotes = deal.upvotes
            comment_count = deal.comment_count

            # Data Integrity Guard:
            # If scraper hits a bot-wall, it might return 0 upvotes/comments.
            # If we already have higher numbers, keep them unless we explicitly want to "reset"
            if existing:
                orig_upvotes, orig_comments = existing
                if upvotes == 0 and orig_upvotes > 0:
                    logger.info("Preserving upvotes (%d) for %s (Incoming was 0)", orig_upvotes, resolved_id)
                    upvotes = orig_upvotes
                if comment_count == 0 and orig_comments > 0:
                    logger.info("Preserving comment_count (%d) for %s (Incoming was 0)", orig_comments, resolved_id)
                    comment_count = orig_comments

            # 2. Upsert Current State
            cursor.execute(
                """
                INSERT OR REPLACE INTO live_deals (
                    resolved_id, resolved_url, original_url,
                    title, price, description, coupon_code, tags,
                    upvotes, downvotes, comment_count,
                    timestamp, time_str, user, action, type, is_expired,
                    posted_date, external_domain, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    resolved_id,
                    resolved_url,
                    deal.original_url or deal.url,
                    deal.title,
                    deal.price,
                    deal.description,
                    deal.coupon_code,
                    tags_str,
                    upvotes,
                    deal.downvotes,
                    comment_count,
                    now_ts,
                    deal.time_str,
                    deal.user,
                    deal.action,
                    deal.type,
                    1 if deal.is_expired else 0,
                    deal.posted_date,
                    deal.external_domain,
                    source,
                ),
            )

            # 3. Add History Snapshot (For Trending Velocity)
            # We assume deal.timestamp is the event time, but for snapshots we usually want "recorded at" time
            # Using current system time for the snapshot timestamp makes velocity calcs reliable relative to "now"
            cursor.execute(
                """
                INSERT INTO deal_snapshots (deal_id, timestamp, upvotes, comment_count)
                VALUES (?, ?, ?, ?)
            """,
                (resolved_id, now_ts, upvotes, comment_count),
            )

            conn.commit()

        logger.info(
            "Successful deal upsert for %s", resolved_id, extra={"event_type": "storage_upsert", "items_count": 1}
        )
        return resolved_id

    def cleanup_snapshots(self, hours_retention: int = 168):
        """Deletes snapshots older than X hours (default 7 days)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute(
                "DELETE FROM deal_snapshots WHERE timestamp < datetime('now', ? || ' hours')",
                (f"-{int(hours_retention)}",),
            )
            deleted = cursor.rowcount

            conn.commit()

        logger.info("Cleaned up %d old snapshots.", deleted)

    def get_trending_deals(self, hours: int = 24, limit: int = -1, min_score: int = 0) -> List[Dict]:
        """
        Returns deals with the highest 'Heat Score' in the last X hours.
        Heat Score = (Upvotes * 2) + Comments.
        If limit <= 0, returns ALL matching deals (no limit).
        """
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            hours_modifier = f"-{int(hours)} hours"

            query = """
                SELECT *, ((upvotes * 2) + comment_count) as heat_score
                FROM live_deals
                WHERE timestamp > datetime('now', ?)
                AND ((upvotes * 2) + comment_count) >= ?
                AND (is_expired = 0 OR is_expired IS NULL)
                AND source = 'live'
                ORDER BY heat_score DESC
            """
            params: list = [hours_modifier, int(min_score)]

            if limit > 0:
                query += " LIMIT ?"
                params.append(int(limit))

            cursor.execute(query, params)

            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def resolve_node_id_by_title(self, title: str) -> Optional[str]:
        """Attempts to find the canonical node ID for a given deal title."""
        if not title:
            return None

        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Try exact match first
            cursor.execute(
                "SELECT resolved_id FROM live_deals WHERE title = ? AND resolved_id LIKE 'node/%' LIMIT 1", (title,)
            )
            row = cursor.fetchone()

            if not row:
                # Try fuzzy match if exact fails (e.g. title has extra whitespace or suffix)
                cursor.execute(
                    "SELECT resolved_id FROM live_deals WHERE title LIKE ? AND resolved_id LIKE 'node/%' LIMIT 1",
                    (f"%{title}%",),
                )
                row = cursor.fetchone()

            return row[0] if row else None

    def get_noisy_records(self) -> List[Dict]:
        """Returns records with missing/noisy titles (e.g. www.ozbargain.com.au or empty)."""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT resolved_id, resolved_url FROM live_deals WHERE title = 'www.ozbargain.com.au' OR title = '' OR title IS NULL"
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    # --- Config Methods ---

    def add_watched_tag(self, tag: str):
        """Adds a tag to the watch list."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("INSERT OR IGNORE INTO watched_tags (tag, is_active) VALUES (?, 1)", (tag,))
                conn.commit()
            except Exception as e:
                logger.error("Error adding tag %s: %s", tag, e)

    def remove_watched_tag(self, tag: str):
        """Removes a tag from the watch list."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM watched_tags WHERE tag = ?", (tag,))
            conn.commit()

    def get_watched_tags(self) -> List[str]:
        """Returns a list of active watched tags."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT tag FROM watched_tags WHERE is_active = 1")
            rows = cursor.fetchall()
            return [row[0] for row in rows]

    # --- Alert History Methods ---

    def has_alerted(self, deal_id: str, alert_type: str) -> bool:
        """Checks if an alert of this type has already been sent for the deal."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM alert_history WHERE deal_id = ? AND alert_type = ?", (deal_id, alert_type))
            return cursor.fetchone() is not None

    def log_alert(self, deal_id: str, alert_type: str):
        """Logs that an alert has been sent."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "INSERT OR IGNORE INTO alert_history (deal_id, alert_type, timestamp) VALUES (?, ?, ?)",
                    (deal_id, alert_type, datetime.now(timezone.utc)),
                )
                conn.commit()
            except Exception as e:
                logger.error("Error logging alert for %s: %s", deal_id, e)

    # --- User Archive Methods ---

    def log_user_activity(
        self, user_id: str, deal_id: str, activity_ref: str, content: str, activity_type: str = "comment"
    ):
        """Logs user activity (comment/post) to the archive."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO user_activity (user_id, deal_id, activity_ref, content, activity_type, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?)
                """,
                    (user_id, deal_id, activity_ref, content, activity_type, datetime.now(timezone.utc)),
                )
                conn.commit()
            except Exception as e:
                logger.error("Error logging user activity for %s: %s", user_id, e)
