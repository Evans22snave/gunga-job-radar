"""
Gunga Job Radar
Phase 4 — Kenya-aware job matching

Pipeline:

    Himalayas API   MyJobMag (Kenya)
          ↓               ↓
          └───────┬───────┘
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
import html
import logging
import os
import re
import smtplib
import time
from datetime import date, datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

import requests
from bs4 import BeautifulSoup
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

MYJOBMAG_CATEGORY_URLS = [

    "https://www.myjobmag.co.ke/jobs-by-field/information-technology",

    "https://www.myjobmag.co.ke/jobs-by-field/internships",

]

MYJOBMAG_MAX_PAGES = 3

MYJOBMAG_REQUEST_DELAY = 1.0

BRIGHTERMONDAY_CATEGORY_URLS = [

    "https://www.brightermonday.co.ke/jobs/it-telecoms",

    "https://www.brightermonday.co.ke/jobs/software-data",

]

BRIGHTERMONDAY_MAX_PAGES = 3

BRIGHTERMONDAY_REQUEST_DELAY = 1.0

OPENEDCAREER_CATEGORY_URLS = [

    "https://openedcareer.com/category/jobs/information-technology-ict/",

    "https://openedcareer.com/category/internships/information-technology-ict-internships/",

]

OPENEDCAREER_MAX_PAGES = 3

OPENEDCAREER_REQUEST_DELAY = 1.0

# Fixed set of location values BrighterMonday itself filters by —
# longest-first so "Rest of Kenya" matches before the bare "Kenya"
# substring inside it.
BRIGHTERMONDAY_LOCATIONS = [

    "Remote (Work From Home)",

    "Outside Kenya",

    "Rest of Kenya",

    "Nairobi",

    "Kenya",

]

STRONG_MATCH_THRESHOLD = 75

CONSIDER_THRESHOLD = 45

# Phase 4 weighted scoring — weights sum to 100
WEIGHT_TITLE = 30
WEIGHT_SKILLS = 25
WEIGHT_EDUCATION = 15
WEIGHT_EXPERIENCE = 10
WEIGHT_LOCATION = 10
WEIGHT_EMPLOYMENT_TYPE = 5
WEIGHT_FRESHNESS = 5

FRESHNESS_FULL_DAYS = 14
FRESHNESS_PARTIAL_DAYS = 30

ELIGIBILITY_LABELS = {

    "KENYA":
        "🇰🇪 KENYA ELIGIBLE",

    "REMOTE-AFRICA":
        "🌍 AFRICA ELIGIBLE",

    "REMOTE-WORLDWIDE":
        "🌍 WORLDWIDE REMOTE",

    "REMOTE-RESTRICTED":
        "⚠️ LOCATION RESTRICTED",

    "UNKNOWN":
        "❓ LOCATION UNCLEAR",

}

EMPLOYMENT_TYPE_TERMS = [

    "internship",
    "intern",

    "attachment",

    "graduate trainee",

    "full-time",
    "full time",

    "part-time",
    "part time",

    "contract",

    "temporary",

]


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

                posted_raw = (
                    item.get("pubDate")
                    or item.get("publishedAt")
                    or item.get("postedAt")
                    or item.get("createdAt")
                )

                posted_date = None

                if posted_raw:

                    try:

                        posted_date = (
                            datetime.fromisoformat(
                                str(posted_raw)
                                .replace(
                                    "Z",
                                    "+00:00",
                                )
                            )
                            .date()
                            .isoformat()
                        )

                    except ValueError:

                        posted_date = None

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

                    "employment_type":
                        employment_type,

                    "posted_date":
                        posted_date,

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
# MYJOBMAG COLLECTOR
# ============================================================

MONTHS_PATTERN = (
    "January|February|March|April|May|June|"
    "July|August|September|October|November|December"
)

DATE_RE = re.compile(
    r"\b\d{1,2}\s+(?:" + MONTHS_PATTERN + r")\b"
)

MONTH_NUMBERS = {

    name: index

    for index, name in enumerate(
        MONTHS_PATTERN.split("|"),
        start=1,
    )

}


def parse_myjobmag_posted_date(
    posted_text: str,
) -> str | None:
    """Convert MyJobMag's "28 August" style date to ISO.

    MyJobMag omits the year, so we assume the current year
    unless that would place the date in the future (which
    means it was actually posted last year).
    """

    if not posted_text:
        return None

    match = re.match(
        r"(\d{1,2})\s+(\w+)",
        posted_text.strip(),
    )

    if not match:
        return None

    day_str, month_name = match.groups()

    month = MONTH_NUMBERS.get(
        month_name
    )

    if not month:
        return None

    today = date.today()

    try:

        candidate = date(
            today.year,
            month,
            int(day_str),
        )

    except ValueError:

        return None

    if candidate > today:

        try:

            candidate = date(
                today.year - 1,
                month,
                int(day_str),
            )

        except ValueError:

            return None

    return candidate.isoformat()


def parse_myjobmag_page(
    html: str,
) -> list[dict[str, Any]]:
    """Parse one MyJobMag category page into raw job dicts.

    MyJobMag renders each listing's job title as a heading
    (h2/h3) wrapping a link to /job/<slug>. Sidebar links
    ("Current Jobs", "You May Like") are plain <a> tags with
    no wrapping heading, so anchoring on headings keeps this
    scoped to the actual listings and skips the sidebar noise.
    """

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    results: list[dict[str, Any]] = []

    seen_hrefs: set[str] = set()

    for heading in soup.find_all(
        ["h2", "h3"]
    ):

        link = heading.find(
            "a",
            href=True,
        )

        if not link:
            continue

        href = link["href"]

        if "/job/" not in href:
            continue

        if href.startswith("/"):
            href = (
                "https://www.myjobmag.co.ke"
                + href
            )

        if href in seen_hrefs:
            continue

        seen_hrefs.add(href)

        heading_text = clean_text(
            link.get_text()
        ).strip()

        # Titles are formatted "<Title> at <Company>"
        if " at " in heading_text:

            title, _, company = (
                heading_text.rpartition(
                    " at "
                )
            )

        else:

            title, company = (
                heading_text,
                "Unknown",
            )

        container = (
            heading.find_parent("li")
            or heading.find_parent("div")
            or heading
        )

        container_text = " ".join(
            container.get_text(
                separator=" "
            ).split()
        )

        location_link = container.find(
            "a",
            href=lambda h: bool(h) and (
                "/jobs-location/" in h
            ),
        )

        location = (
            clean_text(
                location_link.get_text()
            ).strip()
            if location_link
            else ""
        )

        date_match = DATE_RE.search(
            container_text
        )

        posted = (
            date_match.group(0)
            if date_match
            else ""
        )

        description = container_text

        for fragment in (
            heading_text,
            location,
            posted,
        ):

            if fragment:

                description = (
                    description.replace(
                        fragment,
                        " ",
                    )
                )

        description = normalize_text(
            description
        )

        results.append({

            "source":
                "MyJobMag",

            "source_url":
                href,

            "title":
                title.strip()
                or "Untitled",

            "company":
                company.strip()
                or "Unknown",

            "location":
                location
                or "Kenya",

            "description":
                (
                    description
                    + (
                        f" posted {posted}"
                        if posted
                        else ""
                    )
                ),

            "employment_type":
                "",

            "posted_date":
                parse_myjobmag_posted_date(
                    posted
                ),

        })

    return results


def fetch_myjobmag_jobs() -> list[
    dict[str, Any]
]:

    logger.info(
        "Fetching jobs from MyJobMag..."
    )

    jobs: list[dict[str, Any]] = []

    seen_urls: set[str] = set()

    session = requests.Session()

    session.headers.update({

        "User-Agent":
            "Mozilla/5.0 (compatible; "
            "Gunga-Job-Radar/1.0)",

        "Accept":
            "text/html",

    })

    for category_url in (
        MYJOBMAG_CATEGORY_URLS
    ):

        for page in range(
            1,
            MYJOBMAG_MAX_PAGES + 1,
        ):

            url = (
                category_url
                if page == 1
                else f"{category_url}/{page}"
            )

            try:

                response = session.get(
                    url,
                    timeout=REQUEST_TIMEOUT,
                )

                if response.status_code == 404:
                    break

                response.raise_for_status()

                page_jobs = parse_myjobmag_page(
                    response.text
                )

                if not page_jobs:
                    break

                new_on_page = 0

                for job in page_jobs:

                    if job["source_url"] in seen_urls:
                        continue

                    seen_urls.add(
                        job["source_url"]
                    )

                    jobs.append(job)

                    new_on_page += 1

                # Ran into a page of jobs we've already
                # seen (categories overlap) — stop paging.
                if new_on_page == 0:
                    break

            except requests.RequestException as exc:

                logger.warning(
                    "MyJobMag request failed "
                    "for '%s': %s",
                    url,
                    exc,
                )

                break

            time.sleep(
                MYJOBMAG_REQUEST_DELAY
            )

    logger.info(
        "MyJobMag returned %d unique jobs",
        len(jobs),
    )

    return jobs


# ============================================================
# BRIGHTERMONDAY COLLECTOR
# ============================================================

POSTED_RELATIVE_RE = re.compile(
    r"\b(Today|Yesterday|\d+\s+"
    r"(?:day|days|week|weeks|month|months)"
    r"\s+ago)\b",
    re.IGNORECASE,
)


def parse_brightermonday_posted(
    text: str,
) -> str | None:
    """Convert "3 days ago" / "Today" style text to an ISO date."""

    match = POSTED_RELATIVE_RE.search(
        text
    )

    if not match:
        return None

    phrase = match.group(1).lower()

    today = date.today()

    if phrase == "today":

        return today.isoformat()

    if phrase == "yesterday":

        return (
            today
            - timedelta(days=1)
        ).isoformat()

    number_match = re.match(
        r"(\d+)\s+(day|week|month)",
        phrase,
    )

    if not number_match:
        return None

    amount = int(
        number_match.group(1)
    )

    unit = number_match.group(2)

    days = {

        "day": amount,

        "week": amount * 7,

        "month": amount * 30,

    }[unit]

    return (
        today
        - timedelta(days=days)
    ).isoformat()


def parse_brightermonday_page(
    html: str,
) -> list[dict[str, Any]]:
    """Parse one BrighterMonday category page into raw job dicts.

    Job listings link to /listings/<slug>. That href pattern is
    unique to actual job cards — sidebar filter links, pagination,
    and company-profile links all use different paths — so
    anchoring on it (rather than guessing CSS classes we can't
    see) keeps this scoped correctly.
    """

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    results: list[dict[str, Any]] = []

    seen_hrefs: set[str] = set()

    for link in soup.find_all(
        "a",
        href=True,
    ):

        href = link["href"]

        if "/listings/" not in href:
            continue

        if href.startswith("/"):
            href = (
                "https://www.brightermonday.co.ke"
                + href
            )

        href = href.split("?")[0]

        if href in seen_hrefs:
            continue

        title = clean_text(
            link.get_text()
        ).strip()

        if not title:
            continue

        seen_hrefs.add(href)

        container = (
            link.find_parent("li")
            or link.find_parent("article")
            or link.find_parent("div")
            or link
        )

        container_text = " ".join(
            container.get_text(
                separator=" "
            ).split()
        )

        remainder = container_text.replace(
            title,
            " ",
            1,
        )

        location = "Kenya"

        location_start = len(
            remainder
        )

        for candidate in (
            BRIGHTERMONDAY_LOCATIONS
        ):

            idx = remainder.find(
                candidate
            )

            if idx != -1 and idx < location_start:

                location_start = idx

                location = (
                    "Remote"
                    if "Remote" in candidate
                    else candidate
                )

        company = remainder[
            :location_start
        ].strip(
            " -|"
        )

        if (
            not company
            or len(company) > 80
        ):

            company = "Unknown"

        posted_date = (
            parse_brightermonday_posted(
                container_text
            )
        )

        description = normalize_text(
            remainder
        )

        results.append({

            "source":
                "BrighterMonday",

            "source_url":
                href,

            "title":
                title,

            "company":
                company,

            "location":
                location,

            "description":
                description,

            "employment_type":
                "",

            "posted_date":
                posted_date,

        })

    return results


def fetch_brightermonday_jobs() -> list[
    dict[str, Any]
]:

    logger.info(
        "Fetching jobs from BrighterMonday..."
    )

    jobs: list[dict[str, Any]] = []

    seen_urls: set[str] = set()

    session = requests.Session()

    session.headers.update({

        "User-Agent":
            "Mozilla/5.0 (compatible; "
            "Gunga-Job-Radar/1.0)",

        "Accept":
            "text/html",

    })

    for category_url in (
        BRIGHTERMONDAY_CATEGORY_URLS
    ):

        for page in range(
            1,
            BRIGHTERMONDAY_MAX_PAGES + 1,
        ):

            url = (
                category_url
                if page == 1
                else f"{category_url}?page={page}"
            )

            try:

                response = session.get(
                    url,
                    timeout=REQUEST_TIMEOUT,
                )

                if response.status_code == 404:
                    break

                response.raise_for_status()

                page_jobs = (
                    parse_brightermonday_page(
                        response.text
                    )
                )

                if not page_jobs:
                    break

                new_on_page = 0

                for job in page_jobs:

                    if job["source_url"] in seen_urls:
                        continue

                    seen_urls.add(
                        job["source_url"]
                    )

                    jobs.append(job)

                    new_on_page += 1

                if new_on_page == 0:
                    break

            except requests.RequestException as exc:

                logger.warning(
                    "BrighterMonday request "
                    "failed for '%s': %s",
                    url,
                    exc,
                )

                break

            time.sleep(
                BRIGHTERMONDAY_REQUEST_DELAY
            )

    logger.info(
        "BrighterMonday returned %d "
        "unique jobs",
        len(jobs),
    )

    return jobs


# ============================================================
# OPENEDCAREER COLLECTOR
# ============================================================

OPENEDCAREER_DATE_RE = re.compile(
    r"\b(" + MONTHS_PATTERN + r")"
    r"\s+(\d{1,2}),\s+(\d{4})\b"
)

OPENEDCAREER_NAV_HREFS = (

    "/category/",

    "/tag/",

    "/page/",

    "/job-list/",

    "/employers/",

    "/candidates/",

    "/pricing/",

    "/about/",

    "/contact/",

    "/faq/",

    "/submit-job/",

    "/login-register/",

    "/user-dashboard/",

    "/alerts-jobs/",

    "/my-resume/",

    "/terms",

    "/privacy",

)


def parse_openedcareer_posted(
    text: str,
) -> str | None:

    match = OPENEDCAREER_DATE_RE.search(
        text
    )

    if not match:
        return None

    month_name, day_str, year_str = (
        match.groups()
    )

    month = MONTH_NUMBERS.get(
        month_name
    )

    if not month:
        return None

    try:

        return date(
            int(year_str),
            month,
            int(day_str),
        ).isoformat()

    except ValueError:

        return None


def parse_openedcareer_page(
    html: str,
) -> list[dict[str, Any]]:
    """Parse one OpenedCareer category page into raw job dicts.

    Post titles are wrapped in a heading (h3/h4) linking to the
    post's own permalink — the same pattern MyJobMag uses.
    OpenedCareer's "Recent Posts" sidebar widget also uses
    headings, so a few unrelated (non-ICT-category) posts can
    slip in; they score on their own merits rather than causing
    harm, so this is left as acceptable noise rather than solved
    with brittle, unverifiable class-name guessing.
    """

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    results: list[dict[str, Any]] = []

    seen_hrefs: set[str] = set()

    for heading in soup.find_all(
        ["h3", "h4"]
    ):

        link = heading.find(
            "a",
            href=True,
        )

        if not link:
            continue

        href = link["href"]

        if any(
            nav in href
            for nav in OPENEDCAREER_NAV_HREFS
        ):

            continue

        if href.startswith("/"):
            href = (
                "https://openedcareer.com"
                + href
            )

        href = href.rstrip("/") + "/"

        if href in seen_hrefs:
            continue

        seen_hrefs.add(href)

        heading_text = clean_text(
            link.get_text()
        ).strip()

        if not heading_text:
            continue

        if " at " in heading_text:

            title, _, company = (
                heading_text.rpartition(
                    " at "
                )
            )

        else:

            title, company = (
                heading_text,
                "Unknown",
            )

        container = (
            heading.find_parent("article")
            or heading.find_parent("div")
            or heading
        )

        container_text = " ".join(
            container.get_text(
                separator=" "
            ).split()
        )

        location = "Kenya"

        for candidate in (
            "Nairobi",
            "Mombasa",
            "Kisumu",
            "Kilifi",
            "Malindi",
            "Nakuru",
            "Eldoret",
            "Remote",
        ):

            if candidate in container_text:

                location = candidate

                break

        posted_date = (
            parse_openedcareer_posted(
                container_text
            )
        )

        description = normalize_text(
            container_text.replace(
                heading_text,
                " ",
            )
        )

        results.append({

            "source":
                "OpenedCareer",

            "source_url":
                href,

            "title":
                title.strip()
                or "Untitled",

            "company":
                company.strip()
                or "Unknown",

            "location":
                location,

            "description":
                description,

            "employment_type":
                "",

            "posted_date":
                posted_date,

        })

    return results


def fetch_openedcareer_jobs() -> list[
    dict[str, Any]
]:

    logger.info(
        "Fetching jobs from OpenedCareer..."
    )

    jobs: list[dict[str, Any]] = []

    seen_urls: set[str] = set()

    session = requests.Session()

    session.headers.update({

        "User-Agent":
            "Mozilla/5.0 (compatible; "
            "Gunga-Job-Radar/1.0)",

        "Accept":
            "text/html",

    })

    for category_url in (
        OPENEDCAREER_CATEGORY_URLS
    ):

        for page in range(
            1,
            OPENEDCAREER_MAX_PAGES + 1,
        ):

            url = (
                category_url
                if page == 1
                else (
                    category_url.rstrip("/")
                    + f"/page/{page}/"
                )
            )

            try:

                response = session.get(
                    url,
                    timeout=REQUEST_TIMEOUT,
                )

                if response.status_code == 404:
                    break

                response.raise_for_status()

                page_jobs = (
                    parse_openedcareer_page(
                        response.text
                    )
                )

                if not page_jobs:
                    break

                new_on_page = 0

                for job in page_jobs:

                    if job["source_url"] in seen_urls:
                        continue

                    seen_urls.add(
                        job["source_url"]
                    )

                    jobs.append(job)

                    new_on_page += 1

                if new_on_page == 0:
                    break

            except requests.RequestException as exc:

                logger.warning(
                    "OpenedCareer request "
                    "failed for '%s': %s",
                    url,
                    exc,
                )

                break

            time.sleep(
                OPENEDCAREER_REQUEST_DELAY
            )

    logger.info(
        "OpenedCareer returned %d "
        "unique jobs",
        len(jobs),
    )

    return jobs


# ============================================================
# MATCHING ENGINE
# ============================================================

def detect_employment_type(
    job: dict[str, Any],
    combined_text: str,
) -> str:

    explicit = clean_text(
        job.get("employment_type")
    ).strip()

    if explicit:
        return explicit

    for term in EMPLOYMENT_TYPE_TERMS:

        if term in combined_text:
            return term

    return ""


def estimate_freshness_score(
    posted_date: str | None,
) -> tuple[int, str]:
    """Score how recently a job was posted.

    posted_date is an ISO ``YYYY-MM-DD`` string when known.
    Missing dates get a small neutral score rather than being
    punished, since not every source reliably exposes one.
    """

    if not posted_date:

        return (
            2,
            "Posting date unknown",
        )

    try:

        posted = date.fromisoformat(
            posted_date
        )

    except ValueError:

        return (
            2,
            "Posting date unknown",
        )

    age_days = (
        date.today()
        - posted
    ).days

    if age_days < 0:
        age_days = 0

    if age_days <= FRESHNESS_FULL_DAYS:

        return (
            WEIGHT_FRESHNESS,
            f"Posted {age_days}d ago — fresh",
        )

    elif age_days <= FRESHNESS_PARTIAL_DAYS:

        return (
            3,
            f"Posted {age_days}d ago",
        )

    return (
        0,
        f"Posted {age_days}d ago — stale",
    )


def score_job(
    job: dict[str, Any],
) -> tuple[
    int,
    str,
    list[str],
    list[str],
    list[str],
    list[str],
    str,
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
    # LOCATION — 10%
    # ========================================================

    (
        location_classification,
        location_evidence,
    ) = classify_location(job)

    if location_classification in (
        "KENYA",
        "REMOTE-AFRICA",
        "REMOTE-WORLDWIDE",
    ):

        score += WEIGHT_LOCATION

        reasons.append(
            ELIGIBILITY_LABELS[
                location_classification
            ]
        )

    elif location_classification == "REMOTE-RESTRICTED":

        blockers.extend(
            location_evidence
        )

        reasons.append(
            "⚠️ Geographic restriction detected"
        )

    else:

        score += 2

        reasons.append(
            "❓ Location eligibility unclear"
        )

    # ========================================================
    # TITLE — 30%
    # ========================================================

    title_matches = [

        role

        for role in PROFILE[
            "target_titles"
        ]

        if role in title

    ]

    if title_matches:

        score += WEIGHT_TITLE

        reasons.append(
            "Title strongly matches a "
            "target ICT role"
        )

    # ========================================================
    # SKILLS — 25%
    # ========================================================

    for skill in PROFILE[
        "skills"
    ]:

        skill_pattern = (
            r"\b"
            + re.escape(skill)
            + r"\b"
        )

        if re.search(
            skill_pattern,
            combined,
        ):

            matched_skills.append(
                skill
            )

    skill_points = min(
        len(matched_skills) * 5,
        WEIGHT_SKILLS,
    )

    score += skill_points

    if matched_skills:

        reasons.append(
            f"{len(matched_skills)} relevant "
            "skill(s): "
            + ", ".join(
                matched_skills[:6]
            )
        )

    # ========================================================
    # EDUCATION — 15%
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

        score += WEIGHT_EDUCATION

        reasons.append(
            "Entry-level/diploma-friendly "
            "language detected"
        )

    # ========================================================
    # EXPERIENCE — 10%
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

        score += WEIGHT_EXPERIENCE

        reasons.append(
            "Experience requirements "
            "appear suitable"
        )

    # ========================================================
    # EMPLOYMENT TYPE — 5%
    # ========================================================

    employment_type = detect_employment_type(
        job,
        combined,
    )

    if employment_type:

        score += WEIGHT_EMPLOYMENT_TYPE

        reasons.append(
            f"Employment type: {employment_type}"
        )

    # ========================================================
    # FRESHNESS — 5%
    # ========================================================

    freshness_points, freshness_reason = (
        estimate_freshness_score(
            job.get("posted_date")
        )
    )

    score += freshness_points

    reasons.append(
        freshness_reason
    )

    # ========================================================
    # PREFERRED LOCATIONS (informational only)
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

    # A restricted job is never presented as a strong Kenya
    # opportunity, regardless of how well everything else
    # scores — the numeric score is still reported for
    # transparency, but the tier (and therefore Telegram /
    # digest grouping) is capped.
    if location_classification == "REMOTE-RESTRICTED":

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
        location_classification,
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
    eligibility: str,
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

        "eligibility":
            eligibility,

        "employment_type":
            job.get("employment_type")
            or None,

        "posted_date":
            job.get("posted_date"),

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
    eligibility: str = "UNKNOWN",
) -> bool:

    require_environment(
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
    )

    eligibility_label = ELIGIBILITY_LABELS.get(
        eligibility,
        "❓ LOCATION UNCLEAR",
    )

    # Telegram's HTML parse mode needs these escaped, since
    # titles/companies/locations come from scraped job text.
    safe_title = html.escape(
        str(job.get("title", ""))
    )

    safe_company = html.escape(
        str(job.get("company", ""))
    )

    safe_location = html.escape(
        str(job.get("location", ""))
    )

    safe_url = html.escape(
        str(job.get("source_url", "")),
        quote=True,
    )

    reasons_block = (
        "\n".join(
            f"• {html.escape(reason)}"
            for reason in reasons
            if not reason.startswith("Eligibility:")
            and reason != eligibility_label
        )
        if reasons
        else "• Good overall fit"
    )

    message = (
        f"{eligibility_label}\n"

        f"🎯 MATCH: {score}%\n\n"

        f"💼 {safe_title}\n"

        f"🏢 {safe_company}\n"

        f"📍 {safe_location}\n\n"

        "Why it matches:\n"

        f"{reasons_block}\n\n"

        f'🔗 <a href="{safe_url}">Apply</a>'
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

            "parse_mode":
                "HTML",

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

    himalayas_jobs = fetch_himalayas_jobs()

    myjobmag_jobs = fetch_myjobmag_jobs()

    brightermonday_jobs = fetch_brightermonday_jobs()

    openedcareer_jobs = fetch_openedcareer_jobs()

    jobs = (
        himalayas_jobs
        + myjobmag_jobs
        + brightermonday_jobs
        + openedcareer_jobs
    )

    logger.info(
        "Processing %d jobs "
        "(%d Himalayas, %d MyJobMag, "
        "%d BrighterMonday, "
        "%d OpenedCareer)...",
        len(jobs),
        len(himalayas_jobs),
        len(myjobmag_jobs),
        len(brightermonday_jobs),
        len(openedcareer_jobs),
    )

    jobs_fetched = len(jobs)
    jobs_processed = 0
    jobs_new = 0
    strong_matches = 0
    consider_matches = 0
    telegram_attempts = 0
    telegram_sent = 0
    telegram_failures = 0

    for job in jobs:

        source_url = job.get(
            "source_url"
        )

        if not source_url:
            continue

        try:

            # ================================================
            # Score the job (both new and existing)
            # ================================================

            (
                score,
                tier,
                reasons,
                blockers,
                matched_skills,
                matched_locations,
                eligibility,
            ) = score_job(
                job
            )

            # ================================================
            # Attempt to insert/update in database
            # ================================================

            job_id = save_job(

                database,

                job,

                score,

                tier,

                reasons,

                blockers,

                matched_skills,

                matched_locations,

                eligibility,

            )

            jobs_processed += 1

            # If insert_job returned None, it was a duplicate.
            # It may still be an un-alerted strong match from a
            # scan where the Telegram send failed, so look it
            # up and retry rather than skipping outright.
            if job_id is None:

                logger.info(
                    "JOB DUPLICATE | %s | %s%%",
                    job["title"],
                    score,
                )

                existing = database.get_job_by_url(
                    source_url
                )

                if (
                    existing
                    and existing["tier"] == "strong"
                    and not existing["telegram_sent"]
                ):

                    telegram_attempts += 1

                    try:

                        send_telegram_alert(
                            job,
                            existing["score"],
                            reasons,
                            eligibility,
                        )

                        database.mark_telegram_sent(
                            existing["id"]
                        )

                        telegram_sent += 1

                        logger.info(
                            "Telegram alert "
                            "(retry) sent for "
                            "job %s",
                            existing["id"],
                        )

                    except Exception as exc:

                        telegram_failures += 1

                        logger.error(
                            "Telegram retry failed "
                            "for job %s: %s",
                            existing["id"],
                            exc,
                        )

                continue

            # New job was inserted
            jobs_new += 1

            logger.info(

                "NEW JOB | %s | %s%% | %s",

                job["title"],

                score,

                tier,

            )

            # ================================================
            # Handle strong matches
            # ================================================

            if tier == "strong":

                strong_matches += 1

                telegram_attempts += 1

                try:

                    send_telegram_alert(

                        job,

                        score,

                        reasons,

                        eligibility,

                    )

                    database.mark_telegram_sent(
                        job_id
                    )

                    telegram_sent += 1

                    logger.info(

                        "Telegram alert sent "
                        "for job %s",

                        job_id,

                    )

                except Exception as exc:

                    telegram_failures += 1

                    logger.error(

                        "Telegram alert failed "
                        "for job %s: %s",

                        job_id,

                        exc,

                    )

            elif tier == "consider":

                consider_matches += 1

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

    logger.info("")
    logger.info(
        "========== SCAN METRICS =========="
    )
    logger.info(
        "Jobs fetched: %d",
        jobs_fetched,
    )
    logger.info(
        "Jobs processed: %d",
        jobs_processed,
    )
    logger.info(
        "New jobs saved: %d",
        jobs_new,
    )
    logger.info(
        "Strong matches: %d",
        strong_matches,
    )
    logger.info(
        "Consider matches: %d",
        consider_matches,
    )
    logger.info(
        "Telegram attempts: %d",
        telegram_attempts,
    )
    logger.info(
        "Telegram sent: %d",
        telegram_sent,
    )
    logger.info(
        "Telegram failures: %d",
        telegram_failures,
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