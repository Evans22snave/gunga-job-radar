"""
Gunga Job Radar
Phase 4 — Kenya-aware job matching

Pipeline:

    Himalayas API
          ↓
       Collector
          ↓
    Location Classification
          ↓
      Match Scoring
          ↓
       PostgreSQL
          ↓
    ┌─────┴─────┐
    ↓           ↓
 Telegram     Gmail
 Alerts       Digest

Modes:

    python job_radar.py --mode scan
    python job_radar.py --mode digest
    python job_radar.py --mode both

Required environment variables:

    DATABASE_URL
    TELEGRAM_BOT_TOKEN
    TELEGRAM_CHAT_ID
    GMAIL_ADDRESS
    GMAIL_APP_PASSWORD
"""

from __future__ import annotations

import argparse
import logging
import os
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

import requests
from dotenv import load_dotenv

from database.db import Database, DatabaseError


# ============================================================
# ENVIRONMENT
# ============================================================

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN"
)

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID"
)

GMAIL_ADDRESS = os.getenv(
    "GMAIL_ADDRESS"
)

GMAIL_APP_PASSWORD = os.getenv(
    "GMAIL_APP_PASSWORD"
)


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

logger = logging.getLogger(
    "Gunga Job Radar"
)


# ============================================================
# CONFIGURATION
# ============================================================

HIMALAYAS_API = (
    "https://himalayas.app/jobs/api/search"
)

REQUEST_TIMEOUT = 30

HIMALAYAS_REQUEST_DELAY = 0.75

STRONG_MATCH_THRESHOLD = 75

CONSIDER_THRESHOLD = 45


# ============================================================
# CANDIDATE PROFILE
# ============================================================

PROFILE = {

    "locations_preferred": [
        "malindi",
        "kilifi",
        "mombasa",
        "nairobi",
        "kenya",
        "remote",
        "worldwide",
        "africa",
    ],

    "target_titles": [

        "ict intern",
        "ict assistant",
        "ict officer",

        "it intern",
        "it support",
        "it technician",
        "it assistant",

        "help desk",
        "helpdesk",

        "technical support",
        "support technician",

        "computer technician",

        "network technician",
        "networking intern",

        "junior developer",
        "junior software developer",
        "junior web developer",

        "web developer",

        "frontend developer",
        "front-end developer",

        "software developer",
        "software developer intern",

        "application developer",

        "android developer",

        "it attache",
        "ict attache",
        "ict attachment",

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
        "network",

        "html",
        "css",
        "javascript",

        "web development",

        "react",
        "react.js",

        "typescript",

        "node.js",
        "nodejs",

        "postgresql",
        "postgres",

        "kotlin",
        "android",

        "data entry",
        "records management",

        "git",
        "github",

    ],

    "soft_negatives": [

        "bachelor's degree required",
        "bachelor degree required",

        "master's degree required",
        "master degree required",

        "5+ years",
        "5 years experience",
        "6+ years",
        "7+ years",
        "8+ years",
        "10+ years",

        "senior developer",
        "senior software developer",
        "senior engineer",

        "lead developer",
        "principal engineer",

        "manager",
        "director",

        "ccna required",
        "huawei hcia required",

    ],
}


# ============================================================
# ENVIRONMENT VALIDATION
# ============================================================

def require_environment(
    *names: str,
) -> None:

    missing = [
        name
        for name in names
        if not os.getenv(name)
    ]

    if missing:

        raise RuntimeError(
            "Missing required environment "
            "variable(s): "
            + ", ".join(missing)
        )


# ============================================================
# TEXT HELPERS
# ============================================================

def clean_text(
    value: Any,
) -> str:

    if value is None:
        return ""

    if isinstance(value, list):

        return ", ".join(
            clean_text(item)
            for item in value
        )

    if isinstance(value, dict):

        return " ".join(
            clean_text(item)
            for item in value.values()
        )

    return str(value)


def normalize_text(
    value: Any,
) -> str:

    return " ".join(
        clean_text(value)
        .lower()
        .split()
    )


# ============================================================
# LOCATION CLASSIFICATION
# ============================================================

def classify_location(
    job: dict[str, Any],
) -> tuple[str, list[str]]:

    location = normalize_text(
        job.get("location")
    )

    description = normalize_text(
        job.get("description")
    )

    title = normalize_text(
        job.get("title")
    )

    text = " ".join([
        location,
        description,
        title,
    ])

    # --------------------------------------------------------
    # Kenya
    # --------------------------------------------------------

    kenya_terms = [

        "kenya",
        "kenyan",

        "nairobi",
        "mombasa",
        "malindi",
        "kilifi",

        "nakuru",
        "kisumu",
        "eldoret",

    ]

    kenya_matches = [
        term
        for term in kenya_terms
        if term in text
    ]

    if kenya_matches:

        return (
            "KENYA",
            [
                "Kenya eligibility detected"
            ],
        )

    # --------------------------------------------------------
    # Africa
    # --------------------------------------------------------

    africa_terms = [

        "africa",
        "african",

        "sub-saharan africa",

        "east africa",
        "east african",

        "africa-wide",

    ]

    if any(
        term in text
        for term in africa_terms
    ):

        return (
            "REMOTE-AFRICA",
            [
                "Africa eligibility detected"
            ],
        )

    # --------------------------------------------------------
    # Worldwide
    # --------------------------------------------------------

    worldwide_terms = [

        "worldwide",

        "work from anywhere",

        "anywhere in the world",

        "global remote",

        "remote anywhere",

        "remote - worldwide",

        "remote / worldwide",

        "location: worldwide",

        "worldwide remote",

    ]

    if any(
        term in text
        for term in worldwide_terms
    ):

        return (
            "REMOTE-WORLDWIDE",
            [
                "Worldwide remote eligibility detected"
            ],
        )

    # --------------------------------------------------------
    # Explicit restrictions
    # --------------------------------------------------------

    restrictions = {

        "US": [

            "us only",
            "usa only",
            "united states only",

            "must be based in the us",
            "must be located in the us",

            "us-based only",

            "us residents only",

        ],

        "UK": [

            "uk only",
            "united kingdom only",

            "must be based in the uk",
            "must be located in the uk",

            "uk-based only",

            "uk residents only",

        ],

        "EU": [

            "eu only",
            "european union only",

            "must be based in the eu",
            "must be located in the eu",

            "eu residents only",

        ],

        "Canada": [

            "canada only",
            "canadian residents only",

            "must be based in canada",
            "must be located in canada",

        ],

    }

    for region, terms in restrictions.items():

        matches = [
            term
            for term in terms
            if term in text
        ]

        if matches:

            return (
                "REMOTE-RESTRICTED",
                [
                    f"Restricted to {region}"
                ],
            )

    # --------------------------------------------------------
    # Generic remote
    # --------------------------------------------------------

    if "remote" in text:

        return (
            "UNKNOWN",
            [
                "Remote work mentioned, "
                "but geographic eligibility "
                "is unclear"
            ],
        )

    # --------------------------------------------------------
    # Unknown
    # --------------------------------------------------------

    return (
        "UNKNOWN",
        [
            "No clear Kenya eligibility found"
        ],
    )


# ============================================================
# HIMALAYAS COLLECTOR
# ============================================================

def fetch_himalayas_jobs() -> list[
    dict[str, Any]
]:

    logger.info(
        "Fetching jobs from Himalayas..."
    )

    keywords = [

        "ICT",
        "IT support",
        "IT technician",

        "help desk",
        "helpdesk",

        "technical support",

        "web developer",

        "frontend developer",

        "software developer",

        "networking",

        "computer technician",

        "JavaScript",

        "React",

        "Node.js",

        "Kotlin",

        "Android",

    ]

    jobs: list[
        dict[str, Any]
    ] = []

    seen_urls: set[str] = set()

    session = requests.Session()

    session.headers.update({

        "User-Agent":
            "Gunga-Job-Radar/1.0",

        "Accept":
            "application/json",

    })

    for keyword in keywords:

        params = {

            "q": keyword,

            "worldwide": "true",

            "sort": "recent",

            "page": 1,

        }

        try:

            response = session.get(
                HIMALAYAS_API,
                params=params,
                timeout=REQUEST_TIMEOUT,
            )

            response.raise_for_status()

            data = response.json()

            raw_jobs = data.get(
                "jobs",
                [],
            )

            if not isinstance(
                raw_jobs,
                list,
            ):

                raw_jobs = []

            for item in raw_jobs:

                if not isinstance(
                    item,
                    dict,
                ):

                    continue

                title = clean_text(
                    item.get("title")
                ).strip()

                company = clean_text(
                    item.get(
                        "companyName"
                    )
                ).strip()

                description = clean_text(
                    item.get(
                        "description"
                    )
                    or item.get(
                        "excerpt"
                    )
                ).strip()

                application_url = clean_text(
                    item.get(
                        "applicationLink"
                    )
                ).strip()

                guid = clean_text(
                    item.get(
                        "guid"
                    )
                ).strip()

                source_url = (
                    application_url
                    or (
                        "https://himalayas.app/jobs/"
                        + guid
                        if guid
                        else ""
                    )
                )

                if not source_url:

                    continue

                if source_url in seen_urls:

                    continue

                seen_urls.add(
                    source_url
                )

                restrictions = (
                    item.get(
                        "locationRestrictions"
                    )
                    or []
                )

                if isinstance(
                    restrictions,
                    list,
                ):

                    location = ", ".join(
                        clean_text(x)
                        for x in restrictions
                        if clean_text(x)
                    )

                else:

                    location = clean_text(
                        restrictions
                    )

                if not location:

                    location = (
                        "Remote / Worldwide"
                    )

                employment_type = clean_text(
                    item.get(
                        "employmentType"
                    )
                )

                categories = (
                    item.get(
                        "categories"
                    )
                    or item.get(
                        "category"
                    )
                    or []
                )

                category_text = clean_text(
                    categories
                )

                min_salary = item.get(
                    "minSalary"
                )

                max_salary = item.get(
                    "maxSalary"
                )

                currency = clean_text(
                    item.get(
                        "currency"
                    )
                )

                salary = ""

                if (
                    min_salary is not None
                    and max_salary is not None
                ):

                    try:

                        salary = (
                            f"{currency} "
                            f"{int(min_salary):,} - "
                            f"{int(max_salary):,}"
                        )

                    except (
                        TypeError,
                        ValueError,
                    ):

                        salary = (
                            f"{currency} "
                            f"{min_salary} - "
                            f"{max_salary}"
                        )

                full_description = "\n".join(

                    part

                    for part in [

                        description,

                        category_text,

                        employment_type,

                        salary,

                    ]

                    if part

                )

                jobs.append({

                    "source":
                        "Himalayas",

                    "source_url":
                        source_url,

                    "title":
                        title
                        or "Untitled",

                    "company":
                        company
                        or "Unknown",

                    "location":
                        location,

                    "description":
                        full_description,

                })

        except requests.RequestException as exc:

            logger.warning(
                "Himalayas request failed "
                "for '%s': %s",
                keyword,
                exc,
            )

        except ValueError as exc:

            logger.warning(
                "Invalid JSON returned by "
                "Himalayas for '%s': %s",
                keyword,
                exc,
            )

        time.sleep(
            HIMALAYAS_REQUEST_DELAY
        )

    logger.info(
        "Himalayas returned %d unique jobs",
        len(jobs),
    )

    return jobs


# ============================================================
# MATCHING ENGINE
# ============================================================

def score_job(
    job: dict[str, Any],
) -> tuple[
    int,
    str,
    list[str],
    list[str],
    list[str],
    list[str],
]:

    title = normalize_text(
        job.get("title")
    )

    location = normalize_text(
        job.get("location")
    )

    description = normalize_text(
        job.get("description")
    )

    combined = " ".join([
        title,
        location,
        description,
    ])

    score = 0

    reasons: list[str] = []

    blockers: list[str] = []

    matched_skills: list[str] = []

    matched_locations: list[str] = []

    # ========================================================
    # LOCATION
    # ========================================================

    (
        location_classification,
        location_evidence,
    ) = classify_location(job)

    if location_classification == "KENYA":

        score += 15

        reasons.append(
            "🇰🇪 Kenya eligibility detected"
        )

    elif location_classification == "REMOTE-AFRICA":

        score += 15

        reasons.append(
            "🌍 Remote role accepts Africa"
        )

    elif location_classification == "REMOTE-WORLDWIDE":

        score += 15

        reasons.append(
            "🌍 Remote role appears worldwide"
        )

    elif location_classification == "REMOTE-RESTRICTED":

        score -= 30

        blockers.extend(
            location_evidence
        )

        reasons.append(
            "⚠️ Geographic restriction detected"
        )

    else:

        score += 3

        reasons.append(
            "❓ Location eligibility unclear"
        )

    # ========================================================
    # TITLE
    # ========================================================

    title_matches = [

        role

        for role in PROFILE[
            "target_titles"
        ]

        if role in title

    ]

    if title_matches:

        score += 30

        reasons.append(
            "Title strongly matches a "
            "target ICT role"
        )

    # ========================================================
    # SKILLS
    # ========================================================

    for skill in PROFILE[
        "skills"
    ]:

        if skill in combined:

            matched_skills.append(
                skill
            )

    skill_points = min(
        len(matched_skills) * 5,
        25,
    )

    score += skill_points

    if matched_skills:

        reasons.append(
            "Matching skills: "
            + ", ".join(
                matched_skills[:6]
            )
        )

    # ========================================================
    # EDUCATION
    # ========================================================

    education_terms = [

        "diploma",
        "certificate",

        "entry level",
        "entry-level",

        "intern",
        "internship",

        "trainee",
        "junior",

        "graduate",

        "attachment",

        "no experience",

        "no experience required",

    ]

    education_matches = [

        term

        for term in education_terms

        if term in combined

    ]

    if education_matches:

        score += 15

        reasons.append(
            "Entry-level/diploma-friendly "
            "language detected"
        )

    # ========================================================
    # EXPERIENCE
    # ========================================================

    experience_terms = [

        "junior",

        "entry level",
        "entry-level",

        "intern",
        "internship",

        "trainee",

        "graduate",

        "no experience",

        "no experience required",

        "no experience necessary",

    ]

    if any(
        term in combined
        for term in experience_terms
    ):

        score += 10

        reasons.append(
            "Experience requirements "
            "appear suitable"
        )

    # ========================================================
    # PREFERRED LOCATIONS
    # ========================================================

    for preferred_location in PROFILE[
        "locations_preferred"
    ]:

        if preferred_location in combined:

            matched_locations.append(
                preferred_location
            )

    if matched_locations:

        reasons.append(
            "Preferred location mentioned: "
            + ", ".join(
                matched_locations[:4]
            )
        )

    # ========================================================
    # NEGATIVES
    # ========================================================

    for blocker in PROFILE[
        "soft_negatives"
    ]:

        if blocker in combined:

            blockers.append(
                blocker
            )

    score -= (
        len(blockers) * 10
    )

    # ========================================================
    # EXTRA RESTRICTION PENALTY
    # ========================================================

    if location_classification == (
        "REMOTE-RESTRICTED"
    ):

        score -= 20

    # ========================================================
    # SCORE NORMALIZATION
    # ========================================================

    score = max(
        0,
        min(
            100,
            score,
        ),
    )

    # ========================================================
    # TIER
    # ========================================================

    if score >= STRONG_MATCH_THRESHOLD:

        tier = "strong"

    elif score >= CONSIDER_THRESHOLD:

        tier = "consider"

    else:

        tier = "poor"

    # ========================================================
    # FINAL ELIGIBILITY REASON
    # ========================================================

    reasons.append(
        "Eligibility: "
        + location_classification
    )

    return (
        score,
        tier,
        reasons,
        blockers,
        matched_skills,
        matched_locations,
    )


# ============================================================
# DATABASE
# ============================================================

def build_database() -> Database:

    require_environment(
        "DATABASE_URL"
    )

    return Database(
        DATABASE_URL
    )


def save_job(
    database: Database,
    job: dict[str, Any],
    score: int,
    tier: str,
    reasons: list[str],
    blockers: list[str],
    matched_skills: list[str],
    matched_locations: list[str],
) -> int | None:

    payload = {

        "source":
            job["source"],

        "source_url":
            job["source_url"],

        "title":
            job["title"],

        "company":
            job["company"],

        "location":
            job["location"],

        "description":
            job["description"][:10000],

        "score":
            score,

        "tier":
            tier,

        "reasons":
            "; ".join(
                reasons
            ),

        "blockers":
            "; ".join(
                blockers
            ),

    }

    return database.insert_job(
        payload
    )


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram_alert(
    job: dict[str, Any],
    score: int,
    reasons: list[str],
) -> bool:

    require_environment(
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
    )

    message = (
        "🔔 NEW STRONG MATCH\n\n"

        f"🎯 Match score: {score}%\n"

        f"💼 {job['title']}\n"

        f"🏢 {job['company']}\n"

        f"📍 {job['location']}\n\n"

        "Why it matches:\n"

        + (
            "\n".join(
                f"• {reason}"
                for reason in reasons
            )
            if reasons
            else "• Good overall fit"
        )

        + "\n\n"

        f"🔗 {job['source_url']}"
    )

    telegram_url = (
        "https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}"
        "/sendMessage"
    )

    response = requests.post(

        telegram_url,

        data={

            "chat_id":
                TELEGRAM_CHAT_ID,

            "text":
                message,

            "disable_web_page_preview":
                False,

        },

        timeout=30,

    )

    response.raise_for_status()

    result = response.json()

    if not result.get(
        "ok",
        False,
    ):

        raise RuntimeError(
            "Telegram rejected message: "
            f"{result}"
        )

    return True


# ============================================================
# GMAIL DIGEST
# ============================================================

def send_gmail_digest(
    jobs: list[dict[str, Any]],
) -> bool:

    if not jobs:

        logger.info(
            "No undigested jobs. "
            "Skipping Gmail digest."
        )

        return False

    require_environment(
        "GMAIL_ADDRESS",
        "GMAIL_APP_PASSWORD",
    )

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

        f"🟢 Strong matches: {len(strong)}",

        (
            f"🟡 Worth considering: "
            f"{len(consider)}"
        ),

        f"🔴 Poor matches: {len(poor)}",

        "",

    ]

    groups = [

        (
            "🟢 STRONG MATCHES",
            strong,
        ),

        (
            "🟡 WORTH CONSIDERING",
            consider,
        ),

    ]

    for heading, group in groups:

        if not group:

            continue

        lines.extend([

            "",

            "=" * 50,

            heading,

            "=" * 50,

        ])

        for job in sorted(

            group,

            key=lambda item:
                -int(
                    item["score"]
                    or 0
                ),

        ):

            lines.extend([

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

            ])

    body = "\n".join(
        lines
    )

    message = MIMEMultipart()

    message["From"] = (
        GMAIL_ADDRESS
    )

    message["To"] = (
        GMAIL_ADDRESS
    )

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

    with smtplib.SMTP(
        "smtp.gmail.com",
        587,
        timeout=30,
    ) as server:

        server.starttls()

        server.login(
            GMAIL_ADDRESS,
            GMAIL_APP_PASSWORD,
        )

        server.send_message(
            message
        )

    logger.info(
        "Gmail digest sent successfully."
    )

    return True


# ============================================================
# SCAN
# ============================================================

def run_scan(
    database: Database,
) -> None:

    logger.info(
        "========== SCAN START =========="
    )

    jobs = fetch_himalayas_jobs()

    logger.info(
        "Processing %d jobs...",
        len(jobs),
    )

    new_jobs = 0

    strong_matches = 0

    for job in jobs:

        source_url = job.get(
            "source_url"
        )

        if not source_url:

            continue

        try:

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
                matched_locations,
            ) = score_job(
                job
            )

            job_id = save_job(

                database,

                job,

                score,

                tier,

                reasons,

                blockers,

                matched_skills,

                matched_locations,

            )

            if job_id is None:

                continue

            new_jobs += 1

            logger.info(

                "NEW JOB | %s | %s%% | %s",

                job["title"],

                score,

                tier,

            )

            if tier == "strong":

                strong_matches += 1

                try:

                    send_telegram_alert(

                        job,

                        score,

                        reasons,

                    )

                    database.mark_telegram_sent(
                        job_id
                    )

                    logger.info(

                        "Telegram alert sent "
                        "for job %s",

                        job_id,

                    )

                except Exception as exc:

                    logger.error(

                        "Telegram alert failed "
                        "for job %s: %s",

                        job_id,

                        exc,

                    )

        except DatabaseError as exc:

            logger.error(

                "Database error processing "
                "%s: %s",

                source_url,

                exc,

            )

        except Exception as exc:

            logger.exception(

                "Unexpected error processing job: %s",

                exc,

            )

    logger.info(
        "New jobs saved: %d",
        new_jobs,
    )

    logger.info(
        "Strong matches: %d",
        strong_matches,
    )

    logger.info(
        "========== SCAN COMPLETE =========="
    )


# ============================================================
# DIGEST
# ============================================================

def run_digest(
    database: Database,
) -> None:

    logger.info(
        "========== DIGEST START =========="
    )

    jobs = database.get_undigested_jobs()

    logger.info(
        "%d jobs pending digest",
        len(jobs),
    )

    if not jobs:

        logger.info(
            "Nothing to send."
        )

        logger.info(
            "========== DIGEST COMPLETE =========="
        )

        return

    try:

        send_gmail_digest(
            jobs
        )

        job_ids = [

            int(job["id"])

            for job in jobs

            if job.get("id") is not None

        ]

        database.mark_jobs_digested(
            job_ids
        )

        logger.info(
            "Marked %d jobs as digested.",
            len(job_ids),
        )

    except Exception as exc:

        logger.exception(

            "Digest failed. "
            "Jobs were NOT marked "
            "as digested: %s",

            exc,

        )

        raise

    logger.info(
        "========== DIGEST COMPLETE =========="
    )


# ============================================================
# MAIN
# ============================================================

def main() -> int:

    parser = argparse.ArgumentParser(

        description=(
            "Gunga Job Radar"
        )

    )

    parser.add_argument(

        "--mode",

        choices=[
            "scan",
            "digest",
            "both",
        ],

        default="both",

        help=(
            "Operation to run."
        ),

    )

    args = parser.parse_args()

    logger.info(

        "Starting Gunga Job Radar "
        "in %s mode...",

        args.mode,

    )

    database = build_database()

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

    except Exception as exc:

        logger.exception(
            "Fatal error: %s",
            exc,
        )

        return 1

    logger.info(
        "Gunga Job Radar finished successfully."
    )

    return 0


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    raise SystemExit(
        main()
)
