from ozbargain.core.scraper import BrowserScraper
from ozbargain.db.manager import StorageManager
from ozbargain.utils.urls import normalize_deal_url
from ozbargain.core.scraper import BOT_WALL_TITLES


def recover_data():
    db = StorageManager()
    scraper = BrowserScraper(headless=True)

    records = db.get_noisy_records()

    if not records:
        print("[*] No noisy records found to recover.")
        return

    print(f"[*] Found {len(records)} records requiring recovery. Starting re-scrape...")

    recovered_count = 0
    for record in records:
        resolved_id = record["resolved_id"]
        resolved_url = record["resolved_url"]

        # Apply normalization if missing in the logged URL
        url = normalize_deal_url(resolved_url)

        print(f"  [>] Processing {resolved_id} via {url}...")

        try:
            # Re-scrape using the full scraper logic
            deal = scraper.scrape_deal_page(url)

            if deal.has_error:
                print(f"    [!] Error scraping {resolved_id}: {deal.error}")
                continue

            # Use upsert to fix the record
            db.upsert_live_deal(deal)

            # Check if title fixed
            if deal.title not in BOT_WALL_TITLES:
                print(f"    [+] Successfully recovered title: {deal.title}")
                recovered_count += 1
            else:
                print(f"    [?] Title still generic: {deal.title}")

        except Exception as e:
            print(f"    [!!] Unexpected error for {resolved_id}: {e}")

    print(f"\n[*] Data recovery complete. Recovered {recovered_count}/{len(records)} records.")


if __name__ == "__main__":
    recover_data()
