"""
Gunga Job Radar — Database Schema & Initialization

This module defines the PostgreSQL schema for job tracking,
notifications, and digest state.
"""

from __future__ import annotations

import logging

import psycopg2

logger = logging.getLogger("Gunga Job Radar Database")


# ============================================================
# SCHEMA
# ============================================================

SCHEMA = """

-- Main jobs table
CREATE TABLE IF NOT EXISTS jobs (
    id SERIAL PRIMARY KEY,
    source VARCHAR(255) NOT NULL,
    source_url VARCHAR(2048) UNIQUE NOT NULL,
    title VARCHAR(255) NOT NULL,
    company VARCHAR(255),
    location VARCHAR(255),
    description TEXT,
    score INTEGER DEFAULT 0,
    tier VARCHAR(50) DEFAULT 'poor',
    eligibility VARCHAR(30),
    employment_type VARCHAR(60),
    posted_date DATE,
    reasons TEXT,
    blockers TEXT,
    telegram_sent BOOLEAN DEFAULT FALSE,
    digested BOOLEAN DEFAULT FALSE,
    applied BOOLEAN NOT NULL DEFAULT FALSE,
    applied_at TIMESTAMP,
    fetched_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW()
);

-- Notifications table (for tracking Telegram sends)
CREATE TABLE IF NOT EXISTS notifications (
    id SERIAL PRIMARY KEY,
    job_id INTEGER REFERENCES jobs(id) ON DELETE CASCADE,
    channel VARCHAR(50) NOT NULL,
    status VARCHAR(50) DEFAULT 'pending',
    attempts INTEGER DEFAULT 0,
    sent_at TIMESTAMP,
    last_error TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_jobs_source_url ON jobs(source_url);
CREATE INDEX IF NOT EXISTS idx_jobs_telegram_sent ON jobs(telegram_sent);
CREATE INDEX IF NOT EXISTS idx_jobs_digested ON jobs(digested);
CREATE INDEX IF NOT EXISTS idx_jobs_tier ON jobs(tier);
CREATE INDEX IF NOT EXISTS idx_jobs_score ON jobs(score);
CREATE INDEX IF NOT EXISTS idx_jobs_eligibility ON jobs(eligibility);
CREATE INDEX IF NOT EXISTS idx_jobs_applied ON jobs(applied);
CREATE INDEX IF NOT EXISTS idx_jobs_posted_date ON jobs(posted_date);
CREATE INDEX IF NOT EXISTS idx_notifications_job_id ON notifications(job_id);
CREATE INDEX IF NOT EXISTS idx_notifications_status ON notifications(status);

"""


def initialize_database(
    database_url: str,
) -> None:
    """Initialize the PostgreSQL database with schema."""

    conn = None

    try:

        conn = psycopg2.connect(
            database_url
        )

        with conn.cursor() as cur:

            cur.execute(SCHEMA)

        conn.commit()

        logger.info(
            "Database schema initialized successfully."
        )

    except Exception as exc:

        logger.exception(
            "Failed to initialize database: %s",
            exc,
        )

        raise

    finally:

        if conn:
            conn.close()


if __name__ == "__main__":

    import os

    from dotenv import load_dotenv

    load_dotenv()

    db_url = os.getenv("DATABASE_URL")

    if not db_url:
        raise ValueError("DATABASE_URL not set")

    initialize_database(db_url)

    print("✅ Database initialized")
