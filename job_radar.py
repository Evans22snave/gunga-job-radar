"""
Gunga Job Radar — Phase 1 starter script

What this does, end to end:
1. Fetches recent ICT-relevant job postings from the ReliefWeb API (no key needed).
2. Scores each job against Evans's candidate profile (rule-based, Section 7 of the spec).
3. Stores jobs + scores in Supabase Postgres, skipping ones already seen (dedupe).
4. Sends an instant Telegram alert for any NEW strong match (score >= 75).
5. Sends a Gmail digest covering everything scored since the last digest.

Two modes, meant to run on different schedules (see the GitHub Actions workflow):
    python job_radar.py --mode scan    # fetch + score + save + Telegram alerts (run often)
    python job_radar.py --mode digest  # email everything not yet digested (run once/day)
    python job_radar.py --mode both    # do both in one go (useful for local testing)

Environment variables required (put these in a .env file next to this script,
or set them as GitHub Actions secrets later):
    TELEGRAM_BOT_TOKEN
    TELEGRAM_CHAT_ID
    GMAIL_ADDRESS
    GMAIL_APP_PASSWORD
    DATABASE_URL
"""

import os
import argparse
import smtplib
import requests
import psycopg2
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")
DATABASE_URL = os.environ.get("DATABASE_URL")

def require(*names):
    """Fail loudly and clearly if a required env var is missing, instead of a raw KeyError."""
    missing = [n for n in names if not globals().get(n)]
    if missing:
        raise SystemExit(f"Missing required environment variable(s): {', '.join(missing)}")

# ---------------------------------------------------------------------------
# 1. Candidate profile (Section 2 of the project spec)
# ---------------------------------------------------------------------------

PROFILE = {
    "locations_preferred": ["malindi", "kilifi", "mombasa", "nairobi", "remote", "kenya"],
    "target_titles": [
        "ict intern", "it support", "it technician", "ict assistant", "help desk",
        "junior developer", "computer technician", "networking intern",
        "web developer", "software developer intern", "it attache", "ict officer",
    ],
    "skills": [
        "it support", "help desk", "hardware", "troubleshooting", "networking",
        "html", "css", "javascript", "web development", "react", "typescript",
        "node.js", "postgresql", "kotlin", "android", "data entry", "records management",
    ],
    "soft_negatives": [
        "bachelor's degree required", "5+ years", "senior", "ccna required",
        "huawei hcia required",
    ],
}

# ---------------------------------------------------------------------------
# 2. Collector — ReliefWeb API (public, no key required)
# ---------------------------------------------------------------------------

def fetch_reliefweb_jobs(query="ICT OR IT OR Information Technology", country="Kenya", limit=20):
    """Fetch recent job postings from ReliefWeb's public API."""
    url = "https://api.reliefweb.int/v1/jobs"
    params = {
        "appname": "gunga-job-radar",
        "query[value]": query,
        "filter[field]": "country",
        "filter[value]": country,
        "limit": limit,
        "sort[]": "date.created:desc",
        "fields[include][]": ["title", "body", "url", "date", "source", "country"],
    }
    resp = requests.get(url, params=params, timeout=20)
    resp.raise_for_status()
    data = resp.json()

    jobs = []
    for item in data.get("data", []):
        fields = item.get("fields", {})
        jobs.append({
            "source": "ReliefWeb",
            "source_url": fields.get("url", ""),
            "title": fields.get("title", "Untitled"),
            "company": (fields.get("source") or [{}])[0].get("name", "Unknown"),
            "location": country,
            "description": fields.get("body", "") or "",
        })
    return jobs

# ---------------------------------------------------------------------------
# 3. Matching engine — Stage 1 rule-based scoring (Section 7 of the spec)
# ---------------------------------------------------------------------------

def score_job(job, profile=PROFILE):
    text = f"{job['title']} {job['description']}".lower()
    reasons = []
    score = 0

    # Title match (highest weight)
    if any(t in job["title"].lower() for t in profile["target_titles"]):
        score += 35
        reasons.append("Title matches a target role")

    # Location match
    if any(loc in text for loc in profile["locations_preferred"]):
        score += 20
        reasons.append("Preferred location mentioned")

    # Skills overlap
    matched_skills = [s for s in profile["skills"] if s in text]
    score += min(len(matched_skills) * 6, 30)
    if matched_skills:
        reasons.append(f"Skills matched: {', '.join(matched_skills[:4])}")

    # Education/experience friendliness
    if "diploma" in text or "entry level" in text or "entry-level" in text or "intern" in text:
        score += 15
        reasons.append("Diploma / entry-level friendly language")

    # Soft negatives lower the score but never hard-exclude
    blockers = [b for b in profile["soft_negatives"] if b in text]
    score -= len(blockers) * 15

    score = max(0, min(100, score))

    if score >= 75:
        tier = "strong"
    elif score >= 45:
        tier = "consider"
    else:
        tier = "poor"

    return score, tier, reasons, blockers

# ---------------------------------------------------------------------------
# 4. Database — Supabase Postgres (dedupe on source_url)
# ---------------------------------------------------------------------------

def get_db_connection():
    require("DATABASE_URL")
    return psycopg2.connect(DATABASE_URL)

def ensure_schema(conn):
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id SERIAL PRIMARY KEY,
                source TEXT,
                source_url TEXT UNIQUE,
                title TEXT,
                company TEXT,
                location TEXT,
                description TEXT,
                score INTEGER,
                tier TEXT,
                reasons TEXT,
                blockers TEXT,
                telegram_sent BOOLEAN DEFAULT FALSE,
                digested BOOLEAN DEFAULT FALSE,
                fetched_at TIMESTAMP DEFAULT NOW()
            );
        """)
    conn.commit()

def job_is_new(conn, source_url):
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM jobs WHERE source_url = %s", (source_url,))
        return cur.fetchone() is None

def save_job(conn, job, score, tier, reasons, blockers):
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO jobs (source, source_url, title, company, location, description, score, tier, reasons, blockers)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (source_url) DO NOTHING;
        """, (
            job["source"], job["source_url"], job["title"], job["company"],
            job["location"], job["description"][:2000], score, tier,
            "; ".join(reasons), "; ".join(blockers),
        ))
    conn.commit()

def mark_telegram_sent(conn, source_url):
    with conn.cursor() as cur:
        cur.execute("UPDATE jobs SET telegram_sent = TRUE WHERE source_url = %s", (source_url,))
    conn.commit()

def fetch_undigested_jobs(conn):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT title, company, location, source_url, score, tier
            FROM jobs
            WHERE digested = FALSE
            ORDER BY score DESC;
        """)
        rows = cur.fetchall()
    return [
        {"title": r[0], "company": r[1], "location": r[2], "source_url": r[3], "score": r[4], "tier": r[5]}
        for r in rows
    ]

def mark_all_digested(conn):
    with conn.cursor() as cur:
        cur.execute("UPDATE jobs SET digested = TRUE WHERE digested = FALSE")
    conn.commit()

# ---------------------------------------------------------------------------
# 5. Notifications
# ---------------------------------------------------------------------------

def send_telegram_alert(job, score, reasons):
    require("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
    text = (
        f"🔔 NEW STRONG MATCH ({score}%)\n"
        f"{job['title']} — {job['company']}\n"
        f"📍 {job['location']}\n"
        f"✅ {' | '.join(reasons) if reasons else 'Good overall fit'}\n"
        f"🔗 {job['source_url']}"
    )
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    resp = requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": text})
    resp.raise_for_status()

def send_gmail_digest(scored_jobs):
    """scored_jobs: list of dicts with title, company, location, source_url, score, tier.
    Called with everything accumulated since the last digest was sent."""
    if not scored_jobs:
        print("No undigested jobs — skipping email.")
        return

    require("GMAIL_ADDRESS", "GMAIL_APP_PASSWORD")

    strong = [j for j in scored_jobs if j["tier"] == "strong"]
    consider = [j for j in scored_jobs if j["tier"] == "consider"]
    poor = [j for j in scored_jobs if j["tier"] == "poor"]

    lines = [
        f"🔥 {len(scored_jobs)} new jobs found since the last digest\n",
        f"🟢 {len(strong)} strong match{'es' if len(strong) != 1 else ''}",
        f"🟡 {len(consider)} worth considering",
        f"🔴 {len(poor)} poor match\n",
    ]

    for group_label, group in [("STRONG MATCHES", strong), ("WORTH CONSIDERING", consider)]:
        if not group:
            continue
        lines.append(f"\n--- {group_label} ---")
        for j in sorted(group, key=lambda x: -x["score"]):
            lines.append(
                f"\n{j['score']}% — {j['title']} @ {j['company']} ({j['location']})\n"
                f"{j['source_url']}"
            )

    body = "\n".join(lines)

    msg = MIMEMultipart()
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = GMAIL_ADDRESS
    msg["Subject"] = f"Gunga Job Radar — {len(scored_jobs)} new jobs found"
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.send_message(msg)

# ---------------------------------------------------------------------------
# 6. Main pipeline
# ---------------------------------------------------------------------------

def run_scan(conn):
    """Fetch, score, save, and fire instant Telegram alerts for strong matches.
    Meant to run frequently (e.g. every 2-3 hours)."""
    raw_jobs = fetch_reliefweb_jobs()
    print(f"Fetched {len(raw_jobs)} jobs from ReliefWeb")

    new_count = 0
    for job in raw_jobs:
        if not job["source_url"]:
            continue
        if not job_is_new(conn, job["source_url"]):
            continue  # already seen, skip

        score, tier, reasons, blockers = score_job(job)
        save_job(conn, job, score, tier, reasons, blockers)
        new_count += 1

        if tier == "strong":
            send_telegram_alert(job, score, reasons)
            mark_telegram_sent(conn, job["source_url"])

    print(f"{new_count} new jobs scored this scan")

def run_digest(conn):
    """Email everything scored since the last digest, then mark it all as sent.
    Meant to run once a day."""
    undigested = fetch_undigested_jobs(conn)
    print(f"{len(undigested)} jobs pending digest")
    send_gmail_digest(undigested)
    if undigested:
        mark_all_digested(conn)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["scan", "digest", "both"], default="both")
    args = parser.parse_args()

    conn = get_db_connection()
    ensure_schema(conn)

    if args.mode in ("scan", "both"):
        run_scan(conn)
    if args.mode in ("digest", "both"):
        run_digest(conn)

    conn.close()

if __name__ == "__main__":
    main()
