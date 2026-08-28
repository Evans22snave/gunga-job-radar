# Gunga Job Radar

Automated job discovery, relevance matching, PostgreSQL storage, Telegram alerts, and Gmail digests for ICT opportunities in Kenya.

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Initialize database
python -m database.schema

# Run a scan
python job_radar.py --mode scan

# Send digest
python job_radar.py --mode digest

# Do both
python job_radar.py --mode both
```

## Modes

- **scan** — Fetch jobs, score them, send Telegram alerts for strong matches
- **digest** — Send Gmail summary of undigested jobs
- **both** — Run scan followed by digest

## Environment Setup

Required environment variables:

```
DATABASE_URL=postgresql://user:password@host/db
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
GMAIL_ADDRESS=your@gmail.com
GMAIL_APP_PASSWORD=your_app_password
```

Store in `.env` file (never commit).

## Testing & Diagnostics

```bash
# Run integration tests
python -m tests

# View database state
python -m diagnostics

# Initialize schema
python -m database.schema
```

## Architecture

```
Himalayas API (145+ jobs/scan)
         ↓
  Collector & Normalize
         ↓
  Location Classification
         ↓
  Scoring Engine (0-100%)
    ├─ Title matching
    ├─ Skill matching
    ├─ Location eligibility
    ├─ Education/experience level
    └─ Soft negatives
         ↓
  Database (PostgreSQL)
    ├─ Duplicate detection
    ├─ Telegram state tracking
    └─ Digest state tracking
         ↓
  ┌──────┴──────┐
  ↓             ↓
Telegram      Gmail
Alerts        Digest
```

## Profile

Matched against a Kenya-based ICT diploma graduate with:

- **Target titles:** Junior developer, IT support, help desk, networking, Android
- **Skills:** HTML, CSS, JavaScript, React, Node.js, Kotlin, networking, hardware
- **Locations:** Malindi, Kilifi, Mombasa, Nairobi, Kenya, Remote, Africa, Worldwide
- **Education:** Entry-level friendly (diploma, certificate, intern, junior, graduate)

## Key Files

- `job_radar.py` — Main application
- `database/db.py` — PostgreSQL layer
- `database/schema.py` — Schema definition
- `diagnostics.py` — Database inspection tools
- `tests.py` — Integration test suite
- `requirements.txt` — Python dependencies

## Bug Fixes (Latest)

**Critical fix in commit ce9a246:**
- Separated duplicate detection from job re-evaluation
- Existing jobs now re-scored on each scan
- Telegram retry logic for failed notifications
- Added comprehensive scan metrics

## Recent Scan Output

```
Jobs fetched: 145
Jobs processed: 145
New jobs saved: N
Strong matches: N (now correctly detected)
Telegram attempts: N
Telegram sent: N
Telegram failures: 0
```

## Next Steps

1. Run integration tests to verify scoring
2. Check database with diagnostics tool
3. Trigger manual scan via GitHub Actions
4. Verify Telegram notifications arrive
5. Check Gmail digest

## GitHub Actions

Manual workflow dispatch available with mode selector:
- Go to Actions → Gunga Job Radar
- Click "Run workflow"
- Select mode: scan, digest, or both
- Monitor logs for metrics

## License

Private project

## Author

Evans22snave
