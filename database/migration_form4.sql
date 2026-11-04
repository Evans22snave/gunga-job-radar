-- Migration: Form 4 category, location zones, Kenya-only cleanup.
-- Safe to run more than once. Run in Supabase -> SQL Editor.

-- 1. New columns -------------------------------------------------
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS category VARCHAR(10) NOT NULL DEFAULT 'ICT';
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS zone_rank SMALLINT NOT NULL DEFAULT 9;

CREATE INDEX IF NOT EXISTS idx_jobs_category ON jobs(category);
CREATE INDEX IF NOT EXISTS idx_jobs_zone_rank ON jobs(zone_rank);

-- 2. Backfill location zones (mirrors kenya_jobs.classify_zone) --
-- 0 Malindi/Kilifi, 1 rest of Coast, 2 Nairobi area, 3 Eldoret,
-- 4 Narok/Mara, 9 elsewhere. Location text first, then title.
UPDATE jobs SET zone_rank = LEAST(
    CASE
        WHEN COALESCE(location,'') ~* '\m(malindi|watamu|gede|kilifi|mtwapa|mariakani|kaloleni|ganze|magarini|mnarani|takaungu|vipingo|kikambala|rabai|kijipwa|marafa)\M' THEN 0
        WHEN COALESCE(location,'') ~* '\m(mombasa|likoni|nyali|bamburi|changamwe|kisauni|diani|ukunda|kwale|msambweni|lunga lunga|voi|taita|taveta|wundanyi|mwatate|lamu|tana river|garsen|hola|mazeras|shimba hills|kinango)\M' THEN 1
        WHEN COALESCE(location,'') ~* '\m(nairobi|kiambu|thika|ruiru|juja|kitengela|kajiado|machakos|athi river|ngong|rongai|limuru|kikuyu|karen|westlands|lavington|kileleshwa|upper hill|upperhill|industrial area|embakasi|syokimau|mlolongo|ruaka|kasarani|gigiri|runda|kilimani|parklands|langata|south b|south c|donholm|buruburu|eastleigh|ngara)\M' THEN 2
        WHEN COALESCE(location,'') ~* '\m(eldoret|uasin gishu|moi''s bridge|burnt forest)\M' THEN 3
        WHEN COALESCE(location,'') ~* '\m(narok|maasai mara|masai mara|talek|sekenani|ololulunga|kilgoris|aitong|mara north|mara south)\M' THEN 4
        ELSE 9
    END,
    CASE
        WHEN COALESCE(title,'') ~* '\m(malindi|watamu|gede|kilifi|mtwapa|mariakani|kaloleni|ganze|magarini|mnarani|takaungu|vipingo|kikambala|rabai|kijipwa|marafa)\M' THEN 0
        WHEN COALESCE(title,'') ~* '\m(mombasa|likoni|nyali|bamburi|changamwe|kisauni|diani|ukunda|kwale|msambweni|lunga lunga|voi|taita|taveta|wundanyi|mwatate|lamu|tana river|garsen|hola|mazeras|shimba hills|kinango)\M' THEN 1
        WHEN COALESCE(title,'') ~* '\m(nairobi|kiambu|thika|ruiru|juja|kitengela|kajiado|machakos|athi river|ngong|rongai|limuru|kikuyu|karen|westlands|lavington|kileleshwa|upper hill|upperhill|industrial area|embakasi|syokimau|mlolongo|ruaka|kasarani|gigiri|runda|kilimani|parklands|langata|south b|south c|donholm|buruburu|eastleigh|ngara)\M' THEN 2
        WHEN COALESCE(title,'') ~* '\m(eldoret|uasin gishu|moi''s bridge|burnt forest)\M' THEN 3
        WHEN COALESCE(title,'') ~* '\m(narok|maasai mara|masai mara|talek|sekenani|ololulunga|kilgoris|aitong|mara north|mara south)\M' THEN 4
        ELSE 9
    END
) WHERE zone_rank = 9;

-- NOTE: LEAST() above picks the nearer of location/title; the scanner
-- uses location first. The difference only matters for old rows.

-- 3. Remove remote jobs ------------------------------------------
-- Deletes remote / worldwide / restricted postings and everything
-- that came from the remote-only sources. Jobs you SAVED or APPLIED
-- to are kept (hidden by the dashboard) so no history is lost.
DELETE FROM jobs
WHERE saved IS NOT TRUE
  AND applied IS NOT TRUE
  AND (
        eligibility IN ('REMOTE-AFRICA', 'REMOTE-WORLDWIDE', 'REMOTE-RESTRICTED')
        OR source IN ('Himalayas', 'RemoteOK', 'We Work Remotely')
      );
