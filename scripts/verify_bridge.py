import os
import sys
from ozbargain.core.scraper import OzBargainScraper
from ozbargain.db.manager import StorageManager

def test_live_bridge():
    """Verifies that the core scraper can talk to the host Chrome."""
    cdp_url = "http://localhost:9224"
    print(f"[*] Checking CDP Connection to {cdp_url}...")
    
    scraper = OzBargainScraper(cdp_url=cdp_url)
    
    # Target a stable node
    test_node = "https://www.ozbargain.com.au/node/896662"
    
    try:
        print(f"[*] Attempting to scrape: {test_node}")
        # We manually bypass the goto timeout if needed or set it in the scraper
        result = scraper.scrape_deal_page(test_node)
        
        if "error" in result:
            print(f"[!] FAILED: {result['error']}")
            print("    Check if Chrome is running: ./manage.sh chrome")
            return
            
        print(f"[+] SUCCESS! Captured Title: {result.get('title')}")
        print(f"[+] Popularity: Upvotes={result.get('upvotes')}, Comments={result.get('comment_count')}")
        
    except Exception as e:
        print(f"[!] Unexpected Error: {str(e)}")

if __name__ == "__main__":
    test_live_bridge()
