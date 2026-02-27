import os
import time
from playwright.sync_api import sync_playwright
from .scraper import OzBargainScraper
from ..db.manager import StorageManager
from ..notifier.telegram import TelegramNotifier
from datetime import datetime, timedelta
from typing import Dict, Optional

class LiveMonitor:
    def __init__(self):
        self.db = StorageManager()
        self.cdp_url = os.getenv("CHROME_CDP_URL")
        self.scraper = OzBargainScraper(headless=True, cdp_url=self.cdp_url)
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
        deal_id = deal_data.get("id") or url
        
        # --- Metadata & ID Recovery Fallback ---
        # If we have a generic title but a good one from event_data (live row), restore it
        rows_title = event_data.get("title") if event_data else None
        if rows_title and (not deal_data.get("title") or deal_data.get("title") in ["OzBargain", "www.ozbargain.com.au", "Performing security verification"]):
             deal_data["title"] = rows_title
             
        # If deal_id is a comment, try to resolve to parent node via title
        if deal_id and deal_id.startswith("comment/"):
             parent_id = self.db.resolve_node_id_by_title(deal_data.get("title"))
             if parent_id:
                  print(f"[LiveMonitor] Resolved comment {deal_id} to parent node {parent_id}")
                  deal_id = parent_id
                  deal_data["id"] = deal_id
        
        # Final Upsert
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
                    
                    if self.notifier.send_message(alert_text, priority=True):
                        self.db.log_alert(deal_id, "priority")
                        print(f"[LiveMonitor] Sent Alert for tags: {matches}")
                    else:
                        print(f"[LiveMonitor] Failed to send Alert for tags: {matches}")
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
        last_trending_check = datetime.now() - timedelta(minutes=self.trending_check_interval)
        
        while True:
            print("[LiveMonitor] Initializing browser session...")
            try:
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True)
                    page = browser.new_page()
                    
                    print("[LiveMonitor] Navigating to /live...")
                    page.goto("https://www.ozbargain.com.au/live")
                    page.wait_for_selector("tbody#livebody")
                    
                    # Setup Filters: Uncheck Wiki
                    print("[LiveMonitor] Configuring filters...")
                    filter_script = """
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
                            setFilterByText('Wiki', false);
                            const typeHeader = Array.from(document.querySelectorAll('#filters a'))
                                                   .find(a => a.innerText.includes('Type'));
                            if (typeHeader) typeHeader.click();
                        }
                    """
                    page.evaluate(filter_script)
                    page.wait_for_timeout(1000)
                    
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
                    
                    print("[LiveMonitor] Filters configured. Listening for updates...")
                    
                    while True:
                        try:
                            # --- Trending Check ---
                            if datetime.now() - last_trending_check > timedelta(minutes=self.trending_check_interval):
                                print("[LiveMonitor] Checking for trending deals...")
                                last_trending_check = datetime.now()
                                candidates = self.db.get_trending_deals(hours=24, limit=-1, min_score=self.min_heat_score)
                                
                                for deal in candidates:
                                    deal_id = deal["resolved_id"]
                                    if not self.db.has_alerted(deal_id, "trending"):
                                        deal_link = f"https://www.ozbargain.com.au/{deal_id}"
                                        msg = f"<b>🔥 POPULAR DEAL!</b> (Score: {deal['heat_score']})\n\n" \
                                              f"<a href='{deal_link}'>{deal['title']}</a>\n" \
                                              f"<b>Price:</b> {deal['price']}\n" \
                                              f"<b>Votes:</b> {deal['upvotes']} | <b>Comments:</b> {deal['comment_count']}"
                                        
                                        if self.notifier.send_message(msg, priority=False):
                                            self.db.log_alert(deal_id, "trending")
                                            print(f"[LiveMonitor] Sent Trending Alert: {deal['title']}")
                                        else:
                                            print(f"[LiveMonitor] Failed to send Trending Alert: {deal['title']}")

                            # --- Deal Stream Check ---
                            rows = page.locator("tbody#livebody tr").all()
                            recent_rows = rows[:20]
                            
                            for row in recent_rows:
                                try:
                                    type_str = row.locator("td:nth-child(5)").text_content().strip()
                                    if type_str != "Deal":
                                        continue
                                        
                                    subject_link_el = row.locator("td:nth-child(4) a")
                                    if subject_link_el.count() == 0: continue
                                    url = subject_link_el.get_attribute("href")
                                    title_text = subject_link_el.text_content().strip()
                                    
                                    if url.startswith("/"):
                                        url = f"https://www.ozbargain.com.au{url}"
                                    
                                    if url in self.seen_rows: continue
                                    self.seen_rows.add(url)
                                    
                                    time_str = row.locator("td:nth-child(1)").text_content().strip()
                                    timestamp = self.parse_relative_time(time_str).isoformat()
                                    user_str = row.locator("td:nth-child(2)").text_content().strip()
                                    
                                    action_el = row.locator("td:nth-child(3) i")
                                    action_str = action_el.get_attribute("title") or "Unknown"
                                    
                                    event_data = {
                                        "title": title_text,
                                        "original_url": url,
                                        "timestamp": timestamp,
                                        "time_str": time_str,
                                        "user": user_str,
                                        "action": action_str,
                                        "type": type_str
                                    }
                                    
                                    # Normalize URL: Strip /redir for deals, but KEEP for comments (leads to node)
                                    if "/node/" in url:
                                        if url.endswith("/redir"):
                                            url = url.replace("/redir", "")
                                        elif "/redir?" in url:
                                            url = url.replace("/redir?", "?")

                                    # Process deal (will handle priority alerts)
                                    self.process_deal(url, browser=browser, event_data=event_data)
                                    
                                except Exception as e:
                                    if "Target page, context or browser has been closed" in str(e):
                                        raise e # Trigger outer recovery
                                    pass

                        except Exception as loop_e:
                            if "Target page, context or browser has been closed" in str(loop_e):
                                raise loop_e
                            print(f"[LiveMonitor] Loop error: {loop_e}")
                        
                        time.sleep(self.poll_interval)
                        
            except Exception as e:
                print(f"[LiveMonitor] Fatal session error: {e}")
                print("[LiveMonitor] Restarting browser session in 15 seconds...")
                time.sleep(15)

if __name__ == "__main__":
    monitor = LiveMonitor()
    monitor.run()
