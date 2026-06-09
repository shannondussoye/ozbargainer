#!/usr/bin/env python3
"""
chrome_tab_audit.py — Audit open tabs in all Chrome CDP debugging sessions.

Usage:
    python scripts/chrome_tab_audit.py
    python scripts/chrome_tab_audit.py --close-stale   # Close non-essential tabs
    python scripts/chrome_tab_audit.py --port 9228     # Single port only

This script queries the Chrome DevTools Protocol (CDP) /json endpoint on each
known debugging port and prints a summary of open tabs. Run it any time you
suspect a tab leak or want to understand Chrome memory usage.
"""
import argparse
import sys
try:
    import requests
except ImportError:
    print("ERROR: 'requests' not installed. Run: pip install requests")
    sys.exit(1)

# All known CDP ports used by scrapers on this host
DEFAULT_PORTS = {
    9222: "Realestate Rent",
    9223: "Realestate Buy",
    9228: "OzBargain Monitor",
    9300: "Hotcopper",
}

# URLs that are expected / should never be closed
SAFE_URL_FRAGMENTS = [
    "ozbargain.com.au/live",
    "realestate.com.au",
    "hotcopper.com.au",
    "about:blank",
    "chrome://newtab",
]


def audit_port(port: int, label: str, close_stale: bool = False) -> dict:
    url = f"http://127.0.0.1:{port}/json"
    try:
        resp = requests.get(url, timeout=3)
        resp.raise_for_status()
        tabs = resp.json()
    except requests.ConnectionError:
        print(f"\n  ⚠️  Port {port} ({label}): NOT RUNNING")
        return {"port": port, "label": label, "status": "offline", "tabs": []}
    except Exception as e:
        print(f"\n  ⚠️  Port {port} ({label}): ERROR — {e}")
        return {"port": port, "label": label, "status": "error", "tabs": []}

    pages = [t for t in tabs if t.get("type") == "page"]
    iframes = [t for t in tabs if t.get("type") == "iframe"]
    other = [t for t in tabs if t.get("type") not in ("page", "iframe")]

    print(f"\n{'='*60}")
    print(f"  Port {port} — {label}")
    print(f"  {'='*58}")
    print(f"  Total targets : {len(tabs)}")
    print(f"  Pages         : {len(pages)}")
    print(f"  iframes       : {len(iframes)}")
    print(f"  Other         : {len(other)}")
    print()

    stale = []
    for tab in pages:
        tab_url = tab.get("url", "")
        is_safe = any(f in tab_url for f in SAFE_URL_FRAGMENTS)
        tag = "✅" if is_safe else "⚠️  STALE"
        print(f"    {tag}  [{tab['type']}] {tab_url[:70]}")
        if not is_safe:
            stale.append(tab)

    if iframes:
        # Summarise iframe domains rather than listing all
        from urllib.parse import urlparse
        domains = {}
        for t in iframes:
            d = urlparse(t.get("url", "")).netloc
            domains[d] = domains.get(d, 0) + 1
        print("\n    iframes by domain:")
        for domain, count in sorted(domains.items(), key=lambda x: -x[1]):
            print(f"      {count:3d}x  {domain}")

    if close_stale and stale:
        print(f"\n  🔴 Closing {len(stale)} stale page(s)...")
        for tab in stale:
            close_url = f"http://127.0.0.1:{port}/json/close/{tab['id']}"
            try:
                r = requests.get(close_url, timeout=3)
                status = "closed" if r.status_code == 200 else f"status {r.status_code}"
            except Exception as e:
                status = f"error: {e}"
            print(f"      [{status}] {tab.get('url', '')[:70]}")

    return {
        "port": port, "label": label, "status": "online",
        "total": len(tabs), "pages": len(pages),
        "iframes": len(iframes), "stale": len(stale),
    }


def main():
    parser = argparse.ArgumentParser(description="Audit Chrome CDP tabs across all scraper ports.")
    parser.add_argument("--port", type=int, help="Only audit a single CDP port.")
    parser.add_argument("--close-stale", action="store_true", help="Close stale (non-essential) tabs via CDP.")
    args = parser.parse_args()

    ports = {args.port: "Custom"} if args.port else DEFAULT_PORTS

    print("Chrome Tab Audit")
    print("=" * 60)

    results = []
    for port, label in ports.items():
        result = audit_port(port, label, close_stale=args.close_stale)
        results.append(result)

    # Summary
    online = [r for r in results if r.get("status") == "online"]
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    total_tabs = sum(r.get("total", 0) for r in online)
    total_stale = sum(r.get("stale", 0) for r in online)
    print(f"  Chrome sessions online  : {len(online)}/{len(results)}")
    print(f"  Total open targets      : {total_tabs}")
    print(f"  Stale page tabs         : {total_stale}")
    if total_stale > 0 and not args.close_stale:
        print(f"\n  💡 Run with --close-stale to forcibly close {total_stale} stale tab(s).")
    print()


if __name__ == "__main__":
    main()
