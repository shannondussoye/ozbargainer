# OzBargain Monitor & Scraper

A robust Python-based toolkit for monitoring live deals on [OzBargain](https://www.ozbargain.com.au), tracking trend velocity, and automating user activity archiving.

---

## ✨ Features

- **Real-Time Monitoring**: Automatically scans the `/live` feed to ingest new events, votes, and comments.
- **Bot-Wall Resilience**: Specialized Hybrid Resolution bypasses Cloudflare challenges using metadata fallbacks and native CDP connections.
- **Smart Cooldown & Deduplication**: Throttles crawls by Node ID and Deal Title to prevent redundant requests and avoid detection.
- **Interactive Telegram Bot**: Supports real-time deal alerts and inbound tag management (view, add, remove watched tags).
- **Data Integrity Guard**: Prevents zeroing out popularity scores if a Cloudflare challenge block is encountered.
- **Observability Integration**: Out-of-the-box support for Healthchecks.io (heartbeats), Logtail (remote logging), and ntfy alerts.

---

## 🏗 System Architecture

The system is organized into a modular Python package (`ozbargain`) designed for scalability and containerization.

```mermaid
graph TD
    subgraph "Scraper Package (ozbargain)"
        M["core/monitor.py (Live Feed)"] --> S["core/scraper.py (Data Extraction)"]
        M --> DB["db/manager.py (Storage)"]
        M --> T["notifier/telegram.py (Alerts & Listener)"]
    end

    subgraph "Infrastructure"
        DB --> SL[(SQLite - ozbargain.db)]
        M -.-> Docker[Docker Container]
    end

    subgraph "External Integration"
        S --> OZ["OzBargain.com.au"]
        T --> TG["Telegram Bot API"]
    end

    subgraph "Observability"
        M --> HC["Healthchecks.io (Pulse)"]
        M --> LT["Logtail (Audit Trail)"]
        HC --> NT["ntfy (Alerts)"]
    end

    subgraph "Utilities (scripts/)"
        CU["cleanup_db.py"] --> DB
        FU["fetch_user_activity.py"] --> S
    end
```

### Key Components

- **`ozbargain.core.monitor`**: The heartbeat of the system.
  - Watches `/live` for deal, vote, and comment events.
  - Enforces a 15-second timeout for scrapers to prevent hanging.
  - Detects stale web sessions and triggers a refresh every 4 hours.
- **`ozbargain.core.scraper`**: Handles HTML parsing and Cloudflare Turnstile detection.
- **`ozbargain.db.manager`**: Manages SQLite transactions, records trend velocity snapshots, and cleans up historical snapshots.
- **`ozbargain.notifier.telegram`**: Sends outgoing alerts and manages incoming tags command listener.
- **`ozbargain.utils.logger`**: Structured JSON logging outputting to stdout, local log files, and Logtail.

---

## 🚀 Getting Started

### Prerequisites

- Python 3.12+
- Docker & Docker Compose (Recommended)

### Environment Configuration

Create a `.env` file in the root directory:

```ini
TELEGRAM_BOT_TOKEN="your_bot_token"
TELEGRAM_CHAT_ID="your_chat_id"
MIN_HEAT_SCORE=60                # Threshold for trending alerts
TRENDING_CHECK_INTERVAL=30       # Minutes between velocity scans
POLL_INTERVAL=5                  # Seconds between feed polls

# Observability (Optional)
LOGTAIL_SOURCE_TOKEN="your_token"       # Stream logs to Logtail
HEALTHCHECK_PING_URL="https://hc-ping.com/uuid" # Heartbeat URL
```

---

## 🐳 Deployment & Running

### Docker Deployment (Recommended)

#### 1. Hybrid Bridge (Stealth Mode)
Runs Google Chrome on the host machine to easily complete Cloudflare Turnstile challenges while containerizing the monitor.
```bash
# Starts the host browser and monitor container
make start
```

#### 2. Standard Deployment
Runs the monitor inside Docker standalone.
```bash
# Build and run container manually
docker compose up -d --build
```

#### 3. View Logs
```bash
make logs
```

### Local Development

#### 1. Installation
Install dependencies using `uv` (deterministic package management):
```bash
uv pip sync requirements.lock
uv run playwright install chromium
```

#### 2. Run Monitor Locally
```bash
export PYTHONPATH=$PYTHONPATH:.
python3 -m ozbargain.core.monitor
```

#### 3. Run Test Suite
Verify parser logic and database integrity rules:
```bash
make test
```

---

## 💬 Telegram Command Interface

The bot includes an inbound listener enabling tag configuration directly from Telegram.

| Command | Description | Example |
| :--- | :--- | :--- |
| `/tags` | List all active watched tags | `/tags` |
| `/watch <tag>` | Add a tag to the watch list | `/watch laptop` |
| `/unwatch <tag>` | Remove a tag from the watch list | `/unwatch laptop` |
| `/help` | Display list of commands | `/help` |

> [!IMPORTANT]
> **Access Security**: The listener filters all updates strictly against the configured `TELEGRAM_CHAT_ID`. Messages from unauthorized users will be ignored and logged.

---

## 🧹 Maintenance Utilities

Helper scripts are available in the `scripts/` directory:

- **Fetch User Activity**: Scrape user archives.
  ```bash
  python3 -m scripts.fetch_user_activity --username <name>
  ```
- **Cleanup Database**: Delete or repair inconsistent records.
  ```bash
  python3 -m scripts.cleanup_db
  ```

---

## 🛡 Security & Anti-Bot Strategy

1. **Hybrid Resolution**: If direct page scraping fails, it falls back to the metadata parsed directly from the live feed rows. Comments automatically resolve back to their parent deal node IDs to maintain database integrity.
2. **CDP Port Isolation**: When running the Hybrid Bridge (`manage.sh`), the host's Chrome instance binds its remote debugging port strictly to the loopback interface (`127.0.0.1`), allowing only the local container to connect.

---

## 🤖 OzBargain Data Agent

The repository contains a custom AI "Data Agent" skill located in `.agents/skills/ozbargain_data_agent.md`. You can ask the AI agent to:
- **"Give me a health check"** — Reports active/expired ratios, database sizing, and metrics.
- **"Why didn't node/12345 alert?"** — Audits why a specific deal did or didn't alert based on popularity history.
- **"What are the top trending deals?"** — Lists current trending deals ordered by heat score.
