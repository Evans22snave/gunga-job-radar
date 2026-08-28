"""
Gunga Job Radar
Database Layer — Phase 3

Keeps PostgreSQL/Supabase operations separate from the
job collection and matching logic.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Iterator

import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger("Gunga Job Radar")


class DatabaseError(Exception):
    """Raised when a database operation fails."""


class Database:
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
    ) -> bool:

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
                        employment_type,
                        salary,
                        category,
                        published_at,
                        deadline,
                        score,
                        tier,
                        reasons,
                        blockers,
                        matched_skills,
                        matched_locations
                    )
                    VALUES (
                        %(source)s,
                        %(source_url)s,
                        %(title)s,
                        %(company)s,
                        %(location)s,
                        %(description)s,
                        %(employment_type)s,
                        %(salary)s,
                        %(category)s,
                        %(published_at)s,
                        %(deadline)s,
                        %(score)s,
                        %(tier)s,
                        %(reasons)s,
                        %(blockers)s,
                        %(matched_skills)s,
                        %(matched_locations)s
                    )
                    ON CONFLICT (source_url)
                    DO NOTHING
                    RETURNING id
                    """,
                    job,
                )

                row = cur.fetchone()

                return row is not None

    def get_job(
        self,
        job_id: str,
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

    # ========================================================
    # TELEGRAM NOTIFICATIONS
    # ========================================================

    def get_pending_telegram_jobs(
        self,
        minimum_score: int = 75,
        limit: int = 20,
    ):

        with self.connection() as conn:

            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cur:

                cur.execute(
                    """
                    SELECT *
                    FROM jobs
                    WHERE score >= %s
                      AND telegram_sent = FALSE
                    ORDER BY score DESC, fetched_at DESC
                    LIMIT %s
                    """,
                    (
                        minimum_score,
                        limit,
                    ),
                )

                return cur.fetchall()

    def mark_telegram_sent(
        self,
        job_id: str,
    ):

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
    # EMAIL DIGEST
    # ========================================================

    def get_undigested_jobs(
        self,
        limit: int = 100,
    ):

        with self.connection() as conn:

            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cur:

                cur.execute(
                    """
                    SELECT *
                    FROM jobs
                    WHERE digested = FALSE
                    ORDER BY score DESC, fetched_at DESC
                    LIMIT %s
                    """,
                    (limit,),
                )

                return cur.fetchall()

    def mark_jobs_digested(
        self,
        job_ids: list[str],
    ):

        if not job_ids:
            return

        with self.connection() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    UPDATE jobs
                    SET digested = TRUE,
                        email_sent = TRUE
                    WHERE id = ANY(%s)
                    """,
                    (job_ids,),
                )

    # ========================================================
    # JOB MATCHES
    # ========================================================

    def save_match(
        self,
        job_id: str,
        score: int,
        tier: str,
        matched_skills: str,
        matched_locations: str,
        reasons: str,
        blockers: str,
    ):

        with self.connection() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    INSERT INTO job_matches (
                        job_id,
                        score,
                        tier,
                        matched_skills,
                        matched_locations,
                        reasons,
                        blockers
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (job_id)
                    DO UPDATE SET
                        score = EXCLUDED.score,
                        tier = EXCLUDED.tier,
                        matched_skills = EXCLUDED.matched_skills,
                        matched_locations = EXCLUDED.matched_locations,
                        reasons = EXCLUDED.reasons,
                        blockers = EXCLUDED.blockers
                    """,
                    (
                        job_id,
                        score,
                        tier,
                        matched_skills,
                        matched_locations,
                        reasons,
                        blockers,
                    ),
                )

    # ========================================================
    # NOTIFICATION TRACKING
    # ========================================================

    def create_notification(
        self,
        job_id: str,
        channel: str,
    ) -> str:

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

                return str(
                    cur.fetchone()[0]
                )

    def update_notification(
        self,
        notification_id: str,
        status: str,
        attempts: int,
        error: str | None = None,
    ):

        with self.connection() as conn:

            with conn.cursor() as cur:

                if status == "sent":

                    cur.execute(
                        """
                        UPDATE notifications
                        SET status = %s,
                            attempts = %s,
                            last_error = NULL,
                            sent_at = NOW()
                        WHERE id = %s
                        """,
                        (
                            status,
                            attempts,
                            notification_id,
                        ),
                    )

                else:

                    cur.execute(
                        """
                        UPDATE notifications
                        SET status = %s,
                            attempts = %s,
                            last_error = %s
                        WHERE id = %s
                        """,
                        (
                            status,
                            attempts,
                            error,
                            notification_id,
                        ),
                    )

    # ========================================================
    # SAVED JOBS
    # ========================================================

    def save_job_for_user(
        self,
        job_id: str,
    ):

        with self.connection() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    INSERT INTO saved_jobs (
                        job_id
                    )
                    VALUES (%s)
                    ON CONFLICT (job_id)
                    DO NOTHING
                    """,
                    (job_id,),
                )

    def remove_saved_job(
        self,
        job_id: str,
    ):

        with self.connection() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    DELETE FROM saved_jobs
                    WHERE job_id = %s
                    """,
                    (job_id,),
                )

    # ========================================================
    # APPLICATION TRACKING
    # ========================================================

    def create_application(
        self,
        job_id: str,
        status: str = "saved",
        notes: str | None = None,
    ):

        with self.connection() as conn:

            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cur:

                cur.execute(
                    """
                    INSERT INTO applications (
                        job_id,
                        status,
                        notes
                    )
                    VALUES (
                        %s,
                        %s,
                        %s
                    )
                    ON CONFLICT (job_id)
                    DO UPDATE SET
                        status = EXCLUDED.status,
                        notes = EXCLUDED.notes,
                        updated_at = NOW()
                    RETURNING *
                    """,
                    (
                        job_id,
                        status,
                        notes,
                    ),
                )

                return cur.fetchone()

    def update_application(
        self,
        job_id: str,
        status: str,
        notes: str | None = None,
    ):

        with self.connection() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    UPDATE applications
                    SET status = %s,
                        notes = COALESCE(
                            %s,
                            notes
                        ),
                        applied_at = CASE
                            WHEN %s = 'applied'
                                 AND applied_at IS NULL
                            THEN NOW()
                            ELSE applied_at
                        END,
                        updated_at = NOW()
                    WHERE job_id = %s
                    """,
                    (
                        status,
                        notes,
                        status,
                        job_id,
                    ),
                )

    def get_applications(self):

        with self.connection() as conn:

            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cur:

                cur.execute(
                    """
                    SELECT
                        applications.*,
                        jobs.title,
                        jobs.company,
                        jobs.location,
                        jobs.source_url,
                        jobs.score
                    FROM applications
                    JOIN jobs
                        ON jobs.id = applications.job_id
                    ORDER BY applications.updated_at DESC
                    """
                )

                return cur.fetchall()
