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
from dataclasses import dataclass
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

MYJOBMAG_FEED_URL = (
    "https://www.myjobmag.co.ke/feeds/jobsxml.xml"
)

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
# JOB MODEL
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
# TEXT HELPERS
# ============================================================

def clean_text(
    value: str | None,
) -> str:

    if not value:
        return ""

    value = html.unescape(value)

    value = re.sub(
        r"<[^>]+>",
        " ",
        value,
    )

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    return value.strip()


def normalize_for_matching(
    value: str,
) -> str:

    value = clean_text(
        value
    ).lower()

    value = value.replace(
        "’",
        "'",
    )

    value = value.replace(
        "/",
        " ",
    )

    value = value.replace(
        "-",
        " ",
    )

    return value


def contains_phrase(
    text: str,
    phrase: str,
) -> bool:

    text = normalize_for_matching(
        text
    )

    phrase = normalize_for_matching(
        phrase
    )

    pattern = (
        r"(?<!\w)"
        + re.escape(phrase)
        + r"(?!\w)"
    )

    return (
        re.search(
            pattern,
            text,
        )
        is not None
    )


def truncate(
    text: str,
    length: int,
) -> str:

    if len(text) <= length:
        return text

    return (
        text[:length].rstrip()
        + "..."
    )


# ============================================================
# LOCATION
# ============================================================

LOCATION_ALIASES = {
    "malindi": [
        "malindi",
    ],

    "kilifi": [
        "kilifi",
    ],

    "mombasa": [
        "mombasa",
    ],

    "nairobi": [
        "nairobi",
    ],

    "remote": [
        "remote",
        "work from home",
        "work-from-home",
        "fully remote",
        "remote work",
    ],

    "kenya": [
        "kenya",
        "nationwide",
        "all counties",
    ],
}


def extract_locations(
    title: str,
    description: str,
) -> list[str]:

    text = (
        f"{title} "
        f"{description}"
    )

    found = []

    for canonical, aliases in (
        LOCATION_ALIASES.items()
    ):

        for alias in aliases:

            if contains_phrase(
                text,
                alias,
            ):

                found.append(
                    canonical
                )

                break

    return list(
        dict.fromkeys(found)
    )


def extract_location(
    title: str,
    description: str,
) -> str:

    locations = extract_locations(
        title,
        description,
    )

    if not locations:
        return "Kenya"

    priority = [
        "malindi",
        "kilifi",
        "mombasa",
        "remote",
        "nairobi",
        "kenya",
    ]

    for location in priority:

        if location in locations:
            return location.title()

    return locations[0].title()


# ============================================================
# COMPANY EXTRACTION
# ============================================================

def extract_company(
    title: str,
    description: str = "",
) -> str:

    patterns = [
        r"\bat\s+(.+)$",
        r"\s[-|]\s(.+)$",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            title,
            re.IGNORECASE,
        )

        if match:

            company = clean_text(
                match.group(1)
            )

            if company:
                return company

    match = re.search(
        r"(?:company|employer|organization)"
        r"\s*:\s*([^.;]+)",
        description,
        re.IGNORECASE,
    )

    if match:

        return clean_text(
            match.group(1)
        )

    return "Unknown"


# ============================================================
# MYJOBMAG COLLECTOR
# ============================================================

def fetch_myjobmag_jobs(
    limit: int = MAX_JOBS_PER_SOURCE,
) -> list[Job]:

    logger.info(
        "Fetching MyJobMag jobs..."
    )

    headers = {
        "User-Agent": (
            "GungaJobRadar/3.0 "
            "(personal job alert tool)"
        )
    }

    response = requests.get(
        MYJOBMAG_FEED_URL,
        timeout=REQUEST_TIMEOUT,
        headers=headers,
    )

    response.raise_for_status()

    root = ET.fromstring(
        response.content
    )

    jobs: list[Job] = []

    items = root.findall(
        ".//item"
    )

    for item in items[:limit]:

        title = clean_text(
            item.findtext(
                "title"
            )
        )

        link = clean_text(
            item.findtext(
                "link"
            )
        )

        description = clean_text(
            item.findtext(
                "description"
            )
        )

        industry = clean_text(
            item.findtext(
                "industry"
            )
        )

        if not title or not link:
            continue

        if industry:

            description = (
                f"[{industry}] "
                f"{description}"
            )

        description = truncate(
            description,
            MAX_DESCRIPTION_LENGTH,
        )

        company = extract_company(
            title,
            description,
        )

        location = extract_location(
            title,
            description,
        )

        jobs.append(
            Job(
                source="MyJobMag",
                source_url=link,
                title=title,
                company=company,
                location=location,
                description=description,
            )
        )

    logger.info(
        "MyJobMag returned %d jobs",
        len(jobs),
    )

    return jobs


# ============================================================
# MATCHING ENGINE
# ============================================================

def score_job(
    job: Job,
) -> MatchResult:

    title_text = normalize_for_matching(
        job.title
    )

    full_text = normalize_for_matching(
        (
            f"{job.title} "
            f"{job.description} "
            f"{job.location}"
        )
    )

    score = 0

    reasons: list[str] = []

    blockers: list[str] = []

    # --------------------------------------------------------
    # TARGET TITLE
    # --------------------------------------------------------

    matched_titles = [
        title
        for title in PROFILE[
            "target_titles"
        ]
        if contains_phrase(
            title_text,
            title,
        )
    ]

    if matched_titles:

        score += 30

        reasons.append(
            "Target role: "
            + matched_titles[0]
        )

    # --------------------------------------------------------
    # LOCATION
    # --------------------------------------------------------

    matched_locations = []

    for location in PROFILE[
        "preferred_locations"
    ]:

        if location == "kenya":
            continue

        if contains_phrase(
            full_text,
            location,
        ):

            matched_locations.append(
                location
            )

    if matched_locations:

        if any(
            location in {
                "malindi",
                "kilifi",
                "mombasa",
            }
            for location
            in matched_locations
        ):

            score += 20

            reasons.append(
                "Preferred Coast location"
            )

        elif "remote" in matched_locations:

            score += 20

            reasons.append(
                "Remote opportunity"
            )

        elif "nairobi" in matched_locations:

            score += 15

            reasons.append(
                "Preferred Nairobi location"
            )

    elif contains_phrase(
        full_text,
        "kenya",
    ):

        score += 8

        reasons.append(
            "Kenya-based opportunity"
        )

    # --------------------------------------------------------
    # SKILLS
    # --------------------------------------------------------

    matched_skills = [
        skill
        for skill in PROFILE[
            "skills"
        ]
        if contains_phrase(
            full_text,
            skill,
        )
    ]

    skill_points = min(
        len(matched_skills) * 5,
        25,
    )

    score += skill_points

    if matched_skills:

        reasons.append(
            "Skills: "
            + ", ".join(
                matched_skills[:5]
            )
        )

    # --------------------------------------------------------
    # EDUCATION / ENTRY LEVEL
    # --------------------------------------------------------

    education_matches = [
        signal
        for signal in PROFILE[
            "education_signals"
        ]
        if contains_phrase(
            full_text,
            signal,
        )
    ]

    if education_matches:

        score += 15

        reasons.append(
            "Diploma/entry-level friendly"
        )

    # --------------------------------------------------------
    # EXPERIENCE PENALTIES
    # --------------------------------------------------------

    for penalty in PROFILE[
        "experience_penalties"
    ]:

        if contains_phrase(
            full_text,
            penalty,
        ):

            score -= 12

            blockers.append(
                penalty
            )

    # --------------------------------------------------------
    # HARD REQUIREMENTS
    # --------------------------------------------------------

    for penalty in PROFILE[
        "hard_requirement_penalties"
    ]:

        if contains_phrase(
            full_text,
            penalty,
        ):

            score -= 10

            blockers.append(
                penalty
            )

    # --------------------------------------------------------
    # INTERNSHIP BOOST
    # --------------------------------------------------------

    internship_terms = [
        "internship",
        "intern",
        "industrial attachment",
        "attachment",
    ]

    if any(
        contains_phrase(
            full_text,
            term,
        )
        for term in internship_terms
    ):

        score += 5

        reasons.append(
            "Internship/attachment opportunity"
        )

    # --------------------------------------------------------
    # JUNIOR BOOST
    # --------------------------------------------------------

    junior_terms = [
        "junior",
        "trainee",
        "entry level",
        "entry-level",
    ]

    if any(
        contains_phrase(
            title_text,
            term,
        )
        for term in junior_terms
    ):

        score += 5

        reasons.append(
            "Junior/entry-level role"
        )

    # --------------------------------------------------------
    # NORMALIZE SCORE
    # --------------------------------------------------------

    score = max(
        0,
        min(
            score,
            100,
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

    return MatchResult(
        score=score,
        tier=tier,
        reasons=list(
            dict.fromkeys(
                reasons
            )
        ),
        blockers=list(
            dict.fromkeys(
                blockers
            )
        ),
        matched_skills=matched_skills,
        matched_locations=matched_locations,
    )


# ============================================================
# DATABASE JOB PAYLOAD
# ============================================================

def build_job_payload(
    job: Job,
    result: MatchResult,
) -> dict:

    return {
        "source": job.source,

        "source_url": job.source_url,

        "title": job.title,

        "company": job.company,

        "location": job.location,

        "description": job.description,

        "employment_type": None,

        "salary": None,

        "category": None,

        "published_at": None,

        "deadline": None,

        "score": result.score,

        "tier": result.tier,

        "reasons": "; ".join(
            result.reasons
        ),

        "blockers": "; ".join(
            result.blockers
        ),

        "matched_skills": "; ".join(
            result.matched_skills
        ),

        "matched_locations": "; ".join(
            result.matched_locations
        ),
    }


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram_alert(
    job: Job,
    result: MatchResult,
) -> bool:

    token = os.getenv(
        "TELEGRAM_BOT_TOKEN"
    )

    chat_id = os.getenv(
        "TELEGRAM_CHAT_ID"
    )

    if not token or not chat_id:

        logger.warning(
            "Telegram credentials missing."
        )

        return False

    reasons = (
        " • ".join(
            result.reasons[:4]
        )
        if result.reasons
        else "Good overall match"
    )

    blockers = ""

    if result.blockers:

        blockers = (
            "\n⚠️ "
            + ", ".join(
                result.blockers[:3]
            )
        )

    message = (
        "🔔 GUNGA JOB RADAR\n\n"
        f"🔥 MATCH: {result.score}%\n"
        f"💼 {job.title}\n"
        f"🏢 {job.company}\n"
        f"📍 {job.location}\n\n"
        f"✅ {reasons}"
        f"{blockers}\n\n"
        f"🔗 {job.source_url}"
    )

    url = (
        "https://api.telegram.org/"
        f"bot{token}/sendMessage"
    )

    for attempt in range(
        1,
        TELEGRAM_RETRIES + 1,
    ):

        try:

            response = requests.post(
                url,
                data={
                    "chat_id": chat_id,
                    "text": message,
                    "disable_web_page_preview": False,
                },
                timeout=REQUEST_TIMEOUT,
            )

            response.raise_for_status()

            logger.info(
                "Telegram alert sent: %s",
                job.title,
            )

            return True

        except requests.RequestException as exc:

            logger.warning(
                "Telegram attempt %d/%d failed: %s",
                attempt,
                TELEGRAM_RETRIES,
                exc,
            )

            if attempt < TELEGRAM_RETRIES:

                time.sleep(
                    2 ** attempt
                )

    return False


# ============================================================
# EMAIL DIGEST
# ============================================================

def send_gmail_digest(
    jobs: list[dict],
) -> bool:

    if not jobs:

        logger.info(
            "No jobs waiting for digest."
        )

        return True

    address = os.getenv(
        "GMAIL_ADDRESS"
    )

    password = os.getenv(
        "GMAIL_APP_PASSWORD"
    )

    if not address or not password:

        logger.warning(
            "Gmail credentials missing."
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

    lines = [
        "GUNGA JOB RADAR",
        "Daily job digest",
        "",
        f"Total new matches: {len(jobs)}",
        f"Strong matches: {len(strong)}",
        f"Consider: {len(consider)}",
        "",
    ]

    groups = [
        (
            "🔥 STRONG MATCHES",
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

        lines.append("")
        lines.append(heading)
        lines.append("-" * 40)

        for job in sorted(
            group,
            key=lambda item: -item["score"],
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
            (
                "Generated automatically "
                "by Gunga Job Radar."
            ),
        ]
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
            "\n".join(lines),
            "plain",
            "utf-8",
        )
    )

    for attempt in range(
        1,
        EMAIL_RETRIES + 1,
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
                "Email attempt %d/%d failed: %s",
                attempt,
                EMAIL_RETRIES,
                exc,
            )

            if attempt < EMAIL_RETRIES:

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

    jobs = fetch_myjobmag_jobs()

    fetched = len(jobs)

    new_jobs = 0

    saved_jobs = 0

    strong_jobs = 0

    skipped_jobs = 0

    for job in jobs:

        try:

            # ------------------------------------------------
            # DUPLICATE
            # ------------------------------------------------

            if database.job_exists(
                job.source_url
            ):

                continue

            # ------------------------------------------------
            # MATCH
            # ------------------------------------------------

            result = score_job(
                job
            )

            new_jobs += 1

            logger.info(
                "%3d%% | %-8s | %s",
                result.score,
                result.tier,
                job.title,
            )

            # ------------------------------------------------
            # LOW SCORE
            # ------------------------------------------------

            if (
                result.score
                < MIN_SAVE_SCORE
            ):

                skipped_jobs += 1

                continue

            # ------------------------------------------------
            # SAVE
            # ------------------------------------------------

            payload = build_job_payload(
                job,
                result,
            )

            inserted = database.insert_job(
                payload
            )

            if not inserted:
                continue

            saved_jobs += 1

            # ------------------------------------------------
            # MATCH RECORD
            # ------------------------------------------------

            # The database layer records the match
            # after the job has been inserted.

            # Retrieve the job by URL through the
            # database connection only when necessary.
            #
            # The existing insert API deliberately returns
            # a boolean for compatibility, so match tracking
            # is handled by the next database-layer upgrade.

            # ------------------------------------------------
            # TELEGRAM
            # ------------------------------------------------

            if result.tier == "strong":

                strong_jobs += 1

                sent = send_telegram_alert(
                    job,
                    result,
                )

                if sent:

                    # The current database API needs
                    # the job ID to mark the notification.
                    #
                    # The job itself is already stored.
                    #
                    # Notification reconciliation is handled
                    # by the notification worker in Phase 3B.

                    logger.info(
                        "Strong job notification "
                        "completed: %s",
                        job.title,
                    )

        except Exception as exc:

            logger.exception(
                "Failed processing job '%s': %s",
                job.title,
                exc,
            )

    logger.info(
        "Scan summary: "
        "fetched=%d new=%d saved=%d "
        "strong=%d skipped=%d",
        fetched,
        new_jobs,
        saved_jobs,
        strong_jobs,
        skipped_jobs,
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

    if not jobs:

        logger.info(
            "No jobs waiting for digest."
        )

        return

    sent = send_gmail_digest(
        jobs
    )

    if not sent:

        logger.warning(
            "Digest failed. "
            "Jobs remain pending."
        )

        return

    job_ids = [
        str(job["id"])
        for job in jobs
    ]

    database.mark_jobs_digested(
        job_ids
    )

    logger.info(
        "Marked %d jobs as digested.",
        len(job_ids),
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
            "DATABASE_URL is not configured."
        )

        return 1

    database = Database(
        database_url
    )

    logger.info(
        "%s v%s starting...",
        APP_NAME,
        APP_VERSION,
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

        logger.warning(
            "Interrupted by user."
        )

        return 130

    except Exception as exc:

        logger.exception(
            "Fatal Job Radar error: %s",
            exc,
        )

        return 1

    logger.info(
        "Job Radar finished."
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())from email.mime.text import MIMEText
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
