from db_manager import StorageManager
from datetime import datetime
import json

db = StorageManager()

print("--- Trending Candidates (Last 24h, Min Score 60) ---")
candidates = db.get_trending_deals(hours=24, limit=-1, min_score=60)
for d in candidates:
    has_alerted = db.has_alerted(d['resolved_id'], 'trending')
    print(f"ID: {d['resolved_id']} | Score: {d['heat_score']} | Alerted: {has_alerted} | Title: {d['title'][:50]}")

print("\n--- Recent Alert History (Last 10) ---")
conn = db._get_connection()
cursor = conn.cursor()
cursor.execute("SELECT * FROM alert_history ORDER BY timestamp DESC LIMIT 10")
for row in cursor.fetchall():
    print(row)
conn.close()
