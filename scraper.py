
import re
import requests
from datetime import datetime
import random
import time
from typing import List, Dict, Optional
from playwright.sync_api import sync_playwright, Page, ElementHandle

class OzBargainScraper:
    def __init__(self, headless: bool = True):
        self.headless = headless
        self.base_url = "https://www.ozbargain.com.au"


    def get_user_activity(self, user_id: str, max_items: int = 50):
        """
        Scrapes user activity using Infinite Scroll (Guest Mode).
        Generates items as they are found.
        """
        base_user_url = f"{self.base_url}/user/{user_id}"
        count = 0
        items_seen = set()
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            page = browser.new_page()
            
            print(f"[Scraper] Loading profile: {base_user_url}")
            try:
                page.goto(base_user_url, timeout=60000)
                page.wait_for_selector("div.activities", timeout=15000)
            except Exception as e:
                print(f"[Scraper] Error loading profile: {e}")
                browser.close()
                return

            last_height = page.evaluate("document.body.scrollHeight")
            retries = 0
            
            while count < max_items:
                # 1. Yield visible items
                # We re-query all items because the list grows. 
                # Optimization: In heavy infinite scroll, scraping 1000 items from DOM repeatedly is slow.
                # However, Playwright locator.all() is reasonably fast for 100s.
                divs = page.locator("div.activities > div").all()
                
                for item in divs:
                    if count >= max_items: 
                        break
                    
                    try:
                        # Check structure
                        if item.locator(".right .action").count() == 0: 
                            continue
                            
                        action_el = item.locator(".right .action")
                        text = action_el.text_content().strip()
                        
                        # Filter types
                        if not ("replied to" in text or "commented on" in text or "posted" in text): 
                            continue
                        
                        # Link
                        links = action_el.locator("a").all()
                        if not links: 
                            continue
                            
                        # Last link usually deal/comment
                        href = links[-1].get_attribute("href")
                        if not href: 
                            continue
                            
                        full_url = self.base_url + href if href.startswith("/") else href
                        
                        if full_url in items_seen: 
                            continue
                            
                        items_seen.add(full_url)
                        count += 1
                        
                        yield {"text": text, "url": full_url}
                        
                    except: 
                        continue

                if count >= max_items:
                    break
                
                # 2. Scroll and Wait (Humanized & Slower)
                try:
                    self._human_scroll(page)
                    
                    # Wait for load (Randomized & Slower)
                    time.sleep(random.uniform(3.0, 6.0))
                    
                    # Periodic Breather (every ~300 items)
                    if count > 0 and (count // 300) > ((count - 10) // 300):
                         print(f"[Scraper] Taking a breather at ~{count} items...")
                         time.sleep(random.uniform(8.0, 15.0))
                    
                    new_height = page.evaluate("document.body.scrollHeight")
                    if new_height == last_height:
                        retries += 1
                        print(f"[Scraper] No new items (Retry {retries}/10)...")
                        
                        if retries > 3:
                             # Aggressive Jiggle
                             self._human_scroll(page, aggressive=True)
                             time.sleep(2)
                        
                        # Fallback to check for button if really stuck
                        if retries > 5:
                             try:
                                # Look for ANY "next" or "load more" indicator
                                next_btn = page.locator("ul.pager li.pager-next a").first
                                if next_btn.is_visible():
                                    print("[Scraper] Found 'Next' button. Clicking...")
                                    next_btn.click()
                                    time.sleep(3)
                                    retries = 0
                                    last_height = page.evaluate("document.body.scrollHeight")
                                    continue
                             except: pass

                        if retries >= 10:
                            print("[Scraper] End of feed reached.")
                            break
                    else:
                        retries = 0
                        last_height = new_height
                        
                except Exception as e:
                    if "TargetClosed" in str(e) or "closed" in str(e):
                         print("[Scraper] Browser window closed. Finalizing.")
                         break
                    pass
                    
            browser.close()

    def _human_scroll(self, page: Page, aggressive=False):
        """
        Simulates human scrolling using mouse wheel and movement.
        """
        try:
            # Random mouse movement
            page.mouse.move(random.randint(100, 500), random.randint(100, 500))
            
            if aggressive:
                # Scroll UP first
                page.mouse.wheel(0, -1000)
                time.sleep(0.5)
                # Fast heavy scroll down
                steps = 10
                for _ in range(steps):
                    page.mouse.wheel(0, 1000)
                    time.sleep(random.uniform(0.05, 0.1))
            else:
                # Normal read-like scroll (Slower)
                # Scroll in chunks
                steps = random.randint(3, 6)
                for _ in range(steps):
                    scroll_amount = random.randint(300, 800)
                    page.mouse.wheel(0, scroll_amount)
                    # Micro-pause between wheel flicks (Slower to simulate reading/tracking)
                    time.sleep(random.uniform(0.5, 1.2))
                    
            # Move mouse again to trigger hover effects
            page.mouse.move(random.randint(100, 800), random.randint(100, 800))
            
        except Exception as e:
            pass

    def _get_comment_count(self, page: Page, url: str) -> int:
        """
        Determines the total comment count, handling pagination if necessary.
        """
        comment_count = 0
        has_counted_via_dom = False
        
        # 1. Check for Pagination (Exact Count Strategy)
        # Scan all pager links to find the max 'page=X' index
        pager_links = page.locator("ul.pager a")
        max_page_idx = -1
        target_href = None
        
        if pager_links.count() > 0:
            for i in range(pager_links.count()):
                href = pager_links.nth(i).get_attribute("href")
                if href:
                    match = re.search(r'page=(\d+)', href)
                    if match:
                        idx = int(match.group(1))
                        if idx > max_page_idx:
                            max_page_idx = idx
                            target_href = href

        if max_page_idx > -1:
            # Found a multi-page thread
            base_count = max_page_idx * 100
            
            try:
                # Construct absolute URL for last page
                if target_href.startswith("?"):
                     clean_url = url.split("?")[0]
                     target_url = f"{clean_url}{target_href}"
                elif target_href.startswith("/"):
                     target_url = f"https://www.ozbargain.com.au{target_href}"
                else:
                     target_url = target_href

                # Navigate to last page
                page.goto(target_url)
                page.wait_for_selector("div.comment", timeout=5000) 
                
                remainder = page.locator("div.comment").count()
                comment_count = base_count + remainder
                has_counted_via_dom = True
            except Exception as nav_e:
                print(f"Error navigating to last page: {nav_e}")
                comment_count = base_count 
        
        # 2. Single Page Count (Fallback or Default)
        if not has_counted_via_dom:
            dom_count = page.locator("div.comment").count()
            if dom_count > 0:
                comment_count = dom_count
                has_counted_via_dom = True

        # 3. Last Resort: Text Search
        if not has_counted_via_dom or comment_count == 0:
             # Scope to the main deal node if possible
            deal_containter = page.locator("div.node-full").first
            if deal_containter.count() == 0:
                 deal_containter = page.locator("div.node").first
            if deal_containter.count() == 0:
                deal_containter = page.locator("body") 

            # Try Header "Comments (178)"
            header = page.locator("h2#comments") 
            if header.count() == 0:
                 header = page.locator("h2:has-text('Comments')")
            
            if header.count() > 0:
                text = header.first.text_content().strip()
                match = re.search(r'\((\d+)\)', text)
                if match:
                    comment_count = int(match.group(1))
                    
        return comment_count

    def scrape_deal_fast(self, url: str) -> Dict:
        """
        Fast version of scrape_deal_page using requests instead of Playwright.
        Much more efficient for mass scraping.
        """
        try:
            # Setup Retry Strategy for Stability
            from requests.adapters import HTTPAdapter
            from urllib3.util.retry import Retry
            
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36"
            }
            
            session = requests.Session()
            retry = Retry(
                total=5, 
                backoff_factor=2, # Wait 2s, 4s, 8s...
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=["HEAD", "GET", "OPTIONS"]
            )
            adapter = HTTPAdapter(max_retries=retry)
            session.mount("https://", adapter)
            session.mount("http://", adapter)
            
            # Use session with retries
            r = session.get(url, headers=headers, timeout=15)
            r.raise_for_status()
            html = r.text
            
            # Simple fallback ID extraction
            deal_id = "unknown"
            match = re.search(r'node/(\d+)', r.url)
            if match:
                deal_id = f"node/{match.group(1)}"
            
            # BS4 Extraction
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            
            # Title
            if soup.title:
                title = soup.title.string.replace(" - OzBargain", "").strip()
            else:
                title = "Unknown Deal"
            
            # Description (Meta)
            description = ""
            meta_desc = soup.find("meta", property="og:description")
            if meta_desc:
                description = meta_desc.get("content", "")
            
            # Coupon
            coupon = None
            coupon_el = soup.find(class_="couponcode")
            if coupon_el:
                coupon = coupon_el.get_text(strip=True)
                
            # Tags
            tags = [a.get_text(strip=True) for a in soup.select("div.taxonomy a")]
            
            # Linked Comment
            linked_comment = None
            linked_comment_id = None
            
            # Extract Comment ID from Resolved URL
            # Format 1: /node/123#comment-456
            # Format 2: /comment/456
            
            if "#comment-" in r.url:
                try:
                    linked_comment_id = r.url.split("#comment-")[1]
                    linked_comment_id = f"comment-{linked_comment_id}"
                except: pass
            elif "/comment/" in r.url:
                try:
                    # Clean query params if any
                    clean_url = r.url.split("?")[0]
                    part = clean_url.split("/comment/")[1]
                    # handle /redir or trailing slash
                    part = part.replace("/redir", "").replace("/", "")
                    linked_comment_id = f"comment-{part}"
                except: pass
            
            # Fallback: Check input URL if resolved URL is weird
            if not linked_comment_id and "/comment/" in url:
                try:
                     clean_url = url.split("?")[0]
                     part = clean_url.split("/comment/")[1].split("/")[0]
                     linked_comment_id = f"comment-{part}"
                except: pass

            if linked_comment_id:
                # Find the specific comment div
                # <div id="comment-123456" ... > <div class="content"> ... </div> </div>
                comment_div = soup.find("div", id=linked_comment_id)
                if comment_div:
                    content_div = comment_div.find("div", class_="content")
                    if content_div:
                        # Get text, preserving structure slightly with ' ' separator
                        linked_comment = content_div.get_text(" ", strip=True)
            
            # Expired?
            is_expired = soup.find(class_="expired") is not None or soup.select_one(".node-expired") is not None

            return {
                "id": deal_id,
                "url": r.url,
                "title": title,
                "description": description,
                "price": "", 
                "coupon_code": coupon,
                "tags": tags,
                "upvotes": 0,
                "downvotes": 0,
                "comment_count": 0, # Not parsing count in fast mode
                "timestamp": datetime.now(),
                "time_str": datetime.now().strftime("%H:%M"),
                "user": "Unknown",
                "action": "scraped",
                "type": "deal",
                "is_expired": is_expired,
                "linked_comment": linked_comment,
                "linked_comment_id": linked_comment_id,
                "posted_date": "",
                "external_domain": ""
            }
            
        except Exception as e:
            return {"error": str(e), "url": url}

    def _extract_deal_data(self, page, url) -> Dict:
        """
        Internal helper to extract data from an open page.
        """
        data = {"url": url}
        try:
            # Wait for load - sometimes OzBargain has a "click to continue" or similar? usually not.
            page.wait_for_load_state("domcontentloaded")
            
            # CANONICAL URL & ID RESOLUTION
            final_url = page.url
            
            # Extract canonical ID
            deal_id = None
            if "/node/" in final_url:
                parts = final_url.split("/node/")[-1].split("#")[0].split("?")[0]
                deal_id = f"node/{parts}"
            elif "/comment/" in final_url: 
                parts = final_url.split("/comment/")[-1].split("/")[0]
                deal_id = f"comment/{parts}"
            else:
                deal_id = final_url
            
            data["id"] = deal_id
            data["url"] = final_url 

            # Handle Deep Linked Comment
            target_comment_id = None
            if "#comment-" in final_url:
                target_comment_id = final_url.split("#")[-1]
            elif "#comment-" in url: 
                target_comment_id = url.split("#")[-1]

            if target_comment_id:
                data["linked_comment_id"] = target_comment_id
                # Selector for comment text: div#comment-id .content
                comment_el = page.locator(f"#{target_comment_id} .content")
                if comment_el.count() > 0:
                    data["linked_comment"] = comment_el.text_content().strip()
            
            # Title
            if page.locator("h1#title").count() > 0:
                data["title"] = page.locator("h1#title").text_content().strip()
            elif page.locator("h1").count() > 0:
                    data["title"] = page.locator("h1").first.text_content().strip()
            
            # Expired Status (New)
            data["is_expired"] = False
            # Check for "expired" span within the main node container
            if page.locator("div.node").first.locator("span:has-text('expired')").count() > 0:
                data["is_expired"] = True
            
            # --- New Fields: Posted Date & Domain ---
            submitted_loc = page.locator("div.submitted")
            if submitted_loc.count() > 0:
                # Use the first one (primary deal submission)
                primary_submitted = submitted_loc.first
                
                # 1. External Domain
                domain_link = primary_submitted.locator("a[href^='/goto/']")
                if domain_link.count() > 0:
                    data["external_domain"] = domain_link.first.text_content().strip()
                
                # 2. Posted Date
                submitted_text = primary_submitted.text_content().strip()
                # Pattern: "on 13/12/2025 - 09:30"
                match = re.search(r'on (\d{2}/\d{2}/\d{4} - \d{2}:\d{2})', submitted_text)
                if match:
                    data["posted_date"] = match.group(1)
            
            # Coupon Code
            if page.locator("div.couponcode").count() > 0:
                # Check for strong tags (usually the actual code)
                strong_codes = page.locator("div.couponcode strong").all()
                if strong_codes:
                    codes = [el.text_content().strip() for el in strong_codes]
                    data["coupon_code"] = ", ".join(codes)
                else:
                    data["coupon_code"] = page.locator("div.couponcode").text_content().strip()
            
            # Content / Description
            description_text = ""
            if page.locator("div.node-content").count() > 0:
                description_text = page.locator("div.node-content").text_content().strip()
            elif page.locator("div.content").count() > 0:
                description_text = page.locator("div.content").first.text_content().strip()
            
            # Clean description
            if "coupon_code" in data and data["coupon_code"]:
                code = data["coupon_code"]
                if description_text.startswith(code):
                    description_text = description_text[len(code):].strip()
                else:
                        description_text = description_text.replace(code, "").strip()
            
            data["description"] = description_text
            
            # Tags
            tags = []
            # Updated to include categories, tags, and brands
            tag_links = page.locator("div.taxonomy a[href^='/cat/'], div.taxonomy a[href^='/tag/'], div.taxonomy a[href^='/brand/']").all()
            for link in tag_links:
                    tag_text = link.text_content().strip()
                    if tag_text and tag_text not in tags:
                        tags.append(tag_text)
            data["tags"] = tags
            
            # Upvotes
            if page.locator("div.n-vote span.voteup span").count() > 0:
                    try:
                        data["upvotes"] = int(page.locator("div.n-vote span.voteup span").first.text_content().strip())
                    except:
                        data["upvotes"] = 0
            else:
                data["upvotes"] = 0
                
            # Downvotes
            if page.locator("div.n-vote span.votedown span").count() > 0:
                    try:
                        data["downvotes"] = int(page.locator("div.n-vote span.votedown span").first.text_content().strip())
                    except:
                        data["downvotes"] = 0
            else:
                data["downvotes"] = 0

            # Comment Count (delegated to helper)
            data["comment_count"] = self._get_comment_count(page, url)

            # Price
            if "title" in data:
                price_match = re.search(r'\$\d+(?:,\d+)*(?:\.\d+)?', data["title"])
                if price_match:
                    data["price"] = price_match.group(0)
                    
        except Exception as e:
            data["error"] = str(e)
            
        return data

    def scrape_deal_page(self, url: str, browser=None) -> Dict:
        """
        Scrapes details from a specific deal or comment page.
        If browser is provided, uses it to open a new page.
        Otherwise, launches a new browser instance.
        """
        if browser:
            page = browser.new_page()
            try:
                page.goto(url)
                return self._extract_deal_data(page, url)
            finally:
                page.close()
        else:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=self.headless)
                page = browser.new_page()
                page.goto(url)
                
                result = self._extract_deal_data(page, url)
                
                browser.close()
                return result

if __name__ == "__main__":
    # Internal simple test
    scraper = OzBargainScraper(headless=False) # Visibile for debugging if run manually
    print("Scraper initialized.")
