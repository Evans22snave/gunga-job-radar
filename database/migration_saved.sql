-- ============================================================
-- Gunga Job Radar — "Save for later" migration
--
-- Run this ONCE in the Supabase SQL Editor against your
-- existing database. It is safe to run more than once
-- (everything is IF NOT EXISTS / OR REPLACE).
--
-- What this does:
--   1. Adds saved / saved_at columns to jobs (same pattern as
--      the existing applied / applied_at columns)
--   2. Adds a narrow RPC function that lets the anon key
--      toggle ONLY the saved/saved_at columns — same security
--      model as mark_job_applied in migration_dashboard.sql.
--
-- Requires migration_dashboard.sql to have already been run
-- (it's what turns on Row Level Security and the public read
-- policy this depends on).
-- ============================================================

ALTER TABLE jobs
  ADD COLUMN IF NOT EXISTS saved BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS saved_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_jobs_saved ON jobs(saved);

-- ------------------------------------------------------------
-- Narrow "mark saved" function
-- ------------------------------------------------------------

CREATE OR REPLACE FUNCTION mark_job_saved(
  p_job_id INTEGER,
  p_saved BOOLEAN
)
RETURNS void
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
  UPDATE jobs
  SET
    saved = p_saved,
    saved_at = CASE WHEN p_saved THEN NOW() ELSE NULL END
  WHERE id = p_job_id;
$$;

GRANT EXECUTE ON FUNCTION mark_job_saved(INTEGER, BOOLEAN) TO anon;
