import re
import requests
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import random
import time
from typing import Optional

from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from playwright.sync_api import sync_playwright, Page

from ..utils.logger import setup_logger
from ..config import settings
from ..models import DealResult

logger = setup_logger("scraper")

# Titles that indicate a bot-wall / security challenge rather than real content
BOT_WALL_TITLES = frozenset({"OzBargain", "www.ozbargain.com.au", "Performing security verification"})

# Default User-Agent for FastScraper HTTP requests
_DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36"
)


def _build_retry_session() -> requests.Session:
    """Creates a requests.Session with retry strategy for resilient HTTP fetching."""
    session = requests.Session()
    session.headers["User-Agent"] = _DEFAULT_UA
    retry = Retry(
        total=5,
        backoff_factor=2,  # Wait 2s, 4s, 8s...
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "OPTIONS"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


class FastScraper:
    """
    Lightweight HTML parser using standard requests + BeautifulSoup.
    Extremely fast and low overhead (does not spawn Playwright/Chromium).
    """

    def __init__(self):
        self.base_url = settings.ozbargain_base_url
        self.session = _build_retry_session()

    def scrape_deal_fast(self, url: str) -> DealResult:
        """
        Fast version of scrape_deal_page using requests instead of Playwright.
        Much more efficient for mass scraping.
        """
        try:
            r = self.session.get(url, timeout=15)
            r.raise_for_status()
            html = r.text

            # Simple fallback ID extraction
            deal_id = "unknown"
            match = re.search(r"node/(\d+)", r.url)
            if match:
                deal_id = f"node/{match.group(1)}"

            soup = BeautifulSoup(html, "html.parser")

            # Title
            if soup.title and soup.title.string:
                title = soup.title.string.replace(" - OzBargain", "").strip()
            else:
                title = "Unknown Deal"

            # Description (Meta)
            description = ""
            meta_desc = soup.find("meta", property="og:description")
            if meta_desc:
                description = str(meta_desc.get("content", ""))

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
                except Exception:
                    logger.debug("Failed to split comment ID from URL: %s", r.url)
            elif "/comment/" in r.url:
                try:
                    # Clean query params if any
                    clean_url = r.url.split("?")[0]
                    part = clean_url.split("/comment/")[1]
                    # handle /redir or trailing slash
                    part = part.replace("/redir", "").replace("/", "")
                    linked_comment_id = f"comment-{part}"
                except Exception:
                    logger.debug("Failed to extract comment ID from resolved URL part: %s", r.url)

            # Fallback: Check input URL if resolved URL is weird
            if not linked_comment_id and "/comment/" in url:
                try:
                    clean_url = url.split("?")[0]
                    part = clean_url.split("/comment/")[1].split("/")[0]
                    linked_comment_id = f"comment-{part}"
                except Exception:
                    logger.debug("Failed to extract comment ID from fallback URL: %s", url)

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

            # Comment Count (from LD+JSON)
            comment_count = 0
            for script in soup.find_all("script", type="application/ld+json"):
                try:
                    data = json.loads(script.string or "")
                    if isinstance(data, list):
                        for item in data:
                            if isinstance(item, dict) and "commentCount" in item:
                                comment_count = int(item["commentCount"])
                                break
                    elif isinstance(data, dict):
                        if "commentCount" in data:
                            comment_count = int(data["commentCount"])
                            break
                except Exception:
                    pass

            return DealResult(
                id=deal_id,
                url=r.url,
                title=title,
                description=description,
                comment_count=comment_count,
                coupon_code=coupon,
                tags=tags,
                is_expired=is_expired,
                linked_comment=linked_comment,
                linked_comment_id=linked_comment_id,
                timestamp=datetime.now(timezone.utc),
                time_str=datetime.now(timezone.utc).astimezone(ZoneInfo("Australia/Sydney")).strftime("%H:%M"),
                user="Unknown",
                action="scraped",
                type="deal",
            )

        except Exception as e:
            return DealResult(error=str(e), url=url)


class BrowserScraper:
    """
    Playwright-based scraper for dynamic page interactions, infinite scroll,
    and bypassing bot protection/challenges.
    """

    def __init__(self, headless: bool = True, cdp_url: Optional[str] = None):
        self.headless = headless
        self.cdp_url = cdp_url or settings.chrome_cdp_url
        self.base_url = settings.ozbargain_base_url

    def setup_page_routing(self, page: Page) -> None:
        """
        Configure request interception to block images, fonts, media, and third-party ad/tracking domains.
        This significantly reduces memory footprint, CPU load, and loading time.
        """
        def route_handler(route):
            req = route.request
            url_lower = req.url.lower()

            # Block media/fonts
            if req.resource_type in ("image", "font", "media"):
                try:
                    route.abort()
                except Exception:
                    pass
                return

            # Block third-party ad and tracking domains
            blocked_patterns = [
                "googleads", "googlesyndication", "doubleclick",
                "taboola", "analytics", "facebook", "twitter",
                "amazon-adsystem", "scorecardresearch", "adnxs",
                "pubmatic", "rubiconproject", "openx", "adroll"
            ]
            if any(pattern in url_lower for pattern in blocked_patterns):
                try:
                    route.abort()
                except Exception:
                    pass
                return

            try:
                route.continue_()
            except Exception:
                pass

        try:
            page.route("**/*", route_handler)
        except Exception as e:
            logger.debug("Failed to set page routing: %s", e)

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

            logger.info("Loading profile: %s", base_user_url)
            try:
                page.goto(base_user_url, timeout=60000, wait_until="domcontentloaded")
                page.wait_for_selector("div.activities", timeout=15000)
            except Exception as e:
                logger.error("Error loading profile: %s", e)
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
                        text = (action_el.text_content() or "").strip()

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

                    except Exception as item_e:
                        logger.error("Error processing activity item: %s", item_e)
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
                        logger.info("Taking a breather at ~%d items...", count)
                        time.sleep(random.uniform(8.0, 15.0))

                    new_height = page.evaluate("document.body.scrollHeight")
                    if new_height == last_height:
                        retries += 1
                        logger.warning("No new items (Retry %d/10)...", retries)

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
                                    logger.info("Found 'Next' button. Clicking...")
                                    next_btn.click()
                                    time.sleep(3)
                                    retries = 0
                                    last_height = page.evaluate("document.body.scrollHeight")
                                    continue
                            except Exception as next_e:
                                logger.debug("Error checking or clicking next button: %s", next_e)

                        if retries >= 10:
                            logger.info("End of feed reached.")
                            break
                    else:
                        retries = 0
                        last_height = new_height

                except Exception as e:
                    if "TargetClosed" in str(e) or "closed" in str(e):
                        logger.warning("Browser window closed. Finalizing.")
                        break
                    logger.error("Error in user activity feed processing: %s", e)

            browser.close()

    def _human_scroll(self, page: Page, aggressive: bool = False):
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

        except Exception as scroll_e:
            logger.debug("Error during human scroll: %s", scroll_e)

    def _get_comment_count(self, page: Page, url: str) -> int:
        """
        Determines the total comment count, handling pagination if necessary.
        """
        # 1. Parse structured LD+JSON data (Fastest & Most Reliable)
        try:
            scripts = page.locator('script[type="application/ld+json"]').all_inner_texts()
            for content in scripts:
                if not content.strip():
                    continue
                try:
                    data = json.loads(content)
                    if isinstance(data, list):
                        for item in data:
                            if isinstance(item, dict) and "commentCount" in item:
                                return int(item["commentCount"])
                    elif isinstance(data, dict):
                        if "commentCount" in data:
                            return int(data["commentCount"])
                except Exception as json_e:
                    logger.debug("Failed to parse individual LD+JSON block: %s", json_e)
        except Exception as e:
            logger.debug("Failed to retrieve LD+JSON scripts: %s", e)

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
                    match = re.search(r"page=(\d+)", href)
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
                assert target_href is not None  # guaranteed by the loop above
                if target_href.startswith("?"):
                    clean_url = url.split("?")[0]
                    target_url = f"{clean_url}{target_href}"
                elif target_href.startswith("/"):
                    target_url = f"{self.base_url}{target_href}"
                else:
                    target_url = target_href

                # Navigate to last page
                page.goto(target_url, wait_until="domcontentloaded")
                page.wait_for_selector("div.comment", timeout=5000, state="attached")

                remainder = page.locator("div.comment").count()
                comment_count = base_count + remainder
                has_counted_via_dom = True
            except Exception as nav_e:
                logger.error("Error navigating to last page: %s", nav_e)
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
                text = (header.first.text_content() or "").strip()
                match = re.search(r"\((\d+)\)", text)
                if match:
                    comment_count = int(match.group(1))

        return comment_count

    def _extract_deal_data(self, page: Page, url: str) -> DealResult:
        """
        Internal helper to extract data from an open page.
        """
        result = DealResult(url=url)
        try:
            # Wait for load - sometimes OzBargain has a "click to continue" or similar? usually not.
            page.wait_for_load_state("domcontentloaded")

            # Resolve parent deal page if we are on a comment page
            if "/comment/" in page.url or "/comment/" in url:
                parent_selector = "h2.title a, div.node h2 a, ul.breadcrumb a, a[href^='/node/'], a[href*='/node/']"
                try:
                    page.wait_for_selector(parent_selector, timeout=3000)
                except Exception:
                    pass
                parent_link = page.locator(parent_selector).first
                if parent_link.count() > 0:
                    parent_url = parent_link.get_attribute("href") or ""
                    if parent_url:
                        if parent_url.startswith("/"):
                            parent_url = f"{settings.ozbargain_base_url}{parent_url}"
                        logger.info("Resolving comment URL %s to parent deal URL %s", page.url, parent_url)
                        page.goto(parent_url, wait_until="domcontentloaded")
                        page.wait_for_load_state("domcontentloaded")
                        url = parent_url

            # CANONICAL URL & ID RESOLUTION
            final_url = page.url
            if "?" in final_url:
                base, query = final_url.split("?", 1)
                params = [p for p in query.split("&") if not p.startswith("__cf_") and not p.startswith("cf_")]
                if params:
                    final_url = f"{base}?{'&'.join(params)}"
                else:
                    final_url = base

            # Extract canonical ID
            deal_id = None
            if "/node/" in final_url:
                parts = final_url.split("/node/")[-1].split("#")[0].split("?")[0]
                deal_id = f"node/{parts}"
            elif "/comment/" in final_url:
                # Attempt to find parent node link on the page
                # Breadcrumbs or Title link Usually: div.node-full h1 a or h2.title a
                parent_link = page.locator("h2.title a, div.node h2 a, ul.breadcrumb a, a[href^='/node/'], a[href*='/node/']").first
                if parent_link.count() > 0:
                    parent_url = parent_link.get_attribute("href") or ""
                    if "/node/" in parent_url:
                        node_id = parent_url.split("/node/")[-1].split("?")[0].split("#")[0]
                        deal_id = f"node/{node_id}"
                        # Also grab title if missing or noisy
                        if not result.title or result.title in BOT_WALL_TITLES:
                            result.title = (parent_link.text_content() or "").strip()

                # Fallback to comment ID if node not found
                if not deal_id:
                    parts = final_url.split("/comment/")[-1].split("/")[0].split("?")[0].split("#")[0]
                    deal_id = f"comment/{parts}"
            else:
                deal_id = final_url

            result.id = deal_id
            result.url = final_url

            # Handle External Redirects (Non-OzBargain)
            if "ozbargain.com.au" not in final_url:
                try:
                    og_title = page.locator('meta[property="og:title"]').get_attribute("content")
                    if og_title:
                        result.title = og_title
                    else:
                        result.title = page.title().split(" - ")[0]
                    # Tag as external
                    result.tags = ["External"]
                except Exception as ext_e:
                    logger.warning("Failed to scrape external redirect metadata: %s", ext_e)
                    result.title = f"External: {final_url}"
                return result

            # Handle Deep Linked Comment
            target_comment_id = None
            if "#comment-" in final_url:
                target_comment_id = final_url.split("#")[-1]
            elif "#comment-" in url:
                target_comment_id = url.split("#")[-1]

            if target_comment_id:
                result.linked_comment_id = target_comment_id
                # Selector for comment text: div#comment-id .content
                comment_el = page.locator(f"#{target_comment_id} .content")
                if comment_el.count() > 0:
                    result.linked_comment = (comment_el.text_content() or "").strip()

            # Title
            if page.locator("h1#title").count() > 0:
                result.title = (page.locator("h1#title").text_content() or "").strip()
            elif page.locator("h1").count() > 0:
                result.title = (page.locator("h1").first.text_content() or "").strip()

            # Expired Status
            result.is_expired = False
            # Check for "expired" span within the main node container
            node_el = page.locator("div.node").first
            if node_el.count() > 0 and node_el.locator("span:has-text('expired')").count() > 0:
                result.is_expired = True

            # Post-Extraction Cleanup: Title Noise
            if not result.title or result.title in BOT_WALL_TITLES:
                logger.warning(
                    "Bot-wall or empty title detected", extra={"event_type": "security_challenge", "challenge_type": "cloudflare"}
                )
                # Attempt to extract from h2 if h1 was generic
                h2_el = page.locator("h2").first
                if h2_el.count() > 0:
                    result.title = (h2_el.text_content() or "").strip()

                # If still empty or in BOT_WALL_TITLES, mark as error
                if not result.title or result.title in BOT_WALL_TITLES:
                    result.error = "Bot-wall block or empty page detected"

            # --- Posted Date & Domain ---
            submitted_loc = page.locator("div.submitted")
            if submitted_loc.count() > 0:
                # Use the first one (primary deal submission)
                primary_submitted = submitted_loc.first

                # 1. External Domain
                domain_link = primary_submitted.locator("a[href^='/goto/']")
                if domain_link.count() > 0:
                    result.external_domain = (domain_link.first.text_content() or "").strip()

                # 2. Posted Date
                submitted_text = (primary_submitted.text_content() or "").strip()
                # Pattern: "on 13/12/2025 - 09:30"
                match = re.search(r"on (\d{2}/\d{2}/\d{4} - \d{2}:\d{2})", submitted_text)
                if match:
                    result.posted_date = match.group(1)

            # Coupon Code
            if page.locator("div.couponcode").count() > 0:
                # Check for strong tags (usually the actual code)
                strong_codes = page.locator("div.couponcode strong").all()
                if strong_codes:
                    codes = [(el.text_content() or "").strip() for el in strong_codes]
                    result.coupon_code = ", ".join(codes)
                else:
                    result.coupon_code = (page.locator("div.couponcode").text_content() or "").strip()

            # Content / Description
            description_text = ""
            if page.locator("div.node-content").count() > 0:
                description_text = (page.locator("div.node-content").text_content() or "").strip()
            elif page.locator("div.content").count() > 0:
                description_text = (page.locator("div.content").first.text_content() or "").strip()

            # Clean description
            if result.coupon_code:
                code = result.coupon_code
                if description_text.startswith(code):
                    description_text = description_text[len(code) :].strip()
                else:
                    description_text = description_text.replace(code, "").strip()

            result.description = description_text

            # Tags
            tags = []
            # Updated to include categories, tags, and brands
            tag_links = page.locator(
                "div.taxonomy a[href^='/cat/'], div.taxonomy a[href^='/tag/'], div.taxonomy a[href^='/brand/']"
            ).all()
            for link in tag_links:
                tag_text = (link.text_content() or "").strip()
                if tag_text and tag_text not in tags:
                    tags.append(tag_text)
            result.tags = tags

            # Upvotes
            if page.locator("div.n-vote span.voteup span").count() > 0:
                try:
                    result.upvotes = int((page.locator("div.n-vote span.voteup span").first.text_content() or "0").strip())
                except Exception as vote_e:
                    logger.warning("Failed to parse upvotes: %s", vote_e)
                    result.upvotes = 0

            # Downvotes
            if page.locator("div.n-vote span.votedown span").count() > 0:
                try:
                    result.downvotes = int((page.locator("div.n-vote span.votedown span").first.text_content() or "0").strip())
                except Exception as vote_e:
                    logger.warning("Failed to parse downvotes: %s", vote_e)
                    result.downvotes = 0

            # Comment Count (delegated to helper)
            result.comment_count = self._get_comment_count(page, url)

            # Price
            if result.title:
                price_match = re.search(r"\$\d+(?:,\d+)*(?:\.\d+)?", result.title)
                if price_match:
                    result.price = price_match.group(0)

        except Exception as e:
            result.error = str(e)

        return result

    def scrape_deal_page(self, url: str, browser=None, timeout: int = 30000) -> DealResult:
        """
        Scrapes details from a specific deal or comment page.
        Supports connecting via CDP if self.cdp_url is set.
        """
        if browser:
            # Reuse active context (which shares cookies/session state) if available
            context = browser.contexts[0] if hasattr(browser, "contexts") and browser.contexts else browser
            page = context.new_page()
            self.setup_page_routing(page)
            try:
                page.goto(url, timeout=timeout, wait_until="domcontentloaded")
                return self._extract_deal_data(page, url)
            finally:
                page.close()

        with sync_playwright() as p:
            if self.cdp_url:
                logger.info("Connecting to Chrome via CDP: %s", self.cdp_url)
                try:
                    browser = p.chromium.connect_over_cdp(self.cdp_url)
                    page = browser.new_page()
                    self.setup_page_routing(page)
                    page.goto(url, timeout=timeout, wait_until="domcontentloaded")
                    result = self._extract_deal_data(page, url)
                    browser.close()
                    return result
                except Exception as e:
                    return DealResult(error=f"CDP Connection failed: {str(e)}", url=url)
            else:
                browser = p.chromium.launch(headless=self.headless)
                page = browser.new_page()
                self.setup_page_routing(page)
                page.goto(url, timeout=timeout, wait_until="domcontentloaded")

                result = self._extract_deal_data(page, url)

                browser.close()
                return result
