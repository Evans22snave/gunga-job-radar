"""
Gunga Job Radar
Phase 4 — Kenya-aware job matching

Pipeline:

    Himalayas API   MyJobMag   BrighterMonday   OpenedCareer   Fuzu
    Career Point Kenya   Corporate Staffing   RemoteOK
    We Work Remotely   ReliefWeb   PSC
          ↓             ↓             ↓               ↓         ↓
          └─────────────┴─────────────┴───────────────┴─────────┘
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
import json
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

FUZU_CATEGORY_URLS = [

    "https://www.fuzu.com/kenya/job/computers-software-development",

    "https://www.fuzu.com/kenya/job/computers-software-development/basic",

]

FUZU_MAX_PAGES = 3

FUZU_REQUEST_DELAY = 1.0

CAREERPOINTKENYA_CATEGORY_URLS = [

    "https://www.careerpointkenya.co.ke/category/it-jobs-in-kenya/",

    "https://www.careerpointkenya.co.ke/category/internships-in-kenya/",

]

CAREERPOINTKENYA_MAX_PAGES = 3

CAREERPOINTKENYA_REQUEST_DELAY = 1.0

CORPORATESTAFFING_CATEGORY_URLS = [

    "https://www.corporatestaffing.co.ke/category/it-jobs-in-kenya/",

    "https://www.corporatestaffing.co.ke/category/internships-in-kenya/",

]

CORPORATESTAFFING_MAX_PAGES = 3

CORPORATESTAFFING_REQUEST_DELAY = 1.0

REMOTEOK_API = (
    "https://remoteok.com/api"
)

REMOTEOK_REQUEST_DELAY = 0.5

# All-in-one "Programming" feed covers full/back/front-end, plus
# Devops and Sysadmin separately — this is the closest fit to
# Evans's ICT/data-entry target on a board that skews senior and
# has no "entry level" category of its own. score_job's normal
# title/skill matching does the relevance filtering downstream,
# same as it does for every other source.
WEWORKREMOTELY_RSS_URLS = [

    "https://weworkremotely.com/categories/remote-programming-jobs.rss",

    "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",

]

WEWORKREMOTELY_REQUEST_DELAY = 1.0

# ReliefWeb's API has required a *pre-approved* appname since
# 1 Nov 2025 (previously any string worked). If this source comes
# back empty in the logs, the appname below likely needs approval
# from ReliefWeb first — see https://apidoc.reliefweb.int/
RELIEFWEB_APPNAME = "gunga-job-radar"

RELIEFWEB_API = (
    "https://api.reliefweb.int/v2/jobs"
)

RELIEFWEB_QUERY = (
    "information technology OR ICT OR data OR "
    "software OR computer"
)

RELIEFWEB_REQUEST_DELAY = 0.5

PSC_URL = (
    "https://www.psckjobs.go.ke/ActiveJobsAdverts.aspx"
)

PSC_REQUEST_DELAY = 1.0

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
# DEADLINE EXTRACTION
# ============================================================
# Shared across all collectors. Deadlines are stated
# inconsistently (or not at all) across sources — this returns
# None when nothing is found, which is expected and fine; the
# dashboard just doesn't show a deadline badge for those jobs.

MONTHS_PATTERN = (
    "January|February|March|April|May|June|"
    "July|August|September|October|November|December"
)

MONTH_NUMBERS = {

    name: index

    for index, name in enumerate(
        MONTHS_PATTERN.split("|"),
        start=1,
    )

}

DEADLINE_KEYWORD_RE = re.compile(
    r"(?:application\s+)?deadline"
    r"(?:\s+date)?\s*[:\-]?\s*"
    r"|closing\s+date\s*[:\-]?\s*"
    r"|apply\s+(?:before|by)\s*[:\-]?\s*",
    re.IGNORECASE,
)

# "30th July 2026" / "30 July 2026" / "23rd February, 2026"
# (the trailing ",?" handles sources like OpenedCareer that put
# a comma between the month and the year)
DEADLINE_DMY_RE = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s+"
    r"(" + MONTHS_PATTERN + r")"
    r",?\s+(\d{4})\b",
    re.IGNORECASE,
)

# "September 25, 2026" / "September 25 2026"
DEADLINE_MDY_RE = re.compile(
    r"\b(" + MONTHS_PATTERN + r")"
    r"\s+(\d{1,2})(?:st|nd|rd|th)?,?"
    r"\s+(\d{4})\b",
    re.IGNORECASE,
)

# "31/08/2026" or "31-08-2026" (day/month/year, the common
# convention in Kenyan listings)
DEADLINE_NUMERIC_RE = re.compile(
    r"\b(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})\b"
)


def extract_deadline_date(
    text: str,
) -> str | None:

    if not text:
        return None

    keyword_match = DEADLINE_KEYWORD_RE.search(
        text
    )

    if not keyword_match:
        return None

    # Look only in a short window right after the keyword —
    # avoids accidentally grabbing an unrelated date elsewhere
    # in the description.
    window = text[
        keyword_match.end():
        keyword_match.end() + 40
    ]

    dmy = DEADLINE_DMY_RE.search(window)

    if dmy:

        day_str, month_name, year_str = (
            dmy.groups()
        )

        month = MONTH_NUMBERS.get(
            month_name.capitalize()
        )

        if month:

            try:

                return date(
                    int(year_str),
                    month,
                    int(day_str),
                ).isoformat()

            except ValueError:

                pass

    mdy = DEADLINE_MDY_RE.search(window)

    if mdy:

        month_name, day_str, year_str = (
            mdy.groups()
        )

        month = MONTH_NUMBERS.get(
            month_name.capitalize()
        )

        if month:

            try:

                return date(
                    int(year_str),
                    month,
                    int(day_str),
                ).isoformat()

            except ValueError:

                pass

    numeric = DEADLINE_NUMERIC_RE.search(
        window
    )

    if numeric:

        day_str, month_str, year_str = (
            numeric.groups()
        )

        try:

            return date(
                int(year_str),
                int(month_str),
                int(day_str),
            ).isoformat()

        except ValueError:

            pass

    return None


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

                    "deadline_date":
                        extract_deadline_date(
                            full_description
                        ),

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

DATE_RE = re.compile(
    r"\b\d{1,2}\s+(?:" + MONTHS_PATTERN + r")\b"
)


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

            "deadline_date":
                extract_deadline_date(
                    container_text
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


def find_brightermonday_card(link: Any) -> Any:
    """Find the ancestor element that holds the *whole* job card.

    The old approach grabbed the nearest <li>/<article>/<div>
    ancestor of the title link, but on BrighterMonday's current
    markup that nearest ancestor is often just a thin wrapper
    around the title itself — it doesn't reach the sibling text
    that carries the "posted X ago" label, which lives further
    up the tree alongside the company/location/tags block. That
    caused posted_date (and any deadline text) to silently come
    back empty for most listings.

    Instead, climb from the link upward one parent at a time and
    stop at the first ancestor whose text already contains a
    relative-posted-date phrase ("3 days ago", "Today", etc.) or
    the "Easy apply" footer every card ends with — whichever
    comes first proves we've reached the full card, not just a
    fragment of it. Cap the climb so a miss can't accidentally
    swallow the whole results list.
    """

    node = link
    fallback = None

    for _ in range(8):

        parent = node.find_parent(["li", "article", "div"])

        if parent is None:
            break

        if fallback is None:
            fallback = parent

        text = parent.get_text(separator=" ")

        if POSTED_RELATIVE_RE.search(text) or "Easy apply" in text:
            return parent

        node = parent

    return fallback or link


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

        container = find_brightermonday_card(link)

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

            "deadline_date":
                extract_deadline_date(
                    container_text
                ),

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


def _openedcareer_is_real_listing(
    heading: Any,
    max_nodes: int = 60,
) -> bool:
    """True if a "Read More" link follows this heading before
    the next one — the marker that separates a real category
    listing from a "Recent Posts" sidebar entry (see
    parse_openedcareer_page's docstring).
    """

    for node in heading.find_all_next(
        string=True,
        limit=max_nodes,
    ):

        enclosing = node.find_parent(
            ["h3", "h4"]
        )

        if (
            enclosing is not None
            and enclosing is not heading
        ):

            # Reached the next post's heading without
            # finding a "Read More" link for this one.
            return False

        if "read more" in node.strip().lower():
            return True

    return False


def parse_openedcareer_page(
    html: str,
) -> list[dict[str, Any]]:
    """Parse one OpenedCareer category page into raw job dicts.

    Post titles are wrapped in a heading (h3/h4) linking to the
    post's own permalink — the same pattern MyJobMag uses.

    OpenedCareer's site-wide "Recent Posts" sidebar widget also
    uses headings, and it shows whatever the site published most
    recently *overall* — not scoped to this category — so it was
    slipping in stale, unrelated posts (e.g. a hotel front-desk
    role) as if they were real ICT listings. Real listing entries
    always carry a "Read More" link after their excerpt; sidebar
    widget entries never do, so that's used here to tell them
    apart instead of guessing at class names.
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

        if not _openedcareer_is_real_listing(
            heading
        ):
            continue

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

            "deadline_date":
                extract_deadline_date(
                    container_text
                ),

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
# FUZU COLLECTOR
# ============================================================

FUZU_NOISE_PREFIXES = (

    "leading company in",

    "get personalised",

    "only on fuzu",

    "closed for applications",

    "sign in and apply",

)


def parse_fuzu_page(
    html: str,
) -> list[dict[str, Any]]:
    """Parse one Fuzu category page into raw job dicts.

    Fuzu renders each listing's job title as a heading (h2/h3)
    linking to "/<country>/jobs/<slug>" — the plural "jobs" is
    the actual posting permalink. Category, industry, seniority
    and location filter links all use the singular "/job/" path
    instead, so checking for "/jobs/" in the href keeps this
    scoped to real listings and skips all the filter-sidebar
    noise. Unlike MyJobMag/OpenedCareer, the title text itself
    has no "<Title> at <Company>" pattern — the employer name
    sits in a short text node just above the heading, and the
    location sits in one or two short link tags just below it —
    so both are picked up by walking outward from the heading
    rather than by parsing the heading text.
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

        if "/jobs/" not in href:
            continue

        if href.startswith("/"):
            href = (
                "https://www.fuzu.com"
                + href
            )

        href = href.split("?")[0]

        if href in seen_hrefs:
            continue

        seen_hrefs.add(href)

        title = clean_text(
            link.get_text()
        ).strip()

        if not title:
            continue

        # Employer name: nearest text-bearing element before
        # this heading, stopping the walk at the previous job's
        # heading so we never wander into an earlier card.
        company = "Unknown"

        for prev in heading.find_all_previous(
            limit=25
        ):

            if prev.name in (
                "h2",
                "h3",
            ):
                break

            # Only leaf-like text elements are candidates —
            # wrapper "div"s tend to concatenate multiple
            # sibling texts (e.g. a location-tag container),
            # which would otherwise read as the company name.
            if prev.name not in (
                "p",
                "span",
                "strong",
                "b",
                "h4",
                "h5",
                "a",
            ):
                continue

            # An <a> here is only useful if it's a company
            # profile link — location and title links (which
            # both use "/job") would otherwise read as company
            # text (e.g. a stray "Kenya" location tag).
            if (
                prev.name == "a"
                and "/job" in prev.get(
                    "href",
                    "",
                )
            ):
                continue

            text = clean_text(
                prev.get_text()
            ).strip()

            if (
                not text
                or len(text) > 80
                or "•" in text
            ):
                continue

            if text.lower().startswith(
                FUZU_NOISE_PREFIXES
            ):
                continue

            company = text

            break

        # Location: one or two short location links (e.g.
        # "Nairobi" then "• Kenya") immediately follow the
        # title link, using the same singular "/job/" path as
        # the filter sidebar. Stop early if we run into the
        # next job's title link.
        location = "Kenya"

        for loc_link in heading.find_all_next(
            "a",
            href=True,
            limit=8,
        ):

            loc_href = loc_link["href"]

            # find_all_next() walks the flat parse tree, so
            # the first hit is the title link's own anchor
            # (still "inside" the heading) — skip it rather
            # than treating it as the next job's title.
            if loc_link is link:
                continue

            if "/jobs/" in loc_href:
                break

            if "/job/" not in loc_href:
                continue

            loc_text = clean_text(
                loc_link.get_text()
            ).strip(" •")

            if (
                loc_text
                and loc_text.lower()
                != "kenya"
            ):

                location = loc_text

                break

        container = (
            heading.find_parent("div")
            or heading
        )

        container_text = " ".join(
            container.get_text(
                separator=" "
            ).split()
        )

        description = normalize_text(
            container_text.replace(
                title,
                " ",
            )
        )

        results.append({

            "source":
                "Fuzu",

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
                None,

            "deadline_date":
                extract_deadline_date(
                    container_text
                ),

        })

    return results


def fetch_fuzu_jobs() -> list[
    dict[str, Any]
]:

    logger.info(
        "Fetching jobs from Fuzu..."
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
        FUZU_CATEGORY_URLS
    ):

        for page in range(
            1,
            FUZU_MAX_PAGES + 1,
        ):

            url = (
                category_url
                if page == 1
                else (
                    f"{category_url}"
                    f"?page={page}"
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

                page_jobs = parse_fuzu_page(
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
                # seen (the basic-level category overlaps
                # the main category) — stop paging.
                if new_on_page == 0:
                    break

            except requests.RequestException as exc:

                logger.warning(
                    "Fuzu request failed "
                    "for '%s': %s",
                    url,
                    exc,
                )

                break

            time.sleep(
                FUZU_REQUEST_DELAY
            )

    logger.info(
        "Fuzu returned %d unique jobs",
        len(jobs),
    )

    return jobs


# ============================================================
# SHARED WORDPRESS-STYLE HELPER
# ============================================================
# Career Point Kenya and Corporate Staffing both run the same
# family of WordPress job-board theme: a heading (h2) links to
# the post permalink, and the category tags / date / excerpt
# that belong to that same listing sit as plain text between
# this heading and the next one. Walking forward and stopping at
# the next heading (the same trick OpenedCareer's "Read More"
# check uses) collects exactly that listing's text regardless of
# the exact wrapper element each theme uses.

def _collect_text_after_heading(
    heading: Any,
    limit: int = 60,
) -> str:

    parts: list[str] = []

    for node in heading.find_all_next(
        string=True,
        limit=limit,
    ):

        enclosing = node.find_parent(
            ["h2", "h3"]
        )

        if (
            enclosing is not None
            and enclosing is not heading
        ):

            break

        text = clean_text(node).strip()

        if text:

            parts.append(text)

    return " ".join(parts)


# ============================================================
# CAREER POINT KENYA COLLECTOR
# ============================================================

CAREERPOINTKENYA_POST_RE = re.compile(
    r"/(\d{4})/(\d{2})/(\d{2})/[^/]+/?$"
)


def parse_careerpointkenya_page(
    html_text: str,
) -> list[dict[str, Any]]:
    """Parse one Career Point Kenya category page into raw job
    dicts.

    The theme dates every post permalink as /YYYY/MM/DD/slug/,
    which doubles as a reliable posted_date source without
    needing to parse any on-page date text. Titles follow this
    theme family's "<Title> Job <Company>" convention (no "at"
    separator, unlike MyJobMag/OpenedCareer). Some cards wrap the
    title text directly in the permalink anchor; others use an
    icon-only "view" anchor with no visible text and put the
    title in a plain text node just before it — both are handled
    here since the live markup wasn't available to confirm which
    one this theme actually uses.
    """

    soup = BeautifulSoup(
        html_text,
        "html.parser",
    )

    results: list[dict[str, Any]] = []

    seen_hrefs: set[str] = set()

    for link in soup.find_all(
        "a",
        href=True,
    ):

        href = link["href"]

        date_match = CAREERPOINTKENYA_POST_RE.search(
            href
        )

        if not date_match:
            continue

        if href.startswith("/"):

            href = (
                "https://www.careerpointkenya.co.ke"
                + href
            )

        href = href.split("?")[0]

        if href in seen_hrefs:
            continue

        seen_hrefs.add(href)

        link_text = clean_text(
            link.get_text()
        ).strip()

        if len(link_text) > 8:

            heading_text = link_text

        else:

            # Icon-only anchor — walk backward for the nearest
            # substantial text node (same trick used for Fuzu's
            # employer-name extraction).
            heading_text = ""

            for prev in link.find_all_previous(
                limit=15
            ):

                if prev.name not in (
                    "h1",
                    "h2",
                    "h3",
                    "h4",
                    "p",
                    "span",
                    "div",
                ):

                    continue

                # find_all_previous() includes ancestors of
                # `link` itself (an ancestor's opening tag comes
                # "before" its own child in document order) —
                # skip those, since their text just echoes the
                # anchor's own (empty/icon-only) text back.
                if link in prev.descendants:
                    continue

                text = clean_text(
                    prev.get_text()
                ).strip()

                if (
                    not text
                    or len(text) > 140
                ):

                    continue

                heading_text = text

                break

        if not heading_text:
            continue

        if " Job " in heading_text:

            title, _, company = (
                heading_text.partition(
                    " Job "
                )
            )

        else:

            title, company = (
                heading_text,
                "Unknown",
            )

        year_str, month_str, day_str = (
            date_match.groups()
        )

        try:

            posted_date = date(
                int(year_str),
                int(month_str),
                int(day_str),
            ).isoformat()

        except ValueError:

            posted_date = None

        results.append({

            "source":
                "Career Point Kenya",

            "source_url":
                href,

            "title":
                title.strip()
                or "Untitled",

            "company":
                company.strip()
                or "Unknown",

            "location":
                "Kenya",

            "description":
                normalize_text(
                    heading_text
                ),

            "employment_type":
                "",

            "posted_date":
                posted_date,

            "deadline_date":
                extract_deadline_date(
                    heading_text
                ),

        })

    return results


def fetch_careerpointkenya_jobs() -> list[
    dict[str, Any]
]:

    logger.info(
        "Fetching jobs from Career Point Kenya..."
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
        CAREERPOINTKENYA_CATEGORY_URLS
    ):

        for page in range(
            1,
            CAREERPOINTKENYA_MAX_PAGES + 1,
        ):

            url = (
                category_url
                if page == 1
                else (
                    f"{category_url}"
                    f"page/{page}/"
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
                    parse_careerpointkenya_page(
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
                    "Career Point Kenya request "
                    "failed for '%s': %s",
                    url,
                    exc,
                )

                break

            time.sleep(
                CAREERPOINTKENYA_REQUEST_DELAY
            )

    logger.info(
        "Career Point Kenya returned %d "
        "unique jobs",
        len(jobs),
    )

    return jobs


# ============================================================
# CORPORATE STAFFING COLLECTOR
# ============================================================

CORPORATESTAFFING_DATE_RE = re.compile(
    # No trailing \b: the page concatenates its "published" and
    # "modified" dates back to back with no space or punctuation
    # ("September 9, 2026September 9, 2026"), so a digit is
    # immediately followed by a letter with no word boundary
    # between them. The exact {4} digit count already pins the
    # match without needing one.
    r"\b(" + MONTHS_PATTERN + r")"
    r"\s+(\d{1,2}),\s+(\d{4})"
)


def parse_corporatestaffing_page(
    html_text: str,
) -> list[dict[str, Any]]:
    """Parse one Corporate Staffing category page into raw job
    dicts.

    Same theme family as Career Point Kenya: an h2 heading links
    to /job/<slug>/, followed directly by a "Month D, YYYY" date
    line and an excerpt paragraph before the next heading. Titles
    follow the same "<Title> Job <Company>" convention.
    """

    soup = BeautifulSoup(
        html_text,
        "html.parser",
    )

    results: list[dict[str, Any]] = []

    seen_hrefs: set[str] = set()

    for heading in soup.find_all(
        "h2"
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

        href = href.split("?")[0]

        if href in seen_hrefs:
            continue

        seen_hrefs.add(href)

        heading_text = clean_text(
            link.get_text()
        ).strip()

        if not heading_text:
            continue

        if " Job " in heading_text:

            title, _, company = (
                heading_text.partition(
                    " Job "
                )
            )

        else:

            title, company = (
                heading_text,
                "Unknown",
            )

        following_text = (
            _collect_text_after_heading(
                heading
            )
        )

        posted_date = None

        date_match = CORPORATESTAFFING_DATE_RE.search(
            following_text
        )

        if date_match:

            month_name, day_str, year_str = (
                date_match.groups()
            )

            month = MONTH_NUMBERS.get(
                month_name
            )

            if month:

                try:

                    posted_date = date(
                        int(year_str),
                        month,
                        int(day_str),
                    ).isoformat()

                except ValueError:

                    posted_date = None

        description = normalize_text(
            following_text
        )

        results.append({

            "source":
                "Corporate Staffing",

            "source_url":
                href,

            "title":
                title.strip()
                or "Untitled",

            "company":
                company.strip()
                or "Unknown",

            "location":
                "Kenya",

            "description":
                description,

            "employment_type":
                "",

            "posted_date":
                posted_date,

            "deadline_date":
                extract_deadline_date(
                    following_text
                ),

        })

    return results


def fetch_corporatestaffing_jobs() -> list[
    dict[str, Any]
]:

    logger.info(
        "Fetching jobs from Corporate Staffing..."
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
        CORPORATESTAFFING_CATEGORY_URLS
    ):

        for page in range(
            1,
            CORPORATESTAFFING_MAX_PAGES + 1,
        ):

            url = (
                category_url
                if page == 1
                else (
                    f"{category_url}"
                    f"page/{page}/"
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
                    parse_corporatestaffing_page(
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
                    "Corporate Staffing request "
                    "failed for '%s': %s",
                    url,
                    exc,
                )

                break

            time.sleep(
                CORPORATESTAFFING_REQUEST_DELAY
            )

    logger.info(
        "Corporate Staffing returned %d "
        "unique jobs",
        len(jobs),
    )

    return jobs


# ============================================================
# REMOTEOK COLLECTOR
# ============================================================

def fetch_remoteok_jobs() -> list[
    dict[str, Any]
]:
    """Fetch from RemoteOK's public JSON API (remoteok.com/api).

    No HTML parsing needed — it's a flat JSON array. The first
    element is always RemoteOK's API-terms/legal notice, not a
    job (it has no "id" field), so it's skipped. This is a
    general remote-jobs firehose, not ICT-specific, so like the
    generic "internships" categories pulled from other sources,
    relevance is left entirely to score_job downstream rather
    than pre-filtered here.
    """

    logger.info(
        "Fetching jobs from RemoteOK..."
    )

    jobs: list[dict[str, Any]] = []

    session = requests.Session()

    session.headers.update({

        "User-Agent":
            "Mozilla/5.0 (compatible; "
            "Gunga-Job-Radar/1.0)",

        "Accept":
            "application/json",

    })

    try:

        response = session.get(
            REMOTEOK_API,
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()

        raw_jobs = response.json()

    except (
        requests.RequestException,
        ValueError,
    ) as exc:

        logger.warning(
            "RemoteOK request failed: %s",
            exc,
        )

        return jobs

    for entry in raw_jobs:

        if not isinstance(entry, dict):
            continue

        if "id" not in entry:
            # The legal-notice entry has no id.
            continue

        apply_url = entry.get(
            "apply_url"
        ) or entry.get("url")

        if not apply_url:
            continue

        title = clean_text(
            entry.get("position")
        ).strip()

        if not title:
            continue

        description_html = entry.get(
            "description",
            "",
        )

        description_text = normalize_text(
            BeautifulSoup(
                description_html,
                "html.parser",
            ).get_text(
                separator=" "
            )
        )

        location = clean_text(
            entry.get("location")
        ).strip() or "Worldwide Remote"

        tags = entry.get("tags") or []

        tag_text = clean_text(tags)

        posted_date = None

        date_str = entry.get("date")

        if date_str:

            try:

                posted_date = (
                    datetime.fromisoformat(
                        date_str.replace(
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
                "RemoteOK",

            "source_url":
                apply_url,

            "title":
                title,

            "company":
                clean_text(
                    entry.get("company")
                ).strip()
                or "Unknown",

            "location":
                location,

            "description":
                (
                    description_text
                    + " "
                    + normalize_text(tag_text)
                ),

            "employment_type":
                "",

            "posted_date":
                posted_date,

            "deadline_date":
                None,

        })

    time.sleep(
        REMOTEOK_REQUEST_DELAY
    )

    logger.info(
        "RemoteOK returned %d jobs",
        len(jobs),
    )

    return jobs


# ============================================================
# WE WORK REMOTELY COLLECTOR
# ============================================================

def fetch_weworkremotely_jobs() -> list[
    dict[str, Any]
]:
    """Fetch from We Work Remotely's official public RSS feeds.

    Parsed with BeautifulSoup's html.parser rather than a strict
    XML parser — RSS is simple enough that this reads item/title/
    description/link/pubDate tags fine without adding an lxml
    dependency, matching how the rest of this file avoids extra
    packages.
    """

    logger.info(
        "Fetching jobs from We Work Remotely..."
    )

    jobs: list[dict[str, Any]] = []

    seen_urls: set[str] = set()

    session = requests.Session()

    session.headers.update({

        "User-Agent":
            "Mozilla/5.0 (compatible; "
            "Gunga-Job-Radar/1.0)",

        "Accept":
            "application/rss+xml, text/xml",

    })

    for feed_url in (
        WEWORKREMOTELY_RSS_URLS
    ):

        try:

            response = session.get(
                feed_url,
                timeout=REQUEST_TIMEOUT,
            )

            response.raise_for_status()

            soup = BeautifulSoup(
                response.text,
                "html.parser",
            )

        except requests.RequestException as exc:

            logger.warning(
                "We Work Remotely request "
                "failed for '%s': %s",
                feed_url,
                exc,
            )

            continue

        for item in soup.find_all("item"):

            # NOTE: <link> is a void/self-closing element in
            # HTML5, so html.parser silently empties it and its
            # text is unrecoverable via get_text(). <guid> is a
            # plain container tag and, per WWR's own feed, always
            # duplicates the exact same job permalink — so it's
            # used here as the reliable stand-in.
            guid_tag = item.find("guid")

            if not guid_tag:
                continue

            source_url = clean_text(
                guid_tag.get_text()
            ).strip()

            if not source_url:
                continue

            source_url = source_url.split(
                "?"
            )[0]

            if source_url in seen_urls:
                continue

            seen_urls.add(source_url)

            title_tag = item.find("title")

            raw_title = clean_text(
                title_tag.get_text()
                if title_tag
                else ""
            ).strip()

            # Titles are formatted "<Company>: <Title>"
            if ": " in raw_title:

                company, _, title = (
                    raw_title.partition(
                        ": "
                    )
                )

            else:

                company, title = (
                    "Unknown",
                    raw_title,
                )

            if not title:
                continue

            region_tag = item.find("region")

            location = clean_text(
                region_tag.get_text()
                if region_tag
                else ""
            ).strip() or "Worldwide Remote"

            description_tag = item.find(
                "description"
            )

            description_html = (
                description_tag.get_text()
                if description_tag
                else ""
            )

            description_text = normalize_text(
                BeautifulSoup(
                    description_html,
                    "html.parser",
                ).get_text(
                    separator=" "
                )
            )

            pubdate_tag = item.find("pubdate")

            posted_date = None

            if pubdate_tag:

                pub_text = clean_text(
                    pubdate_tag.get_text()
                ).strip()

                try:

                    posted_date = (
                        datetime.strptime(
                            pub_text[:25],
                            "%a, %d %b %Y %H:%M:%S",
                        )
                        .date()
                        .isoformat()
                    )

                except ValueError:

                    posted_date = None

            jobs.append({

                "source":
                    "We Work Remotely",

                "source_url":
                    source_url,

                "title":
                    title.strip(),

                "company":
                    company.strip()
                    or "Unknown",

                "location":
                    location,

                "description":
                    description_text,

                "employment_type":
                    "",

                "posted_date":
                    posted_date,

                "deadline_date":
                    None,

            })

        time.sleep(
            WEWORKREMOTELY_REQUEST_DELAY
        )

    logger.info(
        "We Work Remotely returned %d "
        "unique jobs",
        len(jobs),
    )

    return jobs


# ============================================================
# RELIEFWEB COLLECTOR
# ============================================================

def fetch_reliefweb_jobs() -> list[
    dict[str, Any]
]:
    """Fetch ICT-relevant postings from ReliefWeb's public jobs
    API (humanitarian/NGO/ICT4D sector).

    NOTE: ReliefWeb has required a *pre-approved* appname since
    1 Nov 2025. If this consistently returns 0 jobs in the scan
    logs, RELIEFWEB_APPNAME likely needs to be registered and
    approved at https://apidoc.reliefweb.int/ first — that's a
    one-time manual step outside this script, not a code bug.
    """

    logger.info(
        "Fetching jobs from ReliefWeb..."
    )

    jobs: list[dict[str, Any]] = []

    session = requests.Session()

    session.headers.update({

        "User-Agent":
            "Mozilla/5.0 (compatible; "
            "Gunga-Job-Radar/1.0)",

        "Accept":
            "application/json",

    })

    params = {

        "appname":
            RELIEFWEB_APPNAME,

        "query[value]":
            RELIEFWEB_QUERY,

        "query[operator]":
            "OR",

        "limit":
            50,

        "sort[]":
            "date:desc",

        "fields[include][]": [

            "title",

            "url_alias",

            "date.created",

            "body",

            "source.name",

            "country.name",

        ],

    }

    try:

        response = session.get(
            RELIEFWEB_API,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()

        payload = response.json()

    except (
        requests.RequestException,
        ValueError,
    ) as exc:

        logger.warning(
            "ReliefWeb request failed: %s",
            exc,
        )

        return jobs

    for entry in payload.get("data", []):

        fields = entry.get("fields", {})

        title = clean_text(
            fields.get("title")
        ).strip()

        source_url = fields.get(
            "url_alias"
        )

        if not title or not source_url:
            continue

        source_names = [
            source.get("name", "")
            for source in (
                fields.get("source")
                or []
            )
        ]

        company = (
            clean_text(source_names).strip()
            or "Unknown"
        )

        country_names = [
            country.get("name", "")
            for country in (
                fields.get("country")
                or []
            )
        ]

        location = (
            clean_text(country_names).strip()
            or "Worldwide Remote"
        )

        body_text = normalize_text(
            BeautifulSoup(
                fields.get("body", ""),
                "html.parser",
            ).get_text(
                separator=" "
            )
        )

        posted_date = None

        created = (
            fields.get("date", {})
            .get("created")
        )

        if created:

            try:

                posted_date = (
                    datetime.fromisoformat(
                        created.replace(
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
                "ReliefWeb",

            "source_url":
                source_url,

            "title":
                title,

            "company":
                company,

            "location":
                location,

            "description":
                body_text,

            "employment_type":
                "",

            "posted_date":
                posted_date,

            "deadline_date":
                extract_deadline_date(
                    body_text
                ),

        })

    time.sleep(
        RELIEFWEB_REQUEST_DELAY
    )

    logger.info(
        "ReliefWeb returned %d jobs",
        len(jobs),
    )

    return jobs


# ============================================================
# PSC (PUBLIC SERVICE COMMISSION) COLLECTOR
# ============================================================

def parse_psc_page(
    html_text: str,
) -> list[dict[str, Any]]:
    """Parse the PSC active-adverts page into raw job dicts.

    An old-style ASP.NET WebForms page — plain server-rendered
    HTML, no login needed to view listings. Each advert links to
    AdvertDetailsExt.aspx?kpx=<ref>. The page shows "Sorry there
    are no job vacancies at the moment" with zero adverts far
    more often than not, so an empty result here is the normal
    case, not a parsing failure.
    """

    soup = BeautifulSoup(
        html_text,
        "html.parser",
    )

    results: list[dict[str, Any]] = []

    seen_hrefs: set[str] = set()

    for link in soup.find_all(
        "a",
        href=True,
    ):

        href = link["href"]

        if "AdvertDetailsExt.aspx" not in href:
            continue

        if href.startswith("/"):

            href = (
                "https://www.psckjobs.go.ke"
                + href
            )

        elif not href.startswith("http"):

            href = (
                "https://www.psckjobs.go.ke/"
                + href
            )

        if href in seen_hrefs:
            continue

        seen_hrefs.add(href)

        title = clean_text(
            link.get_text()
        ).strip()

        row = (
            link.find_parent("tr")
            or link.find_parent("div")
            or link
        )

        if not title or title.lower() in (
            "view",
            "apply",
            "details",
            "more",
        ):

            # Icon/button-only link text. The advert's title
            # column position relative to a deadline/status
            # column isn't known without a live example to check
            # against (the page shows zero adverts far more often
            # than not), so rather than guess a fixed column
            # order, take every other cell in the same row and
            # use the longest one that isn't itself a date or a
            # bare action word — a real job title reads far
            # longer than either of those.
            candidates: list[str] = []

            for cell in row.find_all(
                ["td", "span", "div"]
            ):

                if link in cell.descendants:
                    continue

                text = clean_text(
                    cell.get_text()
                ).strip()

                if not text or len(text) > 200:
                    continue

                if text.lower() in (
                    "view",
                    "apply",
                    "details",
                    "more",
                ):

                    continue

                if DEADLINE_KEYWORD_RE.search(
                    text
                ):

                    continue

                candidates.append(text)

            if candidates:

                title = max(
                    candidates,
                    key=len,
                )

        if not title:
            continue

        row_text = " ".join(
            row.get_text(
                separator=" "
            ).split()
        )

        results.append({

            "source":
                "PSC",

            "source_url":
                href,

            "title":
                title,

            "company":
                "Public Service Commission",

            "location":
                "Kenya",

            "description":
                normalize_text(row_text),

            "employment_type":
                "",

            "posted_date":
                None,

            "deadline_date":
                extract_deadline_date(
                    row_text
                ),

        })

    return results


def fetch_psc_jobs() -> list[
    dict[str, Any]
]:

    logger.info(
        "Fetching jobs from PSC..."
    )

    jobs: list[dict[str, Any]] = []

    session = requests.Session()

    session.headers.update({

        "User-Agent":
            "Mozilla/5.0 (compatible; "
            "Gunga-Job-Radar/1.0)",

        "Accept":
            "text/html",

    })

    try:

        response = session.get(
            PSC_URL,
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()

        jobs = parse_psc_page(
            response.text
        )

    except requests.RequestException as exc:

        logger.warning(
            "PSC request failed: %s",
            exc,
        )

    time.sleep(
        PSC_REQUEST_DELAY
    )

    logger.info(
        "PSC returned %d jobs",
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

        "deadline_date":
            job.get("deadline_date"),

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

    fuzu_jobs = fetch_fuzu_jobs()

    careerpointkenya_jobs = (
        fetch_careerpointkenya_jobs()
    )

    corporatestaffing_jobs = (
        fetch_corporatestaffing_jobs()
    )

    remoteok_jobs = fetch_remoteok_jobs()

    weworkremotely_jobs = (
        fetch_weworkremotely_jobs()
    )

    reliefweb_jobs = fetch_reliefweb_jobs()

    psc_jobs = fetch_psc_jobs()

    jobs = (
        himalayas_jobs
        + myjobmag_jobs
        + brightermonday_jobs
        + openedcareer_jobs
        + fuzu_jobs
        + careerpointkenya_jobs
        + corporatestaffing_jobs
        + remoteok_jobs
        + weworkremotely_jobs
        + reliefweb_jobs
        + psc_jobs
    )

    logger.info(
        "Processing %d jobs "
        "(%d Himalayas, %d MyJobMag, "
        "%d BrighterMonday, "
        "%d OpenedCareer, %d Fuzu, "
        "%d Career Point Kenya, "
        "%d Corporate Staffing, "
        "%d RemoteOK, %d We Work Remotely, "
        "%d ReliefWeb, %d PSC)...",
        len(jobs),
        len(himalayas_jobs),
        len(myjobmag_jobs),
        len(brightermonday_jobs),
        len(openedcareer_jobs),
        len(fuzu_jobs),
        len(careerpointkenya_jobs),
        len(corporatestaffing_jobs),
        len(remoteok_jobs),
        len(weworkremotely_jobs),
        len(reliefweb_jobs),
        len(psc_jobs),
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
