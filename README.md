# OzBargain Monitor & Scraper

A Python-based toolkit for monitoring live deals on [OzBargain](https://www.ozbargain.com.au), tracking trend velocity, establishing watched tag alerts, and scraping user activity. The system uses a combination of `playwright` for dynamic content parsing (like infinite scrolls and live feeds) and `requests`/`beautifulsoup4` for fast, concurrent fetching.

## 🏗 Architecture & Components

The application saves all data to a local SQLite database (`ozbargain.db`) and integrates with Telegram for real-time priority alerts and trending deal notifications.

### Key Files
* **`live_monitor.py`**: The main persistent service. It opens a Playwright instance to watch the OzBargain `/live` feed (filtered to Deals), polling every few seconds for new items. Upon detecting a new deal, it scrapes the context, saves it to the DB, checks if it matches any "watched tags", and fires a Telegram alert if it does. It also periodically checks DB snapshots for "trending" deals and alerts when a deal gets popular.
* **`fetch_user_activity.py`**: A CLI tool that scrapes a particular user's activity profile on OzBargain. It uses a Playwright generator to handle infinite scrolling, while a ThreadPool of concurrent workers quickly fetches the context of each deal they interacted with using requests.
* **`scraper.py`**: The core scraping logic. It contains standard Playwright abstractions for logging into/navigating OzBargain, a humanized infinite-scroll mechanism, and a fast `requests`-based scraper to extract deal metadata (Title, Price, Tags, Votes, Description, etc.).
* **`db_manager.py`**: SQLite database manager that tracks `live_deals`, historical `deal_snapshots` (for trending velocity), `user_activity`, and user `watched_tags`. Contains logic to compute "Heat Scores" for trending deals.
* **`notifier.py`**: A simple Telegram messaging module payload dispatcher.


## 🚀 Getting Started

### Prerequisites
* Python 3.10+
* [Telegram Bot Token and Chat ID](https://core.telegram.org/bots/tutorial) (Optional, for alerts)

### Environment Setup

Create a `.env` file in the root directory (or use environment variables) to configure Telegram:
```ini
TELEGRAM_BOT_TOKEN="your_bot_token"
TELEGRAM_CHAT_ID="your_chat_id"
OZBARGAIN_DB_PATH="ozbargain.db" # Optional override
MIN_HEAT_SCORE=60                # Score threshold for trending alerts
TRENDING_CHECK_INTERVAL=30       # Minutes between trending checks
POLL_INTERVAL=5                  # Seconds between live feed polls
```

### Self-Healing Feature
The Live Monitor now includes a self-healing mechanism. If the Playwright browser session crashes or encounters a fatal error (e.g., target closed), the service will automatically log the error and re-initialize a fresh browser session after a short delay (15 seconds), ensuring continuous monitoring.

### Local Installation

1. Create a virtual environment and install dependencies:
   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
2. Install Playwright browser binaries:
   ```bash
   playwright install chromium
   ```

### Running the Live Monitor

To start the real-time deal monitor and alert system:
```bash
python live_monitor.py
```
*Note: Make sure to populate the `watched_tags` table in `ozbargain.db` if you want targeted keyword alerts!*

### Fetching User Activity

To archive a specific user's posts and comments:
```bash
python fetch_user_activity.py <username> --limit 100 --workers 10
```
Use `--headful` if you want to watch the browser automate the infinite scrolling.

## 🐳 Docker Deployment

A `Dockerfile` is provided based on the official Microsoft Playwright Python image.

Build the image:
```bash
docker build -t ozbargain-tools .
```

### Running the Scraper via Docker

When running the container, you can pass environment variables and mount a volume so your database persists:

**Run user activity fetcher (default command):**
```bash
docker run --rm \
    -v $(pwd)/data:/app/data \
    ozbargain-tools \
    python fetch_user_activity.py some_username --limit 50
```

**Run the live monitor:**
```bash
docker run -d \
    --name ozb-monitor \
    --env-file .env \
    -v $(pwd)/data:/app/data \
    -e OZBARGAIN_DB_PATH=/app/data/ozbargain.db \
    ozbargain-tools \
    python live_monitor.py
```

*Note: Ensure you map a persistent directory (e.g. `./data`) to avoid losing the SQLite database and alert history.*
