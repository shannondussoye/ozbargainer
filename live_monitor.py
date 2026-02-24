import os
import time
from playwright.sync_api import sync_playwright
from scraper import OzBargainScraper
from db_manager import StorageManager
from notifier import TelegramNotifier
from datetime import datetime, timedelta
from typing import Dict, Optional

class LiveMonitor:
    def __init__(self):
        self.db = StorageManager()
        self.scraper = OzBargainScraper(headless=True)
        self.notifier = TelegramNotifier()
        self.seen_rows = set() # Cache to avoid re-processing simple rows in same session
        
        # Configuration from Environment
        self.min_heat_score = int(os.getenv("MIN_HEAT_SCORE", 60))
        self.trending_check_interval = int(os.getenv("TRENDING_CHECK_INTERVAL", 30)) # Minutes
        self.poll_interval = int(os.getenv("POLL_INTERVAL", 5)) # Seconds

    def process_deal(self, url: str, browser=None, event_data: Dict = None) -> (Optional[str], Optional[str]):
        """
        Processes a deal URL: Scrape -> Merge -> Upsert
        """
        # Scrape
        deal_data = self.scraper.scrape_deal_page(url, browser=browser)
        
        if "error" in deal_data:
            print(f"[LiveMonitor] Error scraping {url}: {deal_data['error']}")
            return None, None
            
        # Merge event data
        if event_data:
            deal_data.update(event_data)
            
        # Upsert
        deal_id = self.db.upsert_live_deal(deal_data)
        
        # --- Priority Alerts ---
        try:
            # Skip if expired
            if deal_data.get("is_expired"):
                print(f"[LiveMonitor] Skipping alerts for Expired Deal: {deal_id}")
                return deal_id, deal_data.get("url")

            watched_tags = self.db.get_watched_tags()
            deal_tags = set(deal_data.get("tags", []))
            
            # Simple intersection check
            matches = [tag for tag in watched_tags if tag in deal_tags]
            
            if matches:
                # Check DB history to prevent duplicates (Persistence)
                if not self.db.has_alerted(deal_id, "priority"):
                    # Fire Priority Alert
                    deal_link = f"https://www.ozbargain.com.au/{deal_id}"
                    alert_text = f"<b>🚨 ALERT: Watched Tag Found!</b>\n\n" \
                                 f"<b>Matching:</b> {', '.join(matches)}\n" \
                                 f"<b>Deal:</b> <a href='{deal_link}'>{deal_data.get('title')}</a>\n" \
                                 f"<b>Price:</b> {deal_data.get('price', 'N/A')}"
                    
                    self.notifier.send_message(alert_text, priority=True)
                    self.db.log_alert(deal_id, "priority")
                    print(f"[LiveMonitor] Sent Alert for tags: {matches}")
                else:
                    print(f"[LiveMonitor] Skip Alert (Already Sent): {matches}")
        except Exception as e:
            print(f"[LiveMonitor] Error checking alerts: {e}")

        # Log 
        title_sample = deal_data.get("title", "No Title")[:50]
        print(f"[LiveMonitor] Upserted Deal: {deal_id} - {title_sample}")
        
        return deal_id, deal_data.get("url")

    def parse_relative_time(self, time_str):
        try:
            now = datetime.now()
            time_str = time_str.strip().lower()
            
            if "now" in time_str:
                return now
            
            parts = time_str.split()
            if len(parts) < 2:
                return now
                
            val = int(parts[0])
            unit = parts[1]
            
            delta = timedelta(seconds=0)
            if "sec" in unit:
                delta = timedelta(seconds=val)
            elif "min" in unit:
                delta = timedelta(minutes=val)
            elif "hour" in unit:
                delta = timedelta(hours=val)
            elif "day" in unit:
                delta = timedelta(days=val)
                
            return now - delta
        except:
            return datetime.now()

    def run(self):
        print("Starting Live Monitor...")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True) # Can be False to see it
            page = browser.new_page()
            
            print("Navigating to /live...")
            page.goto("https://www.ozbargain.com.au/live")
            page.wait_for_selector("tbody#livebody")
            
            # Setup Filters: Uncheck Wiki
            print("Configuring filters...")
            try:
                # Optimized Filter Script: More resilient to DOM depth changes
                filter_script = """
                    () => {
                        function setFilterByText(text, desiredState) {
                            const labels = Array.from(document.querySelectorAll('label'));
                            const label = labels.find(l => l.innerText.trim() === text);
                            if (label) {
                                const input = label.querySelector('input');
                                if (input && input.checked !== desiredState) {
                                    input.click(); // Click the input directly if possible, or the label
                                }
                            }
                        }

                        // 1. Uncheck Wiki
                        setFilterByText('Wiki', false);

                        // 2. Open Type Dropdown
                        const typeHeader = Array.from(document.querySelectorAll('#filters a'))
                                               .find(a => a.innerText.includes('Type'));
                        if (typeHeader) typeHeader.click();
                    }
                """
                page.evaluate(filter_script)
                
                # Wait for dropdown animation
                page.wait_for_timeout(1000)
                
                # 3. Configure Type Options
                type_script = """
                    () => {
                        function setFilterByText(text, desiredState) {
                            const labels = Array.from(document.querySelectorAll('label'));
                            const label = labels.find(l => l.innerText.trim() === text);
                            if (label) {
                                const input = label.querySelector('input');
                                if (input && input.checked !== desiredState) {
                                    input.click();
                                }
                            }
                        }
                        
                        setFilterByText('Comp', false);
                        setFilterByText('Forum', false);
                        setFilterByText('Deal', true);
                    }
                """
                page.evaluate(type_script)
                page.wait_for_timeout(500)
                
                print("Filters configured (Wiki=Off, Type=Deal Only).")
            except Exception as e:
                print(f"Error checking filters: {e}")

            print("Listening for updates... (Ctrl+C to stop)")
            
            last_trending_check = datetime.now()
            
            while True:
                try:
                    # --- Trending Check (Configurable interval) ---
                    if datetime.now() - last_trending_check > timedelta(minutes=self.trending_check_interval):
                        print("[LiveMonitor] Checking for trending deals...")
                        last_trending_check = datetime.now()
                        try:
                            # Fetch deals meeting threshold directly from DB
                            candidates = self.db.get_trending_deals(hours=24, limit=-1, min_score=self.min_heat_score)
                            
                            for deal in candidates:
                                heat_score = deal.get("heat_score", 0)
                                deal_id = deal["resolved_id"]
                                
                                # Use DB Persistence
                                if heat_score >= self.min_heat_score and not self.db.has_alerted(deal_id, "trending"):
                                    # Send Trending Alert
                                    deal_link = f"https://www.ozbargain.com.au/{deal_id}"
                                    msg = f"<b>🔥 POPULAR DEAL!</b> (Score: {heat_score})\n\n" \
                                          f"<a href='{deal_link}'>{deal['title']}</a>\n" \
                                          f"<b>Price:</b> {deal['price']}\n" \
                                          f"<b>Votes:</b> {deal['upvotes']} | <b>Comments:</b> {deal['comment_count']}"
                                    
                                    self.notifier.send_message(msg, priority=False)
                                    self.db.log_alert(deal_id, "trending")
                                    print(f"[LiveMonitor] Sent Trending Alert: {deal['title']} (Score: {heat_score})")
                        except Exception as te:
                            print(f"[LiveMonitor] Error checking trending: {te}")

                    # Get recent rows from top
                    # We only care about new stuff.
                    # Logic: Get top 5 rows. Process them.
                    # Since it's a "stream", new stuff appears at top.
                    
                    rows = page.locator("tbody#livebody tr").all()
                    
                    # Take top 20 to ensure we find deals even if cluttered
                    recent_rows = rows[:20]
                    
                    for row in recent_rows:
                        # Extract unique signature to avoid spamming the service
                        # best signature is the specific link to the action item
                        try:
                            # Extract columns for Time|User|Action|Subject|Type format
                            # col 1: Time
                            time_str = row.locator("td:nth-child(1)").text_content().strip()
                            timestamp = self.parse_relative_time(time_str).isoformat()
                            
                            # col 2: User
                            user_str = row.locator("td:nth-child(2)").text_content().strip()
                            
                            # col 3: Action (Icon title)
                            action_el = row.locator("td:nth-child(3) i")
                            action_str = "Unknown"
                            if action_el.count() > 0:
                                # Try title attribute first, else guess from class
                                action_title = action_el.get_attribute("title")
                                if action_title:
                                    action_str = action_title
                                else:
                                    cls = action_el.get_attribute("class")
                                    if "fa-file" in cls: action_str = "Post"
                                    elif "fa-comment" in cls: action_str = "Comment"
                                    elif "fa-plus" in cls: action_str = "Vote Up"
                                    elif "fa-minus" in cls: action_str = "Vote Down"
                            
                            # col 4: Subject
                            subject_link_el = row.locator("td:nth-child(4) a")
                            if subject_link_el.count() == 0:
                                print("DEBUG: Skip (no link)")
                                continue
                            subject_text = subject_link_el.text_content().strip()
                            url = subject_link_el.get_attribute("href")
                            
                            # col 5: Type
                            type_str = row.locator("td:nth-child(5)").text_content().strip()
                            
                            # Software-side filter fallback
                            if type_str != "Deal":
                                continue

                            # Construct full URL
                            if url.startswith("/"):
                                url = f"https://www.ozbargain.com.au{url}"
                            
                            if url in self.seen_rows:
                                continue
                                
                            # It's new to this session
                            self.seen_rows.add(url)
                            
                            # Prepare event data for merging
                            event_data = {
                                "original_url": url,
                                "timestamp": timestamp,
                                "time_str": time_str,
                                "user": user_str,
                                "action": action_str,
                                "type": type_str
                            }
                            
                            # Process deal
                            deal_id, resolved_url = self.process_deal(url, browser=browser, event_data=event_data)
                            
                            if not resolved_url:
                                resolved_url = "N/A"

                            # Requested Output Format: Timestamp|TimeStr|User|Action|Subject|Type|URL|ResolvedURL
                            print(f"{timestamp}|{time_str}|{user_str}|{action_str}|{subject_text}|{type_str}|{url}|{resolved_url}")
                            
                            if deal_id:
                                # Optional: We could suppress this if now redundant, but good for debug
                                # print(f"      -> Linked Deal ID: {deal_id}")
                                pass
                                
                        except Exception as e:
                            print(f"DEBUG: Loop Error: {e}")
                            # Row might be detached if page refreshed too fast
                            pass
                            
                except Exception as e:
                    print(f"Error in monitor loop: {e}")
                
                # Poll interval
                time.sleep(self.poll_interval)
                
            browser.close()

if __name__ == "__main__":
    monitor = LiveMonitor()
    monitor.run()
