"""
Gunga Job Radar
Phase 3 — upgraded job collection, matching, storage and notifications.

Modes:
    python job_radar.py --mode scan
    python job_radar.py --mode digest
    python job_radar.py --mode both

Required environment variables:
    DATABASE_URL

For Telegram alerts:
    TELEGRAM_BOT_TOKEN
    TELEGRAM_CHAT_ID

For Gmail digest:
    GMAIL_ADDRESS
    GMAIL_APP_PASSWORD
"""

from __future__ import annotations

import argparse
import html
import logging
import os
import re
import smtplib
import sys
import time
import xml.etree.ElementTree as ET

from dataclasses import dataclass
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Iterable

import psycopg2
import requests
from dotenv import load_dotenv


# ============================================================
# CONFIGURATION
# ============================================================

load_dotenv()

APP_NAME = "Gunga Job Radar"
APP_VERSION = "3.0"

MYJOBMAG_FEED_URL = "https://www.myjobmag.co.ke/feeds/jobsxml.xml"

REQUEST_TIMEOUT = 25
MAX_JOBS_PER_SOURCE = 100

MIN_SAVE_SCORE = 20
TELEGRAM_SCORE = 75

MAX_DESCRIPTION_LENGTH = 5000

TELEGRAM_RETRIES = 3
EMAIL_RETRIES = 3


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger(APP_NAME)


# ============================================================
# CANDIDATE PROFILE
# ============================================================

PROFILE = {
    "preferred_locations": [
        "malindi",
        "kilifi",
        "mombasa",
        "nairobi",
        "remote",
        "kenya",
    ],

    "target_titles": [
        "ict intern",
        "ict assistant",
        "ict officer",
        "ict technician",
        "ict support",
        "it intern",
        "it support",
        "it technician",
        "it assistant",
        "it officer",
        "help desk",
        "helpdesk",
        "technical support",
        "support technician",
        "computer technician",
        "junior developer",
        "junior software developer",
        "junior web developer",
        "web developer",
        "software developer intern",
        "software development intern",
        "frontend developer",
        "front end developer",
        "backend developer",
        "networking intern",
        "network technician",
        "network support",
        "system administrator",
        "systems administrator",
        "data entry",
        "records assistant",
        "it attache",
        "ict attache",
    ],

    "skills": [
        "it support",
        "technical support",
        "help desk",
        "helpdesk",
        "hardware",
        "computer hardware",
        "troubleshooting",
        "networking",
        "network support",
        "tcp/ip",
        "html",
        "css",
        "javascript",
        "web development",
        "react",
        "typescript",
        "node.js",
        "nodejs",
        "postgresql",
        "sql",
        "kotlin",
        "android",
        "git",
        "github",
        "database",
        "data entry",
        "records management",
        "computer literacy",
    ],

    "education_signals": [
        "diploma",
        "certificate",
        "kcse",
        "entry level",
        "entry-level",
        "intern",
        "internship",
        "trainee",
        "graduate trainee",
        "fresh graduate",
        "no experience",
        "without experience",
    ],

    "experience_penalties": [
        "5+ years",
        "6+ years",
        "7+ years",
        "8+ years",
        "10+ years",
        "five years",
        "six years",
        "seven years",
        "eight years",
        "ten years",
        "senior developer",
        "senior software engineer",
        "senior engineer",
        "senior manager",
        "head of",
        "director",
    ],

    "hard_requirement_penalties": [
        "bachelor's degree required",
        "bachelor’s degree required",
        "degree required",
        "master's degree required",
        "master’s degree required",
        "phd required",
        "ccna required",
        "hcia required",
    ],
}


# ============================================================
# DATA MODEL
# ============================================================

@dataclass
class Job:
    source: str
    source_url: str
    title: str
    company: str
    location: str
    description: str


@dataclass
class MatchResult:
    score: int
    tier: str
    reasons: list[str]
    blockers: list[str]
    matched_skills: list[str]
    matched_locations: list[str]


# ============================================================
# ENVIRONMENT
# ============================================================

def require_env(*names: str) -> None:
    missing = [name for name in names if not os.getenv(name)]

    if missing:
        raise RuntimeError(
            "Missing required environment variable(s): "
            + ", ".join(missing)
        )


# ============================================================
# TEXT HELPERS
# ============================================================

def clean_text(value: str | None) -> str:
    if not value:
        return ""

    value = html.unescape(value)

    # Remove HTML tags.
    value = re.sub(r"<[^>]+>", " ", value)

    # Normalize whitespace.
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def normalize_for_matching(value: str) -> str:
    value = clean_text(value).lower()

    # Normalize curly apostrophes.
    value = value.replace("’", "'")

    # Normalize common separators.
    value = value.replace("/", " ")
    value = value.replace("-", " ")

    return value


def contains_phrase(text: str, phrase: str) -> bool:
    """
    Safer phrase matching.

    Prevents things like:
        "react" matching "reaction"
    """
    text = normalize_for_matching(text)
    phrase = normalize_for_matching(phrase)

    pattern = r"(?<!\w)" + re.escape(phrase) + r"(?!\w)"

    return re.search(pattern, text) is not None


def truncate(text: str, length: int) -> str:
    text = text or ""

    if len(text) <= length:
        return text

    return text[:length].rstrip() + "..."


# ============================================================
# LOCATION EXTRACTION
# ============================================================

LOCATION_ALIASES = {
    "malindi": ["malindi"],
    "kilifi": ["kilifi"],
    "mombasa": ["mombasa"],
    "nairobi": ["nairobi"],
    "remote": [
        "remote",
        "work from home",
        "work-from-home",
        "fully remote",
        "remote work",
    ],
    "kenya": ["kenya", "nationwide", "all counties"],
}


def extract_locations(title: str, description: str) -> list[str]:
    text = f"{title} {description}"

    found = []

    for canonical, aliases in LOCATION_ALIASES.items():
        for alias in aliases:
            if contains_phrase(text, alias):
                found.append(canonical)
                break

    return list(dict.fromkeys(found))


def extract_location(title: str, description: str) -> str:
    locations = extract_locations(title, description)

    if not locations:
        return "Kenya"

    # Prefer specific locations over generic Kenya.
    priority = [
        "malindi",
        "kilifi",
        "mombasa",
        "nairobi",
        "remote",
        "kenya",
    ]

    for location in priority:
        if location in locations:
            return location.title()

    return locations[0].title()


# ============================================================
# COMPANY EXTRACTION
# ============================================================

def extract_company(title: str, description: str = "") -> str:
    """
    MyJobMag commonly uses:
        "Job Title at Company"

    We also handle:
        "Job Title - Company"
        "Job Title | Company"
    """

    patterns = [
        r"\bat\s+(.+)$",
        r"\s[-|]\s(.+)$",
    ]

    for pattern in patterns:
        match = re.search(pattern, title, re.IGNORECASE)

        if match:
            company = clean_text(match.group(1))

            if company:
                return company

    # Try simple company labels in descriptions.
    match = re.search(
        r"(?:company|employer|organization)\s*:\s*([^.;]+)",
        description,
        re.IGNORECASE,
    )

    if match:
        return clean_text(match.group(1))

    return "Unknown"


# ============================================================
# MYJOBMAG COLLECTOR
# ============================================================

def fetch_myjobmag_jobs(
    limit: int = MAX_JOBS_PER_SOURCE,
) -> list[Job]:

    logger.info("Fetching MyJobMag jobs...")

    headers = {
        "User-Agent": (
            "GungaJobRadar/3.0 "
            "(personal job alert tool
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
# 2. Collector — MyJobMag Kenya RSS feed (public, no key required)
# ---------------------------------------------------------------------------

MYJOBMAG_FEED_URL = "https://www.myjobmag.co.ke/feeds/jobsxml.xml"

def fetch_myjobmag_jobs(limit=100):
    """Fetch and parse MyJobMag Kenya's public RSS feed. Returns ALL jobs in the
    feed (limited to `limit`) — filtering to ICT-relevant ones happens in run_scan,
    since the scorer already does that work and we don't want to filter twice."""
    resp = requests.get(MYJOBMAG_FEED_URL, timeout=20, headers={
        "User-Agent": "GungaJobRadar/1.0 (personal job alert tool; contact: snavevanso@gmail.com)"
    })
    resp.raise_for_status()

    root = ET.fromstring(resp.content)
    jobs = []
    for item in root.findall(".//item")[:limit]:
        title = (item.findtext("title") or "Untitled").strip()
        link = (item.findtext("link") or "").strip()
        industry = (item.findtext("industry") or "").strip()
        description = (item.findtext("description") or "").strip()

        # Titles are usually "Role at Company" — split that out for a cleaner company field
        company = "Unknown"
        match = re.search(r"\bat\s+(.+)$", title, re.IGNORECASE)
        if match:
            company = match.group(1).strip()

        jobs.append({
            "source": "MyJobMag",
            "source_url": link,
            "title": title,
            "company": company,
            "location": "Kenya",
            "description": f"[{industry}] {description}" if industry else description,
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
    raw_jobs = fetch_myjobmag_jobs()
    print(f"Fetched {len(raw_jobs)} jobs from MyJobMag")

    new_count = 0
    for job in raw_jobs:
        if not job["source_url"]:
            continue
        if not job_is_new(conn, job["source_url"]):
            continue  # already seen, skip

        score, tier, reasons, blockers = score_job(job)

        # MyJobMag is a general Kenyan job board, not ICT-specific, so most postings
        # will score very low. Skip saving/noise for anything clearly irrelevant —
        # keep the DB and digest focused on jobs actually worth Evans's attention.
        if score < 20:
            continue

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
