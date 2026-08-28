"""
Gunga Job Radar
Safe Database Migration

This upgrades the existing Phase 1 database
without deleting existing jobs.

IMPORTANT:
The existing jobs.id SERIAL/INTEGER is preserved.
"""

from __future__ import annotations

import os
import sys

import psycopg2
from dotenv import load_dotenv


load_dotenv()


def main():

    database_url = os.getenv(
        "DATABASE_URL"
    )

    if not database_url:

        print(
            "ERROR: DATABASE_URL is missing."
        )

        return 1

    print()
    print(
        "=" * 60
    )
    print(
        "GUNGA JOB RADAR DATABASE MIGRATION"
    )
    print(
        "=" * 60
    )
    print()

    print(
        "Connecting to database..."
    )

    conn = psycopg2.connect(
        database_url
    )

    try:

        with conn.cursor() as cur:

            # =================================================
            # VERIFY JOBS TABLE
            # =================================================

            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_name = 'jobs'
                );
                """
            )

            jobs_exists = cur.fetchone()[0]

            if not jobs_exists:

                print(
                    "jobs table does not exist."
                )

                print(
                    "Creating fresh schema..."
                )

                with open(
                    os.path.join(
                        os.path.dirname(
                            __file__
                        ),
                        "schema.sql",
                    ),
                    "r",
                    encoding="utf-8",
                ) as file:

                    cur.execute(
                        file.read()
                    )

                conn.commit()

                print(
                    "Fresh schema created."
                )

                return 0

            # =================================================
            # VERIFY EXISTING ID TYPE
            # =================================================

            cur.execute(
                """
                SELECT
                    data_type
                FROM information_schema.columns
                WHERE table_name = 'jobs'
                  AND column_name = 'id';
                """
            )

            result = cur.fetchone()

            if result:

                print(
                    f"Existing jobs.id type: "
                    f"{result[0]}"
                )

            # =================================================
            # ADD UPDATED_AT
            # =================================================

            cur.execute(
                """
                ALTER TABLE jobs
                ADD COLUMN IF NOT EXISTS
                updated_at
                TIMESTAMPTZ
                DEFAULT NOW();
                """
            )

            # =================================================
            # ADD NEW JOB FIELDS
            # =================================================

            cur.execute(
                """
                ALTER TABLE jobs
                ADD COLUMN IF NOT EXISTS
                employment_type TEXT;

                ALTER TABLE jobs
                ADD COLUMN IF NOT EXISTS
                salary TEXT;

                ALTER TABLE jobs
                ADD COLUMN IF NOT EXISTS
                category TEXT;

                ALTER TABLE jobs
                ADD COLUMN IF NOT EXISTS
                published_at TIMESTAMPTZ;

                ALTER TABLE jobs
                ADD COLUMN IF NOT EXISTS
                deadline TIMESTAMPTZ;

                ALTER TABLE jobs
                ADD COLUMN IF NOT EXISTS
                matched_skills TEXT;

                ALTER TABLE jobs
                ADD COLUMN IF NOT EXISTS
                matched_locations TEXT;

                ALTER TABLE jobs
                ADD COLUMN IF NOT EXISTS
                email_sent BOOLEAN
                NOT NULL DEFAULT FALSE;

                ALTER TABLE jobs
                ADD COLUMN IF NOT EXISTS
                is_active BOOLEAN
                NOT NULL DEFAULT TRUE;
                """
            )

            # =================================================
            # BACKFILL UPDATED_AT
            # =================================================

            cur.execute(
                """
                UPDATE jobs
                SET updated_at = NOW()
                WHERE updated_at IS NULL;
                """
            )

            # =================================================
            # NOTIFICATIONS
            # =================================================

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS notifications (
                    id SERIAL PRIMARY KEY,

                    job_id INTEGER
                        REFERENCES jobs(id)
                        ON DELETE CASCADE,

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

            # =================================================
            # SAVED JOBS
            # =================================================

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS saved_jobs (
                    id SERIAL PRIMARY KEY,

                    job_id INTEGER NOT NULL
                        REFERENCES jobs(id)
                        ON DELETE CASCADE,

                    created_at TIMESTAMPTZ
                        NOT NULL DEFAULT NOW(),

                    UNIQUE(job_id)
                );
                """
            )

            # =================================================
            # APPLICATIONS
            # =================================================

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS applications (
                    id SERIAL PRIMARY KEY,

                    job_id INTEGER NOT NULL
                        REFERENCES jobs(id)
                        ON DELETE CASCADE,

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

            # =================================================
            # JOB MATCHES
            # =================================================

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS job_matches (
                    id SERIAL PRIMARY KEY,

                    job_id INTEGER NOT NULL
                        REFERENCES jobs(id)
                        ON DELETE CASCADE,

                    score INTEGER NOT NULL
                        DEFAULT 0,

                    tier TEXT,

                    matched_skills TEXT,

                    matched_locations TEXT,

                    reasons TEXT,

                    blockers TEXT,

                    created_at TIMESTAMPTZ
                        NOT NULL DEFAULT NOW(),

                    UNIQUE(job_id)
                );
                """
            )

            # =================================================
            # JOB SOURCES
            # =================================================

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS job_sources (
                    id SERIAL PRIMARY KEY,

                    name TEXT NOT NULL UNIQUE,

                    base_url TEXT,

                    active BOOLEAN NOT NULL
                        DEFAULT TRUE,

                    created_at TIMESTAMPTZ
                        NOT NULL DEFAULT NOW()
                );
                """
            )

            cur.execute(
                """
                INSERT INTO job_sources (
                    name,
                    base_url,
                    active
                )
                VALUES (
                    'ReliefWeb',
                    'https://reliefweb.int',
                    TRUE
                )
                ON CONFLICT (name)
                DO NOTHING;
                """
            )

            # =================================================
            # INDEXES
            # =================================================

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
                idx_jobs_fetched_at
                ON jobs(fetched_at DESC);
                """,

                """
                CREATE INDEX IF NOT EXISTS
                idx_jobs_tier
                ON jobs(tier);
                """,

                """
                CREATE INDEX IF NOT EXISTS
                idx_notifications_status
                ON notifications(status);
                """,

                """
                CREATE INDEX IF NOT EXISTS
                idx_applications_status
                ON applications(status);
                """,
            ]

            for sql in indexes:

                cur.execute(sql)

            # =================================================
            # TRIGGER FUNCTION
            # =================================================

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

            # =================================================
            # JOB TRIGGER
            # =================================================

            cur.execute(
                """
                DROP TRIGGER IF EXISTS
                jobs_updated_at
                ON jobs;

                CREATE TRIGGER
                jobs_updated_at

                BEFORE UPDATE ON jobs

                FOR EACH ROW

                EXECUTE FUNCTION
                update_updated_at_column();
                """
            )

            # =================================================
            # NOTIFICATION TRIGGER
            # =================================================

            cur.execute(
                """
                DROP TRIGGER IF EXISTS
                notifications_updated_at
                ON notifications;

                CREATE TRIGGER
                notifications_updated_at

                BEFORE UPDATE ON notifications

                FOR EACH ROW

                EXECUTE FUNCTION
                update_updated_at_column();
                """
            )

            # =================================================
            # APPLICATION TRIGGER
            # =================================================

            cur.execute(
                """
                DROP TRIGGER IF EXISTS
                applications_updated_at
                ON applications;

                CREATE TRIGGER
                applications_updated_at

                BEFORE UPDATE ON applications

                FOR EACH ROW

                EXECUTE FUNCTION
                update_updated_at_column();
                """
            )

            # =================================================
            # COMMIT
            # =================================================

            conn.commit()

        print()
        print(
            "=" * 60
        )
        print(
            "MIGRATION SUCCESSFUL"
        )
        print(
            "=" * 60
        )
        print()

        print(
            "Existing jobs were preserved."
        )

        print(
            "Existing jobs.id was preserved."
        )

        print(
            "New Phase 3 tables were created."
        )

        print(
            "Indexes and triggers were installed."
        )

        print()

        return 0

    except Exception as exc:

        conn.rollback()

        print()
        print(
            "=" * 60
        )
        print(
            "MIGRATION FAILED"
        )
        print(
            "=" * 60
        )
        print()

        print(
            f"Error: {exc}"
        )

        return 1

    finally:

        conn.close()


if __name__ == "__main__":

    sys.exit(
        main()
                )
