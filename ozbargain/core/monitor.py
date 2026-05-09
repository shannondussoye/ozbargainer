import os
import time
from playwright.sync_api import sync_playwright
from .scraper import OzBargainScraper
from ..db.manager import StorageManager
from ..notifier.telegram import TelegramNotifier
from datetime import datetime, timedelta
import re
import random
import requests
from typing import Dict, Optional
from ..utils.logger import setup_logger

logger = setup_logger("monitor")

class LiveMonitor:
    def __init__(self):
        self.db = StorageManager()
        self.cdp_url = os.getenv("CHROME_CDP_URL")
        if self.cdp_url:
            from urllib.parse import urlparse
            parsed_url = urlparse(self.cdp_url)
            if parsed_url.hostname not in ["127.0.0.1", "localhost"]:
                raise ValueError(f"CRITICAL: CDP URL must bind to localhost/127.0.0.1 to prevent RCE. Got: {parsed_url.hostname}")
        self.scraper = OzBargainScraper(headless=True, cdp_url=self.cdp_url)
        self.notifier = TelegramNotifier()
        self.seen_rows = set() # Cache to avoid re-processing simple rows in same session
        self.last_scraped_times = {} # url -> datetime
        
        # Configuration from Environment
        self.min_heat_score = int(os.getenv("MIN_HEAT_SCORE", 60))
        self.trending_check_interval = int(os.getenv("TRENDING_CHECK_INTERVAL", 30)) # Minutes
        self.poll_interval = int(os.getenv("POLL_INTERVAL", 5)) # Seconds
        self.scrape_cooldown = int(os.getenv("SCRAPE_COOLDOWN_SECONDS", 120)) # 2 mins
        self.healthcheck_url = os.getenv("HEALTHCHECK_PING_URL")

    def process_deal(self, url: str, browser=None, event_data: Dict = None, timeout: int = 30000) -> (Optional[str], Optional[str]):
        """
        Processes a deal URL: Scrape -> Merge -> Upsert
        """
        # Scrape
        deal_data = self.scraper.scrape_deal_page(url, browser=browser, timeout=timeout)
        
        if "error" in deal_data:
            logger.error("Error scraping %s: %s", url, deal_data['error'])
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
                  logger.info("Resolved comment %s to parent node %s", deal_id, parent_id)
                  deal_id = parent_id
                  deal_data["id"] = deal_id
        
        # Final Upsert
        deal_id = self.db.upsert_live_deal(deal_data)
        
        # --- Priority Alerts ---
        try:
            # Skip if expired
            if deal_data.get("is_expired"):
                logger.info("Skipping alerts for Expired Deal: %s", deal_id)
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
                        logger.info("Sent Alert for tags: %s", matches, extra={"event_type": "notification", "priority": "high"})
                    else:
                        logger.error("Failed to send Alert for tags: %s", matches)
                else:
                    logger.info("Skip Alert (Already Sent): %s", matches)
        except Exception as e:
            logger.error("Error checking alerts: %s", e)

        # Log 
        title_sample = deal_data.get("title", "No Title")[:50]
        logger.info("Upserted Deal: %s - %s", deal_id, title_sample)
        
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

    def ping_healthcheck(self):
        """Sends a heartbeat to Healthchecks.io if configured."""
        if not self.healthcheck_url:
            return
        try:
            requests.get(self.healthcheck_url, timeout=10)
        except Exception as e:
            logger.error("Healthcheck ping failed: %s", e)

    def run(self):
        logger.info("Starting Live Monitor...", extra={"event_type": "startup"})
        last_trending_check = datetime.now() - timedelta(minutes=self.trending_check_interval)
        
        while True:
            logger.info("Initializing browser session...")
            try:
                with sync_playwright() as p:
                    if self.cdp_url:
                        logger.info("Connecting to Chrome via CDP: %s", self.cdp_url)
                        try:
                            browser = p.chromium.connect_over_cdp(self.cdp_url)
                        except Exception as cdp_e:
                            logger.warning("CDP Connection failed: %s. Falling back to local browser.", cdp_e)
                            browser = p.chromium.launch(headless=True)
                    else:
                        logger.info("Launching local browser...")
                        browser = p.chromium.launch(headless=True)
                    
                    page = browser.new_page()
                    
                    logger.info("Navigating to /live...")
                    page.goto("https://www.ozbargain.com.au/live", timeout=60000, wait_until="domcontentloaded")
                    page.wait_for_selector("tbody#livebody", timeout=30000)
                    
                    # Setup Filters: Uncheck Wiki
                    logger.info("Configuring filters...")
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
                    
                    logger.info("Filters configured. Listening for updates...")
                    
                    last_success_time = datetime.now()
                    session_start_time = datetime.now()
                    
                    while True:
                        # Periodic session refresh (every 4 hours)
                        if datetime.now() - session_start_time > timedelta(hours=4):
                            logger.info("Periodic session refresh (4h limit reached).")
                            break

                        try:
                            # --- Trending Check ---
                            if datetime.now() - last_trending_check > timedelta(minutes=self.trending_check_interval):
                                logger.info("Performing scheduled trending deals check...")
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
                                            logger.info("Sent Trending Alert: %s", deal['title'], extra={"event_type": "notification", "priority": "normal"})
                                        else:
                                            logger.error("Failed to send Trending Alert: %s", deal['title'])

                            # --- Deal Stream Check ---
                            rows = page.locator("tbody#livebody tr").all()
                            
                            # Stale Session Detection
                            if rows:
                                last_success_time = datetime.now()
                            elif datetime.now() - last_success_time > timedelta(minutes=10):
                                logger.warning("No rows seen for 10 minutes. Session may be stale/blocked. Restarting...")
                                break

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
                                    
                                    time_str = row.locator("td:nth-child(1)").text_content().strip()
                                    user_str = row.locator("td:nth-child(2)").text_content().strip()
                                    action_el = row.locator("td:nth-child(3) i")
                                    action_str = action_el.get_attribute("title") or "Unknown"
                                    
                                    # Track unique /live rows by composite key
                                    row_key = f"{time_str}|{user_str}|{action_str}|{url}"
                                    if row_key in self.seen_rows: continue
                                    self.seen_rows.add(row_key)
                                    
                                    timestamp = self.parse_relative_time(time_str).isoformat()
                                    
                                    event_data = {
                                        "title": title_text,
                                        "original_url": url,
                                        "timestamp": timestamp,
                                        "time_str": time_str,
                                        "user": user_str,
                                        "action": action_str,
                                        "type": type_str
                                    }
                                    
                                    if "/node/" in url:
                                        if url.endswith("/redir"):
                                            url = url.replace("/redir", "")
                                        elif "/redir?" in url:
                                            url = url.replace("/redir?", "?")

                                    # --- Rate Limiting / Cooldown ---
                                    now_time = datetime.now()
                                    # Smart Cooldown: Use Node ID or Title to prevent re-scraping same deal via different events
                                    cooldown_key = url
                                    if "/node/" in url:
                                        node_match = re.search(r'node/(\d+)', url)
                                        if node_match:
                                            cooldown_key = f"node/{node_match.group(1)}"
                                    elif "/comment/" in url:
                                        # For comments, use the title as a grouping key
                                        # This prevents multiple comments on the same deal from triggering multiple scrapes
                                        cooldown_key = f"title/{title_text[:50]}"
                                    
                                    last_scraped = self.last_scraped_times.get(cooldown_key)
                                    
                                    if last_scraped and (now_time - last_scraped).total_seconds() < self.scrape_cooldown:
                                        # Only log skip if it's a node/title ID or if we haven't logged it too much
                                        if random.random() < 0.1: # 10% chance to log skip to avoid spam
                                            logger.info("Skip re-scrape (Cooldown): %s", cooldown_key)
                                        continue 
                                        
                                    self.last_scraped_times[cooldown_key] = now_time
                                    self.process_deal(url, browser=browser, event_data=event_data, timeout=15000)

                                    
                                except Exception as e:
                                    if "Target page, context or browser has been closed" in str(e):
                                        raise e 
                                    logger.error("Row processing error: %s", e)
                                    pass

                            # --- Housekeeping ---
                            if len(self.last_scraped_times) > 1000:
                                cutoff = datetime.now() - timedelta(hours=1)
                                self.last_scraped_times = {k: v for k, v in self.last_scraped_times.items() if v > cutoff}
                                
                        except Exception as loop_e:
                            if "Target page, context or browser has been closed" in str(loop_e):
                                raise loop_e
                            logger.error("Inner loop error: %s", loop_e)
                        
                        self.ping_healthcheck()
                        time.sleep(self.poll_interval)
                    
                    browser.close()
                        
            except Exception as e:
                logger.error("Fatal session error: %s", e)
                logger.info("Restarting browser session in 15 seconds...")
                time.sleep(15)

if __name__ == "__main__":
    monitor = LiveMonitor()
    monitor.run()

