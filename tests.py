"""
Integration test for Gunga Job Radar.

Simulates a complete scan → score → store → telegram workflow.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from dotenv import load_dotenv

from database.db import Database
from job_radar import (
    CONSIDER_THRESHOLD,
    PROFILE,
    STRONG_MATCH_THRESHOLD,
    classify_location,
    score_job,
)

logger = logging.getLogger("Gunga Job Radar Tests")


# ============================================================
# TEST JOBS
# ============================================================

TEST_JOBS = [
    {
        "source": "Test",
        "source_url": "https://test.local/job/1",
        "title": "Junior Web Developer",
        "company": "TechCorp Kenya",
        "location": "Nairobi, Kenya",
        "description": (
            "Looking for a junior web developer with HTML, CSS, JavaScript, and React experience. "
            "Entry-level position. No experience required. "
            "Located in Nairobi, Kenya."
        ),
    },
    {
        "source": "Test",
        "source_url": "https://test.local/job/2",
        "title": "IT Support Technician",
        "company": "GlobalTech Remote",
        "location": "Remote / Worldwide",
        "description": (
            "IT support role for remote team. Hardware troubleshooting, networking, help desk support. "
            "Entry-level friendly. Diploma holders welcome. "
            "Work from anywhere worldwide."
        ),
    },
    {
        "source": "Test",
        "source_url": "https://test.local/job/3",
        "title": "Senior Backend Engineer",
        "company": "BigCorp US",
        "location": "United States Only",
        "description": (
            "Seeking senior backend engineer with 10+ years experience. "
            "US residents only. Master's degree required. "
            "Advanced node.js and postgresql skills."
        ),
    },
    {
        "source": "Test",
        "source_url": "https://test.local/job/4",
        "title": "Android Developer",
        "company": "MobileFirst Africa",
        "location": "Africa",
        "description": (
            "Junior Android developer needed for East African market. "
            "Kotlin and Java skills. Entry-level graduate positions welcome. "
            "Based in East Africa."
        ),
    },
]


# ============================================================
# TESTS
# ============================================================

def test_location_classification() -> None:
    """Test location classification logic."""

    logger.info("")
    logger.info("========== TEST: Location Classification ==========")

    test_cases = [
        (TEST_JOBS[0], "KENYA"),
        (TEST_JOBS[1], "REMOTE-WORLDWIDE"),
        (TEST_JOBS[2], "REMOTE-RESTRICTED"),
        (TEST_JOBS[3], "REMOTE-AFRICA"),
    ]

    for job, expected_location in test_cases:

        location_class, evidence = classify_location(job)

        status = "✅" if location_class == expected_location else "❌"

        logger.info(
            f"{status} {job['title']} → {location_class} "
            f"(expected {expected_location})"
        )

        if location_class != expected_location:
            logger.warning(f"   Evidence: {evidence}")


def test_scoring() -> None:
    """Test job scoring logic."""

    logger.info("")
    logger.info("========== TEST: Job Scoring ==========")

    for job in TEST_JOBS:

        score, tier, reasons, blockers, skills, locations, eligibility = score_job(job)

        logger.info(
            f"Score: {score}% | Tier: {tier} | "
            f"Title: {job['title']}"
        )

        if tier == "strong":
            logger.info("   ✅ Strong match")
        elif tier == "consider":
            logger.info("   ⏳ Consider")
        else:
            logger.info("   ❌ Poor match")

        if reasons:
            logger.info(f"   Reasons: {reasons[0]}")

        if blockers:
            logger.info(f"   Blockers: {blockers[0]}")

        logger.info("")


def test_strong_match_detection() -> None:
    """Verify that strong matches are actually detected."""

    logger.info("")
    logger.info("========== TEST: Strong Match Detection ==========")

    strong_matches = []

    for job in TEST_JOBS:

        score, tier, _, _, _, _, _ = score_job(job)

        if tier == "strong":
            strong_matches.append((job["title"], score))

    if strong_matches:
        logger.info(f"✅ Found {len(strong_matches)} strong matches:")
        for title, score in strong_matches:
            logger.info(f"   {score}% - {title}")
    else:
        logger.warning("❌ No strong matches detected!")

    logger.info("")


def test_database_operations(
    database: Database,
) -> None:
    """Test database insert and retrieval."""

    logger.info("")
    logger.info("========== TEST: Database Operations ==========")

    try:

        # Test insert
        job = TEST_JOBS[0]
        score, tier, reasons, blockers, _, _, _ = score_job(job)

        payload = {
            "source": job["source"],
            "source_url": job["source_url"],
            "title": job["title"],
            "company": job["company"],
            "location": job["location"],
            "description": job["description"][:10000],
            "score": score,
            "tier": tier,
            "reasons": "; ".join(reasons),
            "blockers": "; ".join(blockers),
        }

        job_id = database.insert_job(payload)

        if job_id:
            logger.info(f"✅ Inserted job with ID: {job_id}")
        else:
            logger.info("⏳ Job already exists (duplicate URL)")

        # Test retrieval
        retrieved = database.get_job(job_id)

        if retrieved:
            logger.info(
                f"✅ Retrieved job: "
                f"{retrieved['title']} "
                f"(Score: {retrieved['score']}%)"
            )
        else:
            logger.warning("❌ Failed to retrieve job")

        # Test duplicate detection
        duplicate_id = database.insert_job(payload)

        if duplicate_id is None:
            logger.info(
                "✅ Duplicate detection working "
                "(insert returned None)"
            )
        else:
            logger.warning(
                "❌ Duplicate not detected "
                f"(returned ID: {duplicate_id})"
            )

    except Exception as exc:
        logger.error(f"❌ Database test failed: {exc}")

    logger.info("")


def test_telegram_state(
    database: Database,
) -> None:
    """Test Telegram notification state tracking."""

    logger.info("")
    logger.info("========== TEST: Telegram State ==========")

    try:

        # Insert a test strong match
        job = TEST_JOBS[0]
        score, tier, reasons, blockers, _, _, _ = score_job(job)

        payload = {
            "source": job["source"],
            "source_url": job["source_url"],
            "title": job["title"],
            "company": job["company"],
            "location": job["location"],
            "description": job["description"][:10000],
            "score": score,
            "tier": tier,
            "reasons": "; ".join(reasons),
            "blockers": "; ".join(blockers),
        }

        job_id = database.insert_job(payload)

        if job_id is None:
            logger.info("Using existing job for test")
            # Retrieve the existing one
            with database.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id FROM jobs WHERE source_url = %s",
                        (job["source_url"],),
                    )
                    row = cur.fetchone()
                    job_id = row[0] if row else None

        if job_id:

            # Check initial state
            retrieved = database.get_job(job_id)
            logger.info(
                f"Initial telegram_sent: "
                f"{retrieved['telegram_sent']}"
            )

            # Mark as sent
            database.mark_telegram_sent(job_id)
            logger.info("✅ Marked as telegram_sent=true")

            # Verify
            retrieved = database.get_job(job_id)
            if retrieved["telegram_sent"]:
                logger.info("✅ telegram_sent persisted correctly")
            else:
                logger.warning("❌ telegram_sent not persisted")

    except Exception as exc:
        logger.error(f"❌ Telegram state test failed: {exc}")

    logger.info("")


def run_all_tests(
    database: Database,
) -> None:
    """Run all tests."""

    logger.info("")
    logger.info("=" * 60)
    logger.info("GUNGA JOB RADAR — INTEGRATION TESTS")
    logger.info("=" * 60)

    test_location_classification()
    test_scoring()
    test_strong_match_detection()
    test_database_operations(database)
    test_telegram_state(database)

    logger.info("=" * 60)
    logger.info("TESTS COMPLETE")
    logger.info("=" * 60)


if __name__ == "__main__":

    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s | "
            "%(levelname)s | "
            "%(message)s"
        ),
    )

    load_dotenv()

    db_url = os.getenv("DATABASE_URL")

    if not db_url:
        raise ValueError("DATABASE_URL not set")

    db = Database(db_url)

    run_all_tests(db)
