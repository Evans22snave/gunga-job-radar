"""
Gunga Job Radar
Phase 3 — End-to-End Job Monitoring System

Pipeline:

    ReliefWeb API
          ↓
       Collector
          ↓
    Matching Engine
          ↓
       Database
          ↓
    ┌─────┴─────┐
    ↓           ↓
 Telegram     Gmail
 Alerts       Digest

Modes:

    python job_radar.py --mode scan
    python job_radar.py --mode digest
    python job_radar.py --mode both
"""

from __future__ import annotations

import argparse
import logging
import os
import smtplib
import time

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
from dotenv import load_dotenv

from database.db import Database


# ============================================================
# CONFIGURATION
# ============================================================

load_dotenv()

APP_NAME = "Gunga Job Radar"
APP_VERSION = "3.0"

RELIEFWEB_URL = "https://api.reliefweb.int/v1/jobs"

RELIEFWEB_QUERY = (
    "ICT OR IT OR "
    "\"Information Technology\" OR "
    "\"Computer\" OR "
    "\"Software\""
)

RELIEFWEB_COUNTRY = "Kenya"

REQUEST_TIMEOUT = 30

TELEGRAM_SCORE = 75

MIN_SAVE_SCORE = 0

MAX_DESCRIPTION_LENGTH = 5000

MAX_JOBS_PER_SCAN = 50

RETRY_COUNT = 3


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s | "
        "%(levelname)s | "
        "%(message)s"
    ),
)

logger = logging.getLogger(APP_NAME)


# ============================================================
# CANDIDATE PROFILE
# ============================================================

PROFILE = {
    "locations_preferred": [
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

        "junior developer",
        "junior software developer",
        "junior web developer",

        "computer technician",

        "networking intern",
        "network technician",
        "network support",

        "web developer",
        "software developer intern",
        "software development intern",

        "frontend developer",
        "front end developer",

        "backend developer",

        "system administrator",
        "systems administrator",

        "technical support",

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

    "soft_negatives": [
        "bachelor's degree required",
        "bachelor’s degree required",
        "degree required",

        "master's degree required",
        "master’s degree required",

        "phd required",

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

        "senior",

        "ccna required",
        "huawei hcia required",
        "hcia required",
    ],
}


# ============================================================
# TEXT HELPERS
# ============================================================

def clean_text(value: str | None) -> str:

    if not value:
        return ""

    return " ".join(
        str(value).split()
    ).strip()


def normalize_text(value: str) -> str:

    value = clean_text(value)

    return (
        value
        .lower()
        .replace("’", "'")
    )


def contains_phrase(
    text: str,
    phrase: str,
) -> bool:

    return normalize_text(
        phrase
    ) in normalize_text(
        text
    )


# ============================================================
# RELIEFWEB COLLECTOR
# ============================================================

def fetch_reliefweb_jobs(
    query: str = RELIEFWEB_QUERY,
    country: str = RELIEFWEB_COUNTRY,
    limit: int = MAX_JOBS_PER_SCAN,
) -> list[dict]:

    logger.info(
        "Fetching jobs from ReliefWeb..."
    )

    params = {
        "appname": "gunga-job-radar",

        "query[value]": query,

        "filter[field]": "country",

        "filter[value]": country,

        "limit": limit,

        "sort[]": "date.created:desc",

        "fields[include][]": [
            "title",
            "body",
            "url",
            "date",
            "source",
            "country",
        ],
    }

    headers = {
        "User-Agent": (
            "GungaJobRadar/3.0 "
            "(job monitoring application)"
        )
    }

    last_error = None

    for attempt in range(
        1,
        RETRY_COUNT + 1,
    ):

        try:

            response = requests.get(
                RELIEFWEB_URL,
                params=params,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            )

            response.raise_for_status()

            data = response.json()

            jobs = []

            for item in data.get(
                "data",
                [],
            ):

                fields = item.get(
                    "fields",
                    {},
                )

                title = clean_text(
                    fields.get(
                        "title"
                    )
                )

                source_url = clean_text(
                    fields.get(
                        "url"
                    )
                )

                description = clean_text(
                    fields.get(
                        "body"
                    )
                )

                source_data = (
                    fields.get(
                        "source"
                    )
                    or []
                )

                company = "Unknown"

                if (
                    isinstance(
                        source_data,
                        list,
                    )
                    and source_data
                ):

                    company = clean_text(
                        source_data[0].get(
                            "name",
                            "Unknown",
                        )
                    )

                if not title or not source_url:
                    continue

                jobs.append(
                    {
                        "source": "ReliefWeb",

                        "source_url": source_url,

                        "title": title,

                        "company": company,

                        "location": country,

                        "description": (
                            description[
                                :MAX_DESCRIPTION_LENGTH
                            ]
                        ),
                    }
                )

            logger.info(
                "ReliefWeb returned %d jobs.",
                len(jobs),
            )

            return jobs

        except Exception as exc:

            last_error = exc

            logger.warning(
                "ReliefWeb attempt %d/%d failed: %s",
                attempt,
                RETRY_COUNT,
                exc,
            )

            if attempt < RETRY_COUNT:

                time.sleep(
                    2 ** attempt
                )

    raise RuntimeError(
        f"Could not fetch ReliefWeb jobs: "
        f"{last_error}"
    )


# ============================================================
# MATCHING ENGINE
# ============================================================

def score_job(
    job: dict,
    profile: dict = PROFILE,
) -> tuple[
    int,
    str,
    list[str],
    list[str],
    list[str],
]:

    title = normalize_text(
        job["title"]
    )

    full_text = normalize_text(
        " ".join(
            [
                job["title"],
                job["description"],
                job["location"],
            ]
        )
    )

    score = 0

    reasons = []

    blockers = []

    matched_skills = []

    # --------------------------------------------------------
    # TITLE
    # --------------------------------------------------------

    title_matches = [
        target
        for target in profile[
            "target_titles"
        ]
        if contains_phrase(
            title,
            target,
        )
    ]

    if title_matches:

        score += 35

        reasons.append(
            "Title matches target role"
        )

    # --------------------------------------------------------
    # LOCATION
    # --------------------------------------------------------

    location_matches = [
        location
        for location in profile[
            "locations_preferred"
        ]
        if contains_phrase(
            full_text,
            location,
        )
    ]

    if location_matches:

        if any(
            location in {
                "malindi",
                "kilifi",
                "mombasa",
            }
            for location
            in location_matches
        ):

            score += 20

            reasons.append(
                "Preferred Coast location"
            )

        elif "remote" in location_matches:

            score += 20

            reasons.append(
                "Remote opportunity"
            )

        else:

            score += 10

            reasons.append(
                "Preferred location mentioned"
            )

    # --------------------------------------------------------
    # SKILLS
    # --------------------------------------------------------

    matched_skills = [
        skill
        for skill in profile[
            "skills"
        ]
        if contains_phrase(
            full_text,
            skill,
        )
    ]

    skill_points = min(
        len(matched_skills) * 6,
        30,
    )

    score += skill_points

    if matched_skills:

        reasons.append(
            "Skills matched: "
            + ", ".join(
                matched_skills[:5]
            )
        )

    # --------------------------------------------------------
    # ENTRY LEVEL / EDUCATION
    # --------------------------------------------------------

    friendly_terms = [
        "diploma",
        "entry level",
        "entry-level",
        "intern",
        "internship",
        "trainee",
        "attachment",
        "fresh graduate",
    ]

    if any(
        contains_phrase(
            full_text,
            term,
        )
        for term in friendly_terms
    ):

        score += 15

        reasons.append(
            "Entry-level/diploma friendly"
        )

    # --------------------------------------------------------
    # NEGATIVES
    # --------------------------------------------------------

    for negative in profile[
        "soft_negatives"
    ]:

        if contains_phrase(
            full_text,
            negative,
        ):

            blockers.append(
                negative
            )

            score -= 15

    # --------------------------------------------------------
    # SCORE LIMIT
    # --------------------------------------------------------

    score = max(
        0,
        min(
            100,
            score,
        ),
    )

    # --------------------------------------------------------
    # TIER
    # --------------------------------------------------------

    if score >= 75:

        tier = "strong"

    elif score >= 45:

        tier = "consider"

    else:

        tier = "poor"

    return (
        score,
        tier,
        reasons,
        blockers,
        matched_skills,
    )


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram_alert(
    job: dict,
    score: int,
    reasons: list[str],
) -> bool:

    token = os.getenv(
        "TELEGRAM_BOT_TOKEN"
    )

    chat_id = os.getenv(
        "TELEGRAM_CHAT_ID"
    )

    if not token or not chat_id:

        logger.warning(
            "Telegram credentials not configured."
        )

        return False

    message = (
        f"🔔 NEW STRONG MATCH\n\n"

        f"🔥 Match: {score}%\n"

        f"💼 {job['title']}\n"

        f"🏢 {job['company']}\n"

        f"📍 {job['location']}\n\n"

        f"✅ "
        f"{' | '.join(reasons[:4])}\n\n"

        f"🔗 {job['source_url']}"
    )

    url = (
        "https://api.telegram.org/"
        f"bot{token}/sendMessage"
    )

    for attempt in range(
        1,
        RETRY_COUNT + 1,
    ):

        try:

            response = requests.post(
                url,
                data={
                    "chat_id": chat_id,
                    "text": message,
                },
                timeout=REQUEST_TIMEOUT,
            )

            response.raise_for_status()

            logger.info(
                "Telegram alert sent."
            )

            return True

        except Exception as exc:

            logger.warning(
                "Telegram attempt %d/%d failed: %s",
                attempt,
                RETRY_COUNT,
                exc,
            )

            if attempt < RETRY_COUNT:

                time.sleep(
                    2 ** attempt
                )

    return False


# ============================================================
# GMAIL DIGEST
# ============================================================

def send_gmail_digest(
    jobs: list[dict],
) -> bool:

    if not jobs:

        logger.info(
            "No undigested jobs."
        )

        return True

    address = os.getenv(
        "GMAIL_ADDRESS"
    )

    password = os.getenv(
        "GMAIL_APP_PASSWORD"
    )

    if not address or not password:

        logger.error(
            "Gmail credentials are missing."
        )

        return False

    strong = [
        job
        for job in jobs
        if job["tier"] == "strong"
    ]

    consider = [
        job
        for job in jobs
        if job["tier"] == "consider"
    ]

    poor = [
        job
        for job in jobs
        if job["tier"] == "poor"
    ]

    lines = [
        "GUNGA JOB RADAR",
        "",
        (
            f"{len(jobs)} new jobs "
            "since the last digest."
        ),
        "",
        f"🔥 Strong: {len(strong)}",
        f"🟡 Consider: {len(consider)}",
        f"🔴 Poor: {len(poor)}",
    ]

    for heading, group in [
        (
            "🔥 STRONG MATCHES",
            strong,
        ),
        (
            "🟡 WORTH CONSIDERING",
            consider,
        ),
    ]:

        if not group:
            continue

        lines.extend(
            [
                "",
                "",
                heading,
                "-" * 45,
            ]
        )

        for job in sorted(
            group,
            key=lambda item: (
                -item["score"]
            ),
        ):

            lines.extend(
                [
                    "",
                    (
                        f"{job['score']}% — "
                        f"{job['title']}"
                    ),
                    (
                        f"Company: "
                        f"{job['company']}"
                    ),
                    (
                        f"Location: "
                        f"{job['location']}"
                    ),
                    (
                        f"Apply: "
                        f"{job['source_url']}"
                    ),
                ]
            )

    lines.extend(
        [
            "",
            "",
            "Generated by Gunga Job Radar.",
        ]
    )

    body = "\n".join(
        lines
    )

    message = MIMEMultipart()

    message["From"] = address

    message["To"] = address

    message["Subject"] = (
        "Gunga Job Radar — "
        f"{len(jobs)} new jobs"
    )

    message.attach(
        MIMEText(
            body,
            "plain",
            "utf-8",
        )
    )

    for attempt in range(
        1,
        RETRY_COUNT + 1,
    ):

        try:

            with smtplib.SMTP(
                "smtp.gmail.com",
                587,
                timeout=REQUEST_TIMEOUT,
            ) as server:

                server.starttls()

                server.login(
                    address,
                    password,
                )

                server.send_message(
                    message
                )

            logger.info(
                "Gmail digest sent."
            )

            return True

        except Exception as exc:

            logger.warning(
                "Gmail attempt %d/%d failed: %s",
                attempt,
                RETRY_COUNT,
                exc,
            )

            if attempt < RETRY_COUNT:

                time.sleep(
                    2 ** attempt
                )

    return False


# ============================================================
# SCAN
# ============================================================

def run_scan(
    database: Database,
):

    logger.info(
        "========== SCAN START =========="
    )

    jobs = fetch_reliefweb_jobs()

    fetched = len(jobs)

    new_jobs = 0

    saved_jobs = 0

    strong_jobs = 0

    telegram_sent = 0

    for job in jobs:

        source_url = job[
            "source_url"
        ]

        if not source_url:

            continue

        if database.job_exists(
            source_url
        ):

            continue

        (
            score,
            tier,
            reasons,
            blockers,
            matched_skills,
        ) = score_job(job)

        new_jobs += 1

        logger.info(
            "%3d%% | %-8s | %s",
            score,
            tier,
            job["title"],
        )

        payload = {
            "source": job["source"],

            "source_url": source_url,

            "title": job["title"],

            "company": job["company"],

            "location": job["location"],

            "description": job[
                "description"
            ],

            "score": score,

            "tier": tier,

            "reasons": "; ".join(
                reasons
            ),

            "blockers": "; ".join(
                blockers
            ),
        }

        job_id = database.insert_job(
            payload
        )

        if job_id is None:

            continue

        saved_jobs += 1

        if tier == "strong":

            strong_jobs += 1

            notification_id = (
                database.create_notification(
                    job_id,
                    "telegram",
                )
            )

            sent = send_telegram_alert(
                job,
                score,
                reasons,
            )

            if sent:

                database.mark_notification_sent(
                    notification_id
                )

                database.mark_telegram_sent(
                    job_id
                )

                telegram_sent += 1

            else:

                database.mark_notification_failed(
                    notification_id,
                    "Telegram delivery failed",
                )

    logger.info(
        "Fetched: %d",
        fetched,
    )

    logger.info(
        "New: %d",
        new_jobs,
    )

    logger.info(
        "Saved: %d",
        saved_jobs,
    )

    logger.info(
        "Strong: %d",
        strong_jobs,
    )

    logger.info(
        "Telegram sent: %d",
        telegram_sent,
    )

    logger.info(
        "=========== SCAN END ==========="
    )


# ============================================================
# DIGEST
# ============================================================

def run_digest(
    database: Database,
):

    logger.info(
        "========= DIGEST START ========="
    )

    jobs = database.get_undigested_jobs()

    logger.info(
        "%d jobs pending digest.",
        len(jobs),
    )

    if not jobs:

        return

    sent = send_gmail_digest(
        jobs
    )

    if not sent:

        logger.error(
            "Digest failed. "
            "Jobs will remain undigested."
        )

        return

    database.mark_jobs_digested(
        [
            job["id"]
            for job in jobs
        ]
    )

    logger.info(
        "Digest completed."
    )

    logger.info(
        "========== DIGEST END =========="
    )


# ============================================================
# MAIN
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description=APP_NAME
    )

    parser.add_argument(
        "--mode",
        choices=[
            "scan",
            "digest",
            "both",
        ],
        default="both",
    )

    args = parser.parse_args()

    database_url = os.getenv(
        "DATABASE_URL"
    )

    if not database_url:

        logger.error(
            "DATABASE_URL is missing."
        )

        return 1

    database = Database(
        database_url
    )

    try:

        if args.mode in (
            "scan",
            "both",
        ):

            run_scan(
                database
            )

        if args.mode in (
            "digest",
            "both",
        ):

            run_digest(
                database
            )

    except KeyboardInterrupt:

        logger.info(
            "Stopped by user."
        )

        return 130

    except Exception as exc:

        logger.exception(
            "Fatal error: %s",
            exc,
        )

        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
)
