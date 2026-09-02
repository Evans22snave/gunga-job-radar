-- ============================================================
-- Gunga Job Radar — Deadline tracking migration
--
-- Run this ONCE in the Supabase SQL Editor. Safe to run more
-- than once (IF NOT EXISTS).
-- ============================================================

ALTER TABLE jobs
  ADD COLUMN IF NOT EXISTS deadline_date DATE;

CREATE INDEX IF NOT EXISTS idx_jobs_deadline_date ON jobs(deadline_date);
