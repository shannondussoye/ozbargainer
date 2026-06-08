from ozbargain.core.scraper import BrowserScraper
from ozbargain.db.manager import StorageManager
from ozbargain.utils.urls import normalize_deal_url
from ozbargain.core.scraper import BOT_WALL_TITLES


def recover_data():
    db = StorageManager()
    scraper = BrowserScraper(headless=True)

    conn = db._get_connection()
    cursor = conn.cursor()

    # Find records with "www.ozbargain.com.au" as title (the noise we identified)
    cursor.execute(
        "SELECT resolved_id, resolved_url FROM live_deals WHERE title = 'www.ozbargain.com.au' OR title = ''"
    )
    records = cursor.fetchall()

    if not records:
        print("[*] No noisy records found to recover.")
        conn.close()
        return

    print(f"[*] Found {len(records)} records requiring recovery. Starting re-scrape...")

    recovered_count = 0
    for resolved_id, resolved_url in records:
        url = resolved_url
        # Apply normalization if missing in the logged URL
        url = normalize_deal_url(url)

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
    conn.close()


if __name__ == "__main__":
    recover_data()
