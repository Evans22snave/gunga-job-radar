"""
Diagnostic utilities for Gunga Job Radar.

Inspect database state, scoring decisions, and job processing.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from dotenv import load_dotenv
from psycopg2.extras import RealDictCursor

from database.db import Database

logger = logging.getLogger("Gunga Job Radar Diagnostics")


def inspect_jobs(
    database: Database,
    limit: int = 20,
) -> None:
    """Inspect recent jobs in the database."""

    logger.info("")
    logger.info("========== JOBS IN DATABASE ==========")

    with database.connection() as conn:

        with conn.cursor(
            cursor_factory=RealDictCursor
        ) as cur:

            cur.execute(
                """
                SELECT
                    id,
                    title,
                    company,
                    location,
                    score,
                    tier,
                    telegram_sent,
                    digested,
                    created_at
                FROM jobs
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (limit,),
            )

            rows = cur.fetchall()

    if not rows:
        logger.info("No jobs in database.")
        return

    logger.info(f"Total: {len(rows)} recent jobs")
    logger.info("")

    for job in rows:

        logger.info(
            f"ID: {job['id']} | "
            f"Score: {job['score']}% | "
            f"Tier: {job['tier']}"
        )

        logger.info(
            f"  Title: {job['title']}"
        )

        logger.info(
            f"  Company: {job['company']}"
        )

        logger.info(
            f"  Location: {job['location']}"
        )

        logger.info(
            f"  Telegram sent: {job['telegram_sent']} | "
            f"Digested: {job['digested']}"
        )

        logger.info(
            f"  Created: {job['created_at']}"
        )

        logger.info("")


def inspect_strong_matches(
    database: Database,
) -> None:
    """Inspect strong matches and their notification state."""

    logger.info("")
    logger.info("========== STRONG MATCHES ==========")

    with database.connection() as conn:

        with conn.cursor(
            cursor_factory=RealDictCursor
        ) as cur:

            cur.execute(
                """
                SELECT
                    id,
                    title,
                    company,
                    score,
                    telegram_sent,
                    reasons
                FROM jobs
                WHERE tier = 'strong'
                ORDER BY score DESC
                """
            )

            rows = cur.fetchall()

    if not rows:
        logger.info("No strong matches in database.")
        return

    logger.info(f"Total: {len(rows)} strong matches")
    logger.info("")

    for job in rows:

        status = (
            "✅ Notified"
            if job["telegram_sent"]
            else "⏳ Pending Telegram"
        )

        logger.info(
            f"{job['score']}% | {job['title']} | {status}"
        )

        logger.info(
            f"  Company: {job['company']}"
        )

        if job["reasons"]:

            reasons = job["reasons"].split("; ")

            logger.info(
                f"  Reasons: {reasons[0]}"
            )

        logger.info("")


def inspect_undigested_jobs(
    database: Database,
) -> None:
    """Inspect jobs pending digest."""

    logger.info("")
    logger.info("========== UNDIGESTED JOBS ==========")

    jobs = database.get_undigested_jobs()

    if not jobs:
        logger.info("No undigested jobs.")
        return

    logger.info(f"Total: {len(jobs)} jobs pending digest")

    strong = sum(
        1 for job in jobs if job["tier"] == "strong"
    )

    consider = sum(
        1 for job in jobs if job["tier"] == "consider"
    )

    logger.info(f"  Strong: {strong}")
    logger.info(f"  Consider: {consider}")

    logger.info("")


def inspect_telegram_state(
    database: Database,
) -> None:
    """Inspect Telegram notification state."""

    logger.info("")
    logger.info("========== TELEGRAM STATE ==========")

    with database.connection() as conn:

        with conn.cursor(
            cursor_factory=RealDictCursor
        ) as cur:

            cur.execute(
                """
                SELECT
                    tier,
                    COUNT(*) as count,
                    SUM(CASE WHEN telegram_sent THEN 1 ELSE 0 END) as sent,
                    SUM(CASE WHEN NOT telegram_sent THEN 1 ELSE 0 END) as pending
                FROM jobs
                GROUP BY tier
                ORDER BY tier DESC
                """
            )

            rows = cur.fetchall()

    logger.info("Telegram notification state by tier:")
    logger.info("")

    for row in rows:

        logger.info(
            f"{row['tier'].upper()}: "
            f"{row['count']} total | "
            f"{row['sent']} sent | "
            f"{row['pending']} pending"
        )

    logger.info("")


def inspect_database_stats(
    database: Database,
) -> None:
    """Print comprehensive database statistics."""

    logger.info("")
    logger.info("========== DATABASE STATISTICS ==========")

    with database.connection() as conn:

        with conn.cursor(
            cursor_factory=RealDictCursor
        ) as cur:

            cur.execute(
                """
                SELECT
                    COUNT(*) as total_jobs,
                    COUNT(CASE WHEN telegram_sent THEN 1 END) as telegram_sent_count,
                    COUNT(CASE WHEN digested THEN 1 END) as digested_count,
                    AVG(score) as avg_score,
                    MAX(score) as max_score,
                    MIN(score) as min_score
                FROM jobs
                """
            )

            stats = cur.fetchone()

    logger.info(f"Total jobs: {stats['total_jobs']}")
    logger.info(
        f"Telegram sent: {stats['telegram_sent_count']}"
    )
    logger.info(f"Digested: {stats['digested_count']}")
    logger.info(
        f"Average score: {stats['avg_score']:.1f}%"
    )
    logger.info(
        f"Score range: {stats['min_score']}% - {stats['max_score']}%"
    )

    logger.info("")


def run_full_diagnostics(
    database: Database,
) -> None:
    """Run comprehensive database diagnostics."""

    logger.info("")
    logger.info("=" * 60)
    logger.info("GUNGA JOB RADAR — FULL DIAGNOSTICS")
    logger.info("=" * 60)

    inspect_database_stats(database)
    inspect_strong_matches(database)
    inspect_undigested_jobs(database)
    inspect_telegram_state(database)
    inspect_jobs(database)

    logger.info("=" * 60)
    logger.info("DIAGNOSTICS COMPLETE")
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

    run_full_diagnostics(db)
