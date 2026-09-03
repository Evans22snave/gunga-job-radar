"""
Database layer for Gunga Job Radar.

Keeps compatibility with the existing Phase 1 database:
jobs.id remains INTEGER / SERIAL.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Iterator

import psycopg2
from psycopg2.extras import RealDictCursor


logger = logging.getLogger("Gunga Job Radar Database")


class DatabaseError(Exception):
    """Raised when a database operation fails."""


class Database:
    """PostgreSQL database access layer."""

    def __init__(self, database_url: str):
        if not database_url:
            raise ValueError("DATABASE_URL is required")

        self.database_url = database_url

    @contextmanager
    def connection(self) -> Iterator[Any]:
        conn = None

        try:
            conn = psycopg2.connect(
                self.database_url
            )

            yield conn

            conn.commit()

        except Exception as exc:

            if conn:
                conn.rollback()

            logger.exception(
                "Database operation failed"
            )

            raise DatabaseError(
                str(exc)
            ) from exc

        finally:

            if conn:
                conn.close()

    # ========================================================
    # JOBS
    # ========================================================

    def job_exists(
        self,
        source_url: str,
    ) -> bool:

        with self.connection() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM jobs
                        WHERE source_url = %s
                    )
                    """,
                    (source_url,),
                )

                return bool(
                    cur.fetchone()[0]
                )

    def insert_job(
        self,
        job: dict[str, Any],
    ) -> int | None:
        """Insert a job, or — if its source_url already exists —
        backfill any fields that are still NULL on the existing
        row (e.g. posted_date/deadline_date/eligibility added by
        a later version of the scanner) without touching fields
        that already have a value.

        Returns the row id only when this call performed a real
        INSERT (a genuinely new job) — None for a duplicate, even
        though its stale fields may have just been backfilled.
        This preserves the existing "is this new?" contract that
        run_scan()'s new-vs-duplicate and Telegram-retry logic
        depend on; only the freshness of old rows' data changes.
        """

        with self.connection() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    INSERT INTO jobs (
                        source,
                        source_url,
                        title,
                        company,
                        location,
                        description,
                        score,
                        tier,
                        reasons,
                        blockers,
                        eligibility,
                        employment_type,
                        posted_date,
                        deadline_date
                    )
                    VALUES (
                        %(source)s,
                        %(source_url)s,
                        %(title)s,
                        %(company)s,
                        %(location)s,
                        %(description)s,
                        %(score)s,
                        %(tier)s,
                        %(reasons)s,
                        %(blockers)s,
                        %(eligibility)s,
                        %(employment_type)s,
                        %(posted_date)s,
                        %(deadline_date)s
                    )
                    ON CONFLICT (source_url) DO UPDATE SET
                        eligibility = COALESCE(
                            jobs.eligibility, EXCLUDED.eligibility
                        ),
                        employment_type = COALESCE(
                            NULLIF(jobs.employment_type, ''),
                            EXCLUDED.employment_type
                        ),
                        posted_date = COALESCE(
                            jobs.posted_date, EXCLUDED.posted_date
                        ),
                        deadline_date = COALESCE(
                            jobs.deadline_date, EXCLUDED.deadline_date
                        )
                    RETURNING id, (xmax = 0) AS inserted
                    """,
                    job,
                )

                row = cur.fetchone()

                if row is None:
                    return None

                job_id, was_inserted = row

                if not was_inserted:
                    return None

                return int(job_id)

    def get_job(
        self,
        job_id: int,
    ):

        with self.connection() as conn:

            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cur:

                cur.execute(
                    """
                    SELECT *
                    FROM jobs
                    WHERE id = %s
                    """,
                    (job_id,),
                )

                return cur.fetchone()

    def get_job_by_url(
        self,
        source_url: str,
    ):

        with self.connection() as conn:

            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cur:

                cur.execute(
                    """
                    SELECT *
                    FROM jobs
                    WHERE source_url = %s
                    """,
                    (source_url,),
                )

                return cur.fetchone()

    # ========================================================
    # TELEGRAM
    # ========================================================

    def mark_telegram_sent(
        self,
        job_id: int,
    ) -> None:

        with self.connection() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    UPDATE jobs
                    SET telegram_sent = TRUE
                    WHERE id = %s
                    """,
                    (job_id,),
                )

    # ========================================================
    # DIGEST
    # ========================================================

    def get_undigested_jobs(
        self,
    ):

        with self.connection() as conn:

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
                        source_url,
                        score,
                        tier
                    FROM jobs
                    WHERE digested = FALSE
                    ORDER BY
                        score DESC,
                        fetched_at DESC
                    """
                )

                return cur.fetchall()

    def mark_jobs_digested(
        self,
        job_ids: list[int],
    ) -> None:

        if not job_ids:
            return

        with self.connection() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    UPDATE jobs
                    SET digested = TRUE
                    WHERE id = ANY(%s)
                    """,
                    (job_ids,),
                )

    # ========================================================
    # NOTIFICATIONS
    # ========================================================

    def create_notification(
        self,
        job_id: int,
        channel: str,
    ) -> int:

        with self.connection() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    INSERT INTO notifications (
                        job_id,
                        channel,
                        status
                    )
                    VALUES (
                        %s,
                        %s,
                        'pending'
                    )
                    RETURNING id
                    """,
                    (
                        job_id,
                        channel,
                    ),
                )

                return int(
                    cur.fetchone()[0]
                )

    def mark_notification_sent(
        self,
        notification_id: int,
    ) -> None:

        with self.connection() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    UPDATE notifications
                    SET
                        status = 'sent',
                        attempts = attempts + 1,
                        sent_at = NOW(),
                        updated_at = NOW(),
                        last_error = NULL
                    WHERE id = %s
                    """,
                    (notification_id,),
                )

    def mark_notification_failed(
        self,
        notification_id: int,
        error: str,
    ) -> None:

        with self.connection() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    UPDATE notifications
                    SET
                        status = 'failed',
                        attempts = attempts + 1,
                        last_error = %s,
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (
                        error,
                        notification_id,
                    ),
            )
