import sqlite3
import os
import sys

# Add current dir to path to allow relative imports
sys.path.append(os.getcwd())

from ozbargain.core.scraper import OzBargainScraper
from ozbargain.db.manager import StorageManager

def recover_data():
    db = StorageManager()
    scraper = OzBargainScraper(headless=True)
    
    conn = db._get_connection()
    cursor = conn.cursor()
    
    # Find records with "www.ozbargain.com.au" as title (the noise we identified)
    cursor.execute("SELECT resolved_id, resolved_url FROM live_deals WHERE title = 'www.ozbargain.com.au' OR title = ''")
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
        if url.endswith("/redir"):
            url = url.replace("/redir", "")
        elif "/redir?" in url:
            url = url.replace("/redir?", "?")
            
        print(f"  [>] Processing {resolved_id} via {url}...")
        
        try:
            # Re-scrape using the full scraper logic
            deal_data = scraper.scrape_deal_page(url)
            
            if "error" in deal_data:
                print(f"    [!] Error scraping {resolved_id}: {deal_data['error']}")
                continue
                
            # Use upsert to fix the record
            db.upsert_live_deal(deal_data)
            
            # Check if title fixed
            if deal_data.get("title") not in ["OzBargain", "www.ozbargain.com.au"]:
                print(f"    [+] Successfully recovered title: {deal_data['title']}")
                recovered_count += 1
            else:
                print(f"    [?] Title still generic: {deal_data.get('title')}")
                
        except Exception as e:
            print(f"    [!!] Unexpected error for {resolved_id}: {e}")

    print(f"\n[*] Data recovery complete. Recovered {recovered_count}/{len(records)} records.")
    conn.close()

if __name__ == "__main__":
    recover_data()
