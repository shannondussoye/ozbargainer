from ozbargain.core.scraper import BrowserScraper
from ozbargain.config import settings


def test_live_bridge():
    """Verifies that the core scraper can talk to the host Chrome."""
    cdp_url = settings.chrome_cdp_url
    if not cdp_url:
        print("[!] CHROME_CDP_URL is not configured. Set it in .env or environment.")
        return

    print(f"[*] Checking CDP Connection to {cdp_url}...")

    scraper = BrowserScraper(cdp_url=cdp_url)

    # Target a stable node
    test_node = f"{settings.ozbargain_base_url}/node/896662"

    try:
        print(f"[*] Attempting to scrape: {test_node}")
        result = scraper.scrape_deal_page(test_node)

        if result.has_error:
            print(f"[!] FAILED: {result.error}")
            print("    Check if Chrome is running: make start")
            return

        print(f"[+] SUCCESS! Captured Title: {result.title}")
        print(f"[+] Popularity: Upvotes={result.upvotes}, Comments={result.comment_count}")

    except Exception as e:
        print(f"[!] Unexpected Error: {str(e)}")


if __name__ == "__main__":
    test_live_bridge()
