import argparse
import time
import concurrent.futures
from typing import Dict
from scraper import OzBargainScraper
from db_manager import StorageManager

def process_item(item: Dict, username: str):
    """
    Worker function to process a single activity item.
    Scrapes the context deal and saves to DB.
    """
    url = item['url']
    text = item['text']
    
    # 1. Init separate instances for thread safety
    scraper = OzBargainScraper(headless=True)
    db = StorageManager()
    
    try:
        # 2. Scrape Deal/Context (Fast Mode - Requests)
        deal_data = scraper.scrape_deal_fast(url)
        if "error" in deal_data:
            print(f"[!] Error processing {url}: {deal_data['error']}")
            return False
            
        # 3. Store Deal Context (Mark as manual_fetch)
        db.upsert_live_deal(deal_data, source="manual_fetch")
        
        # 4. Store Activity
        content = deal_data.get("linked_comment")
        activity_type = "comment"
        activity_ref = deal_data.get("linked_comment_id")
        
        # Fallback if no specific comment content found
        if not content:
            if "posted" in text.lower():
                activity_type = "post"
                content = deal_data.get("title")
                activity_ref = deal_data.get("id")
            else:
                 content = "[No Comment Content Extracted (Fast Mode)]"
                 # Create a unique ref if missing
                 activity_ref = f"unknown-{int(time.time()*1000)}"

        if activity_ref and content:
            db.log_user_activity(
                user_id=username,
                deal_id=deal_data.get("id"),
                activity_ref=activity_ref,
                content=content,
                activity_type=activity_type
            )
            print(f"[+] Archived {activity_type}: {activity_ref} ({url})")
            return True
        else:
            print(f"[?] skipping {url} - no content")
            return False
            
    except Exception as e:
        print(f"[!!] Exception for {url}: {e}")
        return False
    finally:
        # cleanup if needed
        pass

def fetch_user_activity(username: str, limit: int = 50, workers: int = 8, headless: bool = True):
    # Fast mode (requests) is light, so we can support more workers.
    if workers > 20:
        print(f"[!] Warning: {workers} threads is high. Be careful of rate limiting.")
        
    print(f"[*] Starting fetch for user: {username} (Limit: {limit}, Threads: {workers})")
    if not headless:
        print("[*] Running in HEADFUL mode (Browser Visible).")
    
    # Main Scraper for the Feed (Generator)
    # This one drives the pagination loops
    feed_scraper = OzBargainScraper(headless=headless)
    
    print(f"[*] Fetching activity feed stream...")
    
    count_submitted = 0
    futures = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        # Iterate over the generator
        for activity_item in feed_scraper.get_user_activity(username, max_items=limit):
            count_submitted += 1
            
            # Submit to pool
            future = executor.submit(process_item, activity_item, username)
            futures.append(future)
            
            # Optional: throttle submission if too fast? 
            # Not needed, ThreadPool handles queue.
            
            # Print brief status
            if count_submitted % 10 == 0:
                print(f"[*] Discovered {count_submitted} items so far...")

        print(f"[*] Finished discovery. Waiting for {len(futures)} tasks to complete...")
        
        # Wait for all
        completed_count = 0
        for f in concurrent.futures.as_completed(futures):
            if f.result():
                completed_count += 1
                
    print(f"[*] All Done. Successfully archived {completed_count} items.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch OzBargain User Activity")
    parser.add_argument("username", help="OzBargain Username or ID")
    parser.add_argument("--limit", type=int, default=50, help="Max items to scrape")
    parser.add_argument("--workers", type=int, default=8, help="Concurrent threads (Default: 8)")
    parser.add_argument("--headful", action="store_true", help="Run browser in visible mode (debug)")
    
    args = parser.parse_args()
    fetch_user_activity(args.username, args.limit, args.workers, headless=not args.headful)
