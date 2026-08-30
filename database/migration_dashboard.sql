-- ============================================================
-- Gunga Job Radar — Dashboard support migration
--
-- Run this ONCE in the Supabase SQL Editor against your
-- existing database. It is safe to run more than once
-- (everything is IF NOT EXISTS / OR REPLACE).
--
-- What this does:
--   1. Adds the columns the dashboard needs (eligibility,
--      employment_type, posted_date, applied, applied_at)
--   2. Turns on Row Level Security for the jobs table
--   3. Allows anyone with the public anon key to READ jobs
--      (needed for the dashboard to list them)
--   4. Adds a narrow RPC function that lets the anon key
--      toggle ONLY the applied/applied_at columns — it can't
--      touch score, tier, or anything else, and there is no
--      general UPDATE/DELETE policy, so nothing else is
--      writable from the browser.
-- ============================================================

ALTER TABLE jobs
  ADD COLUMN IF NOT EXISTS eligibility VARCHAR(30),
  ADD COLUMN IF NOT EXISTS employment_type VARCHAR(60),
  ADD COLUMN IF NOT EXISTS posted_date DATE,
  ADD COLUMN IF NOT EXISTS applied BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS applied_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_jobs_eligibility ON jobs(eligibility);
CREATE INDEX IF NOT EXISTS idx_jobs_applied ON jobs(applied);
CREATE INDEX IF NOT EXISTS idx_jobs_posted_date ON jobs(posted_date);

-- ------------------------------------------------------------
-- Row Level Security
-- ------------------------------------------------------------

ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Public read access" ON jobs;

CREATE POLICY "Public read access"
ON jobs
FOR SELECT
TO anon
USING (true);

-- No INSERT/UPDATE/DELETE policy is created for anon, so the
-- browser cannot write to the table directly at all — only
-- through the function below.

-- ------------------------------------------------------------
-- Narrow "mark applied" function
-- ------------------------------------------------------------

CREATE OR REPLACE FUNCTION mark_job_applied(
  p_job_id INTEGER,
  p_applied BOOLEAN
)
RETURNS void
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
  UPDATE jobs
  SET
    applied = p_applied,
    applied_at = CASE WHEN p_applied THEN NOW() ELSE NULL END
  WHERE id = p_job_id;
$$;

GRANT EXECUTE ON FUNCTION mark_job_applied(INTEGER, BOOLEAN) TO anon;
