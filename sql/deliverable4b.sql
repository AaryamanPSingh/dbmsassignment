-- ============================================================================
-- DBMS Lab End-Sem — Deliverable 4b (optional): the value of a new install
--
-- Run with:  python3 scripts/run_deliverable4b.py
--
-- Brief (section 4b): predict how much revenue a new install will generate in
-- its first 90 days using only what is known by the end of day 7. UA would
-- use the ranking to decide how much to bid for an install, so ORDER matters
-- more than the average error.
--
-- The hard part is not the model, it is who can be labelled at all. The
-- extract is 2026-01-01..2026-04-30 (120 days), so a complete 90-day outcome
-- requires install_date <= 2026-01-30, and complete first-week features
-- require install_date >= 2026-01-01.
--
-- DEFINITION (used by every section below):
--   Population  installs with install_date in [2026-01-01, 2026-01-30].
--               Excluded and why:
--                 * 16,000 installs before 2026-01-01: their days 0-6 are
--                   outside the extract, so the features are unobservable.
--                 * 54,801 installs after 2026-01-30: their days 60-89 are
--                   after 2026-04-30, so revenue_90 is right-censored.
--   Features    only days 0-6 after install (never day 7+).
--   revenue_90  gross IAP revenue over days 0-89 after install: positive,
--               deduplicated usd_amount (D3, D2).
--   payer_90    1 iff revenue_90 > 0.
--   Split       train      2026-01-01..2026-01-14
--               validation 2026-01-15..2026-01-20  (L2 selection only)
--               test       2026-01-21..2026-01-30  (untouched, out of time)
--
-- Conventions D1-D4 are unchanged from deliverables 1-4a.
-- ============================================================================

-- @setup
DROP TABLE IF EXISTS purchase_dedup;
DROP TABLE IF EXISTS ad_local;
DROP TABLE IF EXISTS d4b_installs;
DROP TABLE IF EXISTS d4b_cohort;

-- D1 + D2: deduplicated purchases with normalised dates
CREATE TEMP TABLE purchase_dedup AS
WITH ranked AS (
    SELECT p.*,
           ROW_NUMBER() OVER (PARTITION BY purchase_id ORDER BY event_ts) AS rn
    FROM purchase p
)
SELECT purchase_id,
       device_id,
       event_ts,
       CAST(strftime('%Y%m%d', DATE(event_ts)) AS INT) AS tx_date,
       DATE(event_ts)                                   AS tx_dstr,
       pack_name,
       usd_amount,
       currency_granted,
       sale_flag
FROM ranked
WHERE rn = 1;
CREATE INDEX idx_d4b_pur_dev ON purchase_dedup(device_id, tx_date);

-- D4: active device-days (player_day UNION positive-purchase days)
CREATE TEMP TABLE active_days AS
SELECT device_id, activity_date AS day_id FROM player_day
UNION
SELECT device_id, tx_date FROM purchase_dedup WHERE usd_amount > 0;
CREATE INDEX idx_d4b_act ON active_days(device_id, day_id);

-- D5: ad interactions on local (game) dates
CREATE TEMP TABLE ad_local AS
SELECT device_id,
       DATE(event_ts, '-8 hours')              AS local_date,
       CAST(strftime('%Y%m%d', DATE(event_ts, '-8 hours')) AS INT) AS local_day,
       status,
       ad_daily_count,
       ad_daily_cap
FROM ad_view;
CREATE INDEX idx_d4b_ad ON ad_local(device_id, local_day);


-- @4b_base_build
-- The labelable population and its split. Day 0 is the install date; the
-- feature window is days 0-6 and the label window days 0-89.
CREATE TEMP TABLE d4b_installs AS
SELECT device_id,
       install_date,
       platform,
       country_tier,
       acquisition_channel,
       CAST(REPLACE(install_date, '-', '') AS INT)                          AS install_day,
       CAST(strftime('%Y%m%d', DATE(install_date, '+6 days'))  AS INT)     AS d7_end,
       CAST(strftime('%Y%m%d', DATE(install_date, '+89 days')) AS INT)     AS d90_end,
       CASE
           WHEN install_date BETWEEN '2026-01-01' AND '2026-01-14' THEN 'train'
           WHEN install_date BETWEEN '2026-01-15' AND '2026-01-20' THEN 'validation'
           ELSE 'test'
       END                                                                 AS split
FROM player_profile
WHERE install_date BETWEEN '2026-01-01' AND '2026-01-30';
CREATE INDEX idx_d4b_inst_device ON d4b_installs(device_id);
CREATE INDEX idx_d4b_inst_split ON d4b_installs(split, install_day);


-- @4b_cohort_build
-- One row per labelable install. Every feature comes from the player's days
-- 0-6 only; revenue_90 comes from days 0-89. revenue_7 is kept for the
-- baseline and the "how much is already known by day 7" diagnostic.
DROP TABLE IF EXISTS d4b_cohort;
CREATE TEMP TABLE d4b_cohort AS
WITH rev AS (
    SELECT b.device_id,
           SUM(CASE WHEN p.tx_date BETWEEN b.install_day AND b.d90_end
                    THEN p.usd_amount ELSE 0 END)                    AS revenue_90,
           SUM(CASE WHEN p.tx_date BETWEEN b.install_day AND b.d7_end
                    THEN p.usd_amount ELSE 0 END)                    AS revenue_7,
           SUM(CASE WHEN p.tx_date BETWEEN b.install_day AND b.d7_end
                    THEN 1 ELSE 0 END)                               AS purchases_7,
           MIN(CASE WHEN p.tx_date BETWEEN b.install_day AND b.d7_end
                    THEN p.tx_date END)                              AS first_purchase_day_7
    FROM d4b_installs b
    JOIN purchase_dedup p
      ON p.device_id = b.device_id
     AND p.tx_date BETWEEN b.install_day AND b.d90_end
     AND p.usd_amount > 0
    GROUP BY b.device_id
),
act AS (
    -- D4 active days: player_day union positive-purchase days.
    SELECT b.device_id, COUNT(*) AS active_days_7
    FROM d4b_installs b
    JOIN active_days a
      ON a.device_id = b.device_id
     AND a.day_id BETWEEN b.install_day AND b.d7_end
    GROUP BY b.device_id
),
pd AS (
    SELECT b.device_id,
           COUNT(*)                 AS recorded_days_7,
           SUM(pd.session_count)    AS sessions_7,
           SUM(pd.playtime_minutes) AS playtime_7,
           MAX(pd.player_level)     AS level_last_7
    FROM d4b_installs b
    JOIN player_day pd
      ON pd.device_id = b.device_id
     AND pd.activity_date BETWEEN b.install_day AND b.d7_end
    GROUP BY b.device_id
),
ads AS (
    SELECT b.device_id,
           COUNT(*)                    AS ads_completed_7,
           COUNT(DISTINCT a.local_day) AS ad_days_7
    FROM d4b_installs b
    JOIN ad_local a
      ON a.device_id = b.device_id
     AND a.local_day BETWEEN b.install_day AND b.d7_end
    WHERE a.status = 'completed'
    GROUP BY b.device_id
),
cs AS (
    -- In-game currency spend events in the first week. event_ts is already
    -- local for in-game events (D5's -8h shift applies to ad_view only).
    SELECT b.device_id,
           SUM(CASE WHEN s.currency_type = 'PREMIUM' THEN 1 ELSE 0 END) AS cs_premium_7,
           SUM(CASE WHEN s.currency_type = 'SOCIAL'  THEN 1 ELSE 0 END) AS cs_social_7,
           SUM(CASE WHEN s.currency_type = 'GRIND'   THEN 1 ELSE 0 END) AS cs_grind_7,
           SUM(s.currency_value)                                        AS cs_value_7
    FROM d4b_installs b
    JOIN currency_spend s
      ON s.device_id = b.device_id
     AND CAST(strftime('%Y%m%d', DATE(s.event_ts)) AS INT)
         BETWEEN b.install_day AND b.d7_end
    GROUP BY b.device_id
)
SELECT b.device_id,
       b.install_date,
       b.split,
       b.install_day,
       b.platform,
       b.country_tier,
       b.acquisition_channel,
       COALESCE(r.revenue_90, 0)                                        AS revenue_90,
       CASE WHEN COALESCE(r.revenue_90, 0) > 0 THEN 1 ELSE 0 END        AS payer_90,
       COALESCE(r.revenue_7, 0)                                         AS revenue_7,
       COALESCE(r.purchases_7, 0)                                       AS purchases_7,
       CASE WHEN COALESCE(r.purchases_7, 0) > 0 THEN 1 ELSE 0 END       AS first_week_payer,
       CASE WHEN r.first_purchase_day_7 IS NULL THEN 7
            ELSE r.first_purchase_day_7 - b.install_day END             AS days_to_first_purchase,
       COALESCE(a.active_days_7, 0)                                     AS active_days_7,
       COALESCE(p.recorded_days_7, 0)                                   AS recorded_days_7,
       COALESCE(p.sessions_7, 0)                                        AS sessions_7,
       ROUND(COALESCE(p.playtime_7, 0), 1)                              AS playtime_7,
       COALESCE(p.level_last_7, 0)                                      AS level_last_7,
       COALESCE(ad.ads_completed_7, 0)                                  AS ads_completed_7,
       COALESCE(ad.ad_days_7, 0)                                        AS ad_days_7,
       COALESCE(c.cs_premium_7, 0)                                      AS cs_premium_7,
       COALESCE(c.cs_social_7, 0)                                       AS cs_social_7,
       COALESCE(c.cs_grind_7, 0)                                        AS cs_grind_7,
       COALESCE(c.cs_value_7, 0)                                        AS cs_value_7
FROM d4b_installs b
LEFT JOIN rev r ON r.device_id = b.device_id
LEFT JOIN act a ON a.device_id = b.device_id
LEFT JOIN pd  p ON p.device_id = b.device_id
LEFT JOIN ads ad ON ad.device_id = b.device_id
LEFT JOIN cs  c ON c.device_id = b.device_id;


-- @4b_cohort
SELECT * FROM d4b_cohort ORDER BY install_day, device_id;


-- @4b_cohort_profile
-- Descriptive profile of the labelable cohort: the honest view of who this
-- model can be fitted on, and how it differs from the full extract.
SELECT 'all' AS cut, 'all' AS value, COUNT(*) AS n, SUM(payer_90) AS payers,
       ROUND(100.0 * SUM(payer_90) / COUNT(*), 2) AS payer_rate_pct,
       ROUND(AVG(revenue_90), 2) AS mean_rev_90,
       ROUND(AVG(revenue_7), 2)  AS mean_rev_7
FROM d4b_cohort
UNION ALL
SELECT 'split', split, COUNT(*), SUM(payer_90),
       ROUND(100.0 * SUM(payer_90) / COUNT(*), 2),
       ROUND(AVG(revenue_90), 2), ROUND(AVG(revenue_7), 2)
FROM d4b_cohort GROUP BY split
UNION ALL
SELECT 'acquisition_channel', acquisition_channel, COUNT(*), SUM(payer_90),
       ROUND(100.0 * SUM(payer_90) / COUNT(*), 2),
       ROUND(AVG(revenue_90), 2), ROUND(AVG(revenue_7), 2)
FROM d4b_cohort GROUP BY acquisition_channel
UNION ALL
SELECT 'country_tier', CAST(country_tier AS TEXT), COUNT(*), SUM(payer_90),
       ROUND(100.0 * SUM(payer_90) / COUNT(*), 2),
       ROUND(AVG(revenue_90), 2), ROUND(AVG(revenue_7), 2)
FROM d4b_cohort GROUP BY country_tier
UNION ALL
SELECT 'platform', platform, COUNT(*), SUM(payer_90),
       ROUND(100.0 * SUM(payer_90) / COUNT(*), 2),
       ROUND(AVG(revenue_90), 2), ROUND(AVG(revenue_7), 2)
FROM d4b_cohort GROUP BY platform
ORDER BY cut, value;


-- @checks_d4b
-- Reconciliation, window and leakage guards. Each row is (check, observed,
-- expected); the Python script fails loudly if any observed != expected.
SELECT '1 labelable population matches an independent count' AS check_item,
       CAST((SELECT COUNT(*) FROM d4b_cohort) AS TEXT) || ' / ' ||
       CAST((SELECT COUNT(*) FROM player_profile
             WHERE install_date BETWEEN '2026-01-01' AND '2026-01-30') AS TEXT) AS observed,
       'equal' AS expected
UNION ALL
SELECT '2 one row per device',
       CAST((SELECT COUNT(*) FROM (SELECT device_id FROM d4b_cohort
                                   GROUP BY device_id HAVING COUNT(*) > 1)) AS TEXT),
       '0'
UNION ALL
SELECT '3 every install is inside the labelable window',
       CAST((SELECT COUNT(*) FROM d4b_cohort
             WHERE install_date < '2026-01-01' OR install_date > '2026-01-30') AS TEXT),
       '0'
UNION ALL
SELECT '4 every feature/label window is inside the extract',
       CAST((SELECT COUNT(*) FROM d4b_cohort
             WHERE install_day < 20260101 OR install_day + 89 > 20260430) AS TEXT),
       '0'
UNION ALL
SELECT '5 no NULLs in model features',
       CAST((SELECT COUNT(*) FROM d4b_cohort
             WHERE revenue_90 IS NULL OR payer_90 IS NULL
                OR revenue_7 IS NULL OR purchases_7 IS NULL
                OR first_week_payer IS NULL OR days_to_first_purchase IS NULL
                OR active_days_7 IS NULL OR recorded_days_7 IS NULL
                OR sessions_7 IS NULL OR playtime_7 IS NULL
                OR level_last_7 IS NULL OR ads_completed_7 IS NULL
                OR ad_days_7 IS NULL OR cs_premium_7 IS NULL
                OR cs_social_7 IS NULL OR cs_grind_7 IS NULL) AS TEXT),
       '0'
UNION ALL
SELECT '6 revenue_90 recomputed by an independent query',
       CAST(ROUND((SELECT SUM(revenue_90) FROM d4b_cohort), 0) AS TEXT) || ' / ' ||
       CAST(ROUND((SELECT SUM(p.usd_amount)
                   FROM purchase_dedup p
                   JOIN d4b_installs b ON b.device_id = p.device_id
                   WHERE p.usd_amount > 0
                     AND p.tx_date BETWEEN b.install_day AND b.d90_end), 0) AS TEXT),
       'equal'
UNION ALL
SELECT '7 split order is strictly temporal (train < validation < test)',
       (SELECT MAX(install_date) FROM d4b_cohort WHERE split = 'train')
       || ' < ' ||
       (SELECT MIN(install_date) FROM d4b_cohort WHERE split = 'validation')
       || ' < ' ||
       (SELECT MAX(install_date) FROM d4b_cohort WHERE split = 'validation')
       || ' < ' ||
       (SELECT MIN(install_date) FROM d4b_cohort WHERE split = 'test'),
       'true'
UNION ALL
SELECT '8 first-week revenue never exceeds 90-day revenue',
       CAST((SELECT COUNT(*) FROM d4b_cohort WHERE revenue_7 > revenue_90 + 1e-9) AS TEXT),
       '0'
UNION ALL
SELECT '9 labelable + excluded = in-window installs',
       CAST((SELECT COUNT(*) FROM d4b_cohort) AS TEXT) || ' + ' ||
       CAST((SELECT COUNT(*) FROM player_profile
             WHERE install_date > '2026-01-30'
               AND install_date <= '2026-04-30') AS TEXT) || ' = ' ||
       CAST((SELECT COUNT(*) FROM player_profile
             WHERE install_date BETWEEN '2026-01-01' AND '2026-04-30') AS TEXT),
       CAST((SELECT COUNT(*) FROM player_profile
             WHERE install_date BETWEEN '2026-01-01' AND '2026-04-30') AS TEXT)
UNION ALL
SELECT '10 feature window ends at day 6; label window ends at day 89',
       CAST((SELECT COUNT(*) FROM d4b_installs
             WHERE d7_end <> CAST(strftime('%Y%m%d', DATE(install_date, '+6 days')) AS INT)
                OR d90_end <> CAST(strftime('%Y%m%d', DATE(install_date, '+89 days')) AS INT)) AS TEXT),
       '0'
ORDER BY check_item;
