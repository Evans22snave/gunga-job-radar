"""
Gunga Job Radar
Database Migration — Phase 3

Safely upgrades the existing jobs table without deleting
existing job records.

Run:
    python database/migrate.py
"""

from __future__ import annotations

import os
import sys

import psycopg2
from dotenv import load_dotenv


load_dotenv()


def get_database_url() -> str:
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise RuntimeError(
            "DATABASE_URL environment variable is missing."
        )

    return database_url


def migrate():
    database_url = get_database_url()

    print("Connecting to database...")

    conn = psycopg2.connect(database_url)

    try:

        with conn.cursor() as cur:

            print("Creating job_sources table...")

            cur.execute(
                """
                CREATE EXTENSION IF NOT EXISTS pgcrypto;

                CREATE TABLE IF NOT EXISTS job_sources (
                    id UUID PRIMARY KEY
                        DEFAULT gen_random_uuid(),

                    name TEXT NOT NULL UNIQUE,

                    base_url TEXT,

                    active BOOLEAN NOT NULL
                        DEFAULT TRUE,

                    created_at TIMESTAMPTZ
                        NOT NULL DEFAULT NOW()
                );
                """
            )

            print("Upgrading jobs table...")

            # ------------------------------------------------
            # Add missing columns individually.
            # PostgreSQL will leave existing data untouched.
            # ------------------------------------------------

            columns = [
                (
                    "source_id",
                    """
                    UUID REFERENCES job_sources(id)
                    ON DELETE SET NULL
                    """
                ),
                (
                    "employment_type",
                    "TEXT"
                ),
                (
                    "salary",
                    "TEXT"
                ),
                (
                    "category",
                    "TEXT"
                ),
                (
                    "published_at",
                    "TIMESTAMPTZ"
                ),
                (
                    "deadline",
                    "TIMESTAMPTZ"
                ),
                (
                    "updated_at",
                    "TIMESTAMPTZ DEFAULT NOW()"
                ),
                (
                    "tier",
                    "TEXT"
                ),
                (
                    "reasons",
                    "TEXT"
                ),
                (
                    "blockers",
                    "TEXT"
                ),
                (
                    "matched_skills",
                    "TEXT"
                ),
                (
                    "matched_locations",
                    "TEXT"
                ),
                (
                    "email_sent",
                    "BOOLEAN NOT NULL DEFAULT FALSE"
                ),
                (
                    "is_active",
                    "BOOLEAN NOT NULL DEFAULT TRUE"
                ),
            ]

            for column_name, column_type in columns:

                cur.execute(
                    f"""
                    ALTER TABLE jobs
                    ADD COLUMN IF NOT EXISTS
                    {column_name}
                    {column_type};
                    """
                )

            # ------------------------------------------------
            # Make sure fetched_at exists.
            # ------------------------------------------------

            cur.execute(
                """
                ALTER TABLE jobs
                ADD COLUMN IF NOT EXISTS
                fetched_at
                TIMESTAMPTZ DEFAULT NOW();
                """
            )

            # ------------------------------------------------
            # Fill NULL timestamps for old records.
            # ------------------------------------------------

            cur.execute(
                """
                UPDATE jobs
                SET fetched_at = NOW()
                WHERE fetched_at IS NULL;
                """
            )

            cur.execute(
                """
                UPDATE jobs
                SET updated_at = NOW()
                WHERE updated_at IS NULL;
                """
            )

            # ------------------------------------------------
            # Make source available for old records.
            # ------------------------------------------------

            cur.execute(
                """
                UPDATE jobs
                SET source = 'MyJobMag'
                WHERE source IS NULL
                   OR TRIM(source) = '';
                """
            )

            # ------------------------------------------------
            # Create source record.
            # ------------------------------------------------

            cur.execute(
                """
                INSERT INTO job_sources (
                    name,
                    base_url,
                    active
                )
                VALUES (
                    'MyJobMag',
                    'https://www.myjobmag.co.ke',
                    TRUE
                )
                ON CONFLICT (name)
                DO NOTHING;
                """
            )

            # ------------------------------------------------
            # Link existing MyJobMag jobs.
            # ------------------------------------------------

            cur.execute(
                """
                UPDATE jobs
                SET source_id = (
                    SELECT id
                    FROM job_sources
                    WHERE name = 'MyJobMag'
                    LIMIT 1
                )
                WHERE source_id IS NULL
                  AND source = 'MyJobMag';
                """
            )

            # ------------------------------------------------
            # Create indexes.
            # ------------------------------------------------

            print("Creating indexes...")

            indexes = [
                """
                CREATE INDEX IF NOT EXISTS
                idx_jobs_score
                ON jobs(score DESC);
                """,

                """
                CREATE INDEX IF NOT EXISTS
                idx_jobs_location
                ON jobs(location);
                """,

                """
                CREATE INDEX IF NOT EXISTS
                idx_jobs_source
                ON jobs(source);
                """,

                """
                CREATE INDEX IF NOT EXISTS
                idx_jobs_source_id
                ON jobs(source_id);
                """,

                """
                CREATE INDEX IF NOT EXISTS
                idx_jobs_fetched_at
                ON jobs(fetched_at DESC);
                """,

                """
                CREATE INDEX IF NOT EXISTS
                idx_jobs_published_at
                ON jobs(published_at DESC);
                """,

                """
                CREATE INDEX IF NOT EXISTS
                idx_jobs_deadline
                ON jobs(deadline);
                """,

                """
                CREATE INDEX IF NOT EXISTS
                idx_jobs_active
                ON jobs(is_active);
                """,

                """
                CREATE INDEX IF NOT EXISTS
                idx_jobs_tier
                ON jobs(tier);
                """,
            ]

            for index_sql in indexes:
                cur.execute(index_sql)

            # ------------------------------------------------
            # JOB MATCHES
            # ------------------------------------------------

            print("Creating job_matches...")

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS job_matches (
                    id UUID PRIMARY KEY
                        DEFAULT gen_random_uuid(),

                    job_id UUID,

                    score INTEGER NOT NULL
                        DEFAULT 0,

                    tier TEXT,

                    matched_skills TEXT,

                    matched_locations TEXT,

                    reasons TEXT,

                    blockers TEXT,

                    created_at TIMESTAMPTZ
                        NOT NULL DEFAULT NOW()
                );
                """
            )

            # ------------------------------------------------
            # NOTIFICATIONS
            # ------------------------------------------------

            print("Creating notifications...")

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS notifications (
                    id UUID PRIMARY KEY
                        DEFAULT gen_random_uuid(),

                    job_id UUID,

                    channel TEXT NOT NULL,

                    status TEXT NOT NULL
                        DEFAULT 'pending',

                    attempts INTEGER NOT NULL
                        DEFAULT 0,

                    last_error TEXT,

                    sent_at TIMESTAMPTZ,

                    created_at TIMESTAMPTZ
                        NOT NULL DEFAULT NOW(),

                    updated_at TIMESTAMPTZ
                        NOT NULL DEFAULT NOW()
                );
                """
            )

            # ------------------------------------------------
            # SAVED JOBS
            # ------------------------------------------------

            print("Creating saved_jobs...")

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS saved_jobs (
                    id UUID PRIMARY KEY
                        DEFAULT gen_random_uuid(),

                    job_id UUID,

                    created_at TIMESTAMPTZ
                        NOT NULL DEFAULT NOW(),

                    UNIQUE(job_id)
                );
                """
            )

            # ------------------------------------------------
            # APPLICATIONS
            # ------------------------------------------------

            print("Creating applications...")

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS applications (
                    id UUID PRIMARY KEY
                        DEFAULT gen_random_uuid(),

                    job_id UUID,

                    status TEXT NOT NULL
                        DEFAULT 'saved',

                    applied_at TIMESTAMPTZ,

                    interview_at TIMESTAMPTZ,

                    notes TEXT,

                    created_at TIMESTAMPTZ
                        NOT NULL DEFAULT NOW(),

                    updated_at TIMESTAMPTZ
                        NOT NULL DEFAULT NOW(),

                    UNIQUE(job_id)
                );
                """
            )

            # ------------------------------------------------
            # TRIGGER FUNCTION
            # ------------------------------------------------

            print("Creating update trigger function...")

            cur.execute(
                """
                CREATE OR REPLACE FUNCTION
                update_updated_at_column()
                RETURNS TRIGGER AS $$
                BEGIN
                    NEW.updated_at = NOW();
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql;
                """
            )

            # ------------------------------------------------
            # JOB TRIGGER
            # ------------------------------------------------

            cur.execute(
                """
                DROP TRIGGER IF EXISTS
                jobs_updated_at
                ON jobs;

                CREATE TRIGGER jobs_updated_at
                BEFORE UPDATE ON jobs
                FOR EACH ROW
                EXECUTE FUNCTION
                update_updated_at_column();
                """
            )

            # ------------------------------------------------
            # NOTIFICATION TRIGGER
            # ------------------------------------------------

            cur.execute(
                """
                DROP TRIGGER IF EXISTS
                notifications_updated_at
                ON notifications;

                CREATE TRIGGER notifications_updated_at
                BEFORE UPDATE ON notifications
                FOR EACH ROW
                EXECUTE FUNCTION
                update_updated_at_column();
                """
            )

            # ------------------------------------------------
            # APPLICATION TRIGGER
            # ------------------------------------------------

            cur.execute(
                """
                DROP TRIGGER IF EXISTS
                applications_updated_at
                ON applications;

                CREATE TRIGGER applications_updated_at
                BEFORE UPDATE ON applications
                FOR EACH ROW
                EXECUTE FUNCTION
                update_updated_at_column();
                """
            )

            conn.commit()

        print()
        print("=" * 60)
        print("MIGRATION COMPLETED SUCCESSFULLY")
        print("=" * 60)
        print()
        print("Existing jobs were preserved.")
        print("New Phase 3 tables are ready.")
        print()

    except Exception:

        conn.rollback()

        print()
        print("=" * 60)
        print("MIGRATION FAILED")
        print("=" * 60)
        print()

        raise

    finally:

        conn.close()


if __name__ == "__main__":

    try:
        migrate()

    except Exception as exc:

        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )

        sys.exit(1)
