-- ============================================================
-- GUNGA JOB RADAR
-- DATABASE SCHEMA
-- ============================================================

-- ============================================================
-- JOBS
-- ============================================================

CREATE TABLE IF NOT EXISTS jobs (
    id SERIAL PRIMARY KEY,

    source TEXT NOT NULL,

    source_url TEXT NOT NULL UNIQUE,

    title TEXT NOT NULL,

    company TEXT,

    location TEXT,

    description TEXT,

    score INTEGER NOT NULL DEFAULT 0,

    tier TEXT,

    reasons TEXT,

    blockers TEXT,

    telegram_sent BOOLEAN NOT NULL DEFAULT FALSE,

    digested BOOLEAN NOT NULL DEFAULT FALSE,

    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- ============================================================
-- JOB SOURCES
-- ============================================================

CREATE TABLE IF NOT EXISTS job_sources (
    id SERIAL PRIMARY KEY,

    name TEXT NOT NULL UNIQUE,

    base_url TEXT,

    active BOOLEAN NOT NULL DEFAULT TRUE,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- ============================================================
-- NOTIFICATIONS
-- ============================================================

CREATE TABLE IF NOT EXISTS notifications (
    id SERIAL PRIMARY KEY,

    job_id INTEGER
        REFERENCES jobs(id)
        ON DELETE CASCADE,

    channel TEXT NOT NULL,

    status TEXT NOT NULL DEFAULT 'pending',

    attempts INTEGER NOT NULL DEFAULT 0,

    last_error TEXT,

    sent_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- ============================================================
-- SAVED JOBS
-- ============================================================

CREATE TABLE IF NOT EXISTS saved_jobs (
    id SERIAL PRIMARY KEY,

    job_id INTEGER NOT NULL
        REFERENCES jobs(id)
        ON DELETE CASCADE,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(job_id)
);


-- ============================================================
-- APPLICATIONS
-- ============================================================

CREATE TABLE IF NOT EXISTS applications (
    id SERIAL PRIMARY KEY,

    job_id INTEGER NOT NULL
        REFERENCES jobs(id)
        ON DELETE CASCADE,

    status TEXT NOT NULL DEFAULT 'saved',

    applied_at TIMESTAMPTZ,

    interview_at TIMESTAMPTZ,

    notes TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(job_id)
);


-- ============================================================
-- JOB MATCHES
-- ============================================================

CREATE TABLE IF NOT EXISTS job_matches (
    id SERIAL PRIMARY KEY,

    job_id INTEGER NOT NULL
        REFERENCES jobs(id)
        ON DELETE CASCADE,

    score INTEGER NOT NULL DEFAULT 0,

    tier TEXT,

    matched_skills TEXT,

    matched_locations TEXT,

    reasons TEXT,

    blockers TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(job_id)
);


-- ============================================================
-- INDEXES
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_jobs_score
ON jobs(score DESC);

CREATE INDEX IF NOT EXISTS idx_jobs_location
ON jobs(location);

CREATE INDEX IF NOT EXISTS idx_jobs_source
ON jobs(source);

CREATE INDEX IF NOT EXISTS idx_jobs_fetched_at
ON jobs(fetched_at DESC);

CREATE INDEX IF NOT EXISTS idx_jobs_tier
ON jobs(tier);

CREATE INDEX IF NOT EXISTS idx_jobs_telegram_sent
ON jobs(telegram_sent);

CREATE INDEX IF NOT EXISTS idx_jobs_digested
ON jobs(digested);

CREATE INDEX IF NOT EXISTS idx_notifications_status
ON notifications(status);

CREATE INDEX IF NOT EXISTS idx_notifications_channel
ON notifications(channel);

CREATE INDEX IF NOT EXISTS idx_applications_status
ON applications(status);


-- ============================================================
-- UPDATED_AT FUNCTION
-- ============================================================

CREATE OR REPLACE FUNCTION
update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN

    NEW.updated_at = NOW();

    RETURN NEW;

END;
$$ LANGUAGE plpgsql;


-- ============================================================
-- JOB TRIGGER
-- ============================================================

DROP TRIGGER IF EXISTS
jobs_updated_at
ON jobs;

CREATE TRIGGER
jobs_updated_at

BEFORE UPDATE ON jobs

FOR EACH ROW

EXECUTE FUNCTION
update_updated_at_column();


-- ============================================================
-- NOTIFICATION TRIGGER
-- ============================================================

DROP TRIGGER IF EXISTS
notifications_updated_at
ON notifications;

CREATE TRIGGER
notifications_updated_at

BEFORE UPDATE ON notifications

FOR EACH ROW

EXECUTE FUNCTION
update_updated_at_column();


-- ============================================================
-- APPLICATION TRIGGER
-- ============================================================

DROP TRIGGER IF EXISTS
applications_updated_at
ON applications;

CREATE TRIGGER
applications_updated_at

BEFORE UPDATE ON applications

FOR EACH ROW

EXECUTE FUNCTION
update_updated_at_column();


-- ============================================================
-- DEFAULT SOURCE
-- ============================================================

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
    source TEXT NOT NULL,

    source_url TEXT NOT NULL UNIQUE,

    title TEXT NOT NULL,

    company TEXT,

    location TEXT,

    description TEXT,

    employment_type TEXT,

    salary TEXT,

    category TEXT,

    published_at TIMESTAMPTZ,

    deadline TIMESTAMPTZ,

    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    score INTEGER NOT NULL DEFAULT 0,

    tier TEXT,

    reasons TEXT,

    blockers TEXT,

    matched_skills TEXT,

    matched_locations TEXT,

    telegram_sent BOOLEAN NOT NULL DEFAULT FALSE,

    email_sent BOOLEAN NOT NULL DEFAULT FALSE,

    digested BOOLEAN NOT NULL DEFAULT FALSE,

    is_active BOOLEAN NOT NULL DEFAULT TRUE
);


-- ============================================================
-- JOB MATCHES
-- ============================================================

CREATE TABLE IF NOT EXISTS job_matches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    job_id UUID NOT NULL
        REFERENCES jobs(id)
        ON DELETE CASCADE,

    score INTEGER NOT NULL DEFAULT 0,

    tier TEXT,

    matched_skills TEXT,

    matched_locations TEXT,

    reasons TEXT,

    blockers TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(job_id)
);


-- ============================================================
-- NOTIFICATIONS
-- ============================================================

CREATE TABLE IF NOT EXISTS notifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    job_id UUID
        REFERENCES jobs(id)
        ON DELETE CASCADE,

    channel TEXT NOT NULL,

    status TEXT NOT NULL DEFAULT 'pending',

    attempts INTEGER NOT NULL DEFAULT 0,

    last_error TEXT,

    sent_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- ============================================================
-- SAVED JOBS
-- ============================================================

CREATE TABLE IF NOT EXISTS saved_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    job_id UUID NOT NULL
        REFERENCES jobs(id)
        ON DELETE CASCADE,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(job_id)
);


-- ============================================================
-- APPLICATIONS
-- ============================================================

CREATE TABLE IF NOT EXISTS applications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    job_id UUID NOT NULL
        REFERENCES jobs(id)
        ON DELETE CASCADE,

    status TEXT NOT NULL DEFAULT 'saved',

    applied_at TIMESTAMPTZ,

    interview_at TIMESTAMPTZ,

    notes TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(job_id)
);


-- ============================================================
-- INDEXES
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_jobs_score
ON jobs(score DESC);

CREATE INDEX IF NOT EXISTS idx_jobs_location
ON jobs(location);

CREATE INDEX IF NOT EXISTS idx_jobs_source
ON jobs(source);

CREATE INDEX IF NOT EXISTS idx_jobs_source_id
ON jobs(source_id);

CREATE INDEX IF NOT EXISTS idx_jobs_fetched_at
ON jobs(fetched_at DESC);

CREATE INDEX IF NOT EXISTS idx_jobs_published_at
ON jobs(published_at DESC);

CREATE INDEX IF NOT EXISTS idx_jobs_deadline
ON jobs(deadline);

CREATE INDEX IF NOT EXISTS idx_jobs_active
ON jobs(is_active);

CREATE INDEX IF NOT EXISTS idx_jobs_tier
ON jobs(tier);

CREATE INDEX IF NOT EXISTS idx_notifications_status
ON notifications(status);

CREATE INDEX IF NOT EXISTS idx_notifications_channel
ON notifications(channel);

CREATE INDEX IF NOT EXISTS idx_applications_status
ON applications(status);


-- ============================================================
-- INITIAL JOB SOURCE
-- ============================================================

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


-- ============================================================
-- AUTOMATIC UPDATED_AT FUNCTION
-- ============================================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;


-- ============================================================
-- JOBS UPDATED_AT TRIGGER
-- ============================================================

DROP TRIGGER IF EXISTS jobs_updated_at
ON jobs;

CREATE TRIGGER jobs_updated_at
BEFORE UPDATE ON jobs
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();


-- ============================================================
-- NOTIFICATIONS UPDATED_AT TRIGGER
-- ============================================================

DROP TRIGGER IF EXISTS notifications_updated_at
ON notifications;

CREATE TRIGGER notifications_updated_at
BEFORE UPDATE ON notifications
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();


-- ============================================================
-- APPLICATIONS UPDATED_AT TRIGGER
-- ============================================================

DROP TRIGGER IF EXISTS applications_updated_at
ON applications;

CREATE TRIGGER applications_updated_at
BEFORE UPDATE ON applications
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();
