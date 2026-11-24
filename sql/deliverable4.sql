-- ============================================================================
-- DBMS Lab End-Sem — Deliverable 4a: Predict 14-day churn
--
-- Run with:  python3 scripts/run_deliverable4.py
--
-- Brief (section 4): predict which CURRENTLY ACTIVE players will stop playing
-- in the next 14 days. The live-ops team will spend a re-engagement offer on
-- the players we flag, so the write-up must expose how many flagged players
-- would have been wasted, and how the threshold depends on offer cost vs the
-- value of a retained player.
--
-- Conventions carried over unchanged from deliverables 1-3:
--   D1  event_ts zero-padded at load time
--   D2  purchases deduplicated by purchase_id
--   D3  gross revenue = positive usd_amount on deduplicated rows
--   D4  active = player_day row OR a positive purchase that day
--   D5  ad_view shifted -8h to local dates
--
-- DEFINITION (stated once, used everywhere):
--   Snapshot t   a date on which the player is active. All features use data
--                in the 14-day window [t-13, t] or earlier; the label uses
--                only (t, t+14].
--   Churn14     1 iff the player has NO active day in [t+1, t+14].
--   Eligible    every player active on t whose install_date <= t. There is
--                no minimum tenure: pre-install days in the feature window
--                are genuine zeros, and tenure_days is itself a feature.
--                Players active before install_date are a data artefact and
--                are excluded (9 rows in the Apr-08 snapshot; 0 elsewhere).
--   Snapshots   four 28-day-spaced dates, so feature/outcome windows do not
--                overlap: 2026-01-14, 02-11, 03-11, 04-08.
--   Split       train = Jan-14 + Feb-11; validation = Mar-11 (L2 selection
--                only); test = Apr-08 (untouched final, out of time).
-- ============================================================================

-- @setup
DROP TABLE IF EXISTS purchase_dedup;
DROP TABLE IF EXISTS active_days;
DROP TABLE IF EXISTS ad_local;
DROP TABLE IF EXISTS d4_snapshots;

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
CREATE INDEX idx_d4_pur_dev ON purchase_dedup(device_id, tx_date);
CREATE INDEX idx_d4_pur_tx ON purchase_dedup(tx_date);

-- D4: active device-days (player_day UNION positive-purchase days)
CREATE TEMP TABLE active_days AS
SELECT device_id, activity_date AS day_id FROM player_day
UNION
SELECT device_id, tx_date FROM purchase_dedup WHERE usd_amount > 0;
CREATE INDEX idx_d4_act ON active_days(device_id, day_id);
CREATE INDEX idx_d4_act_day ON active_days(day_id);

-- D5: ad interactions on local (game) dates
CREATE TEMP TABLE ad_local AS
SELECT device_id,
       DATE(event_ts, '-8 hours')              AS local_date,
       CAST(strftime('%Y%m%d', DATE(event_ts, '-8 hours')) AS INT) AS local_day,
       status,
       ad_daily_count,
       ad_daily_cap
FROM ad_view;
CREATE INDEX idx_d4_ad ON ad_local(device_id, local_day);

-- Snapshot calendar. Integer YYYYMMDD is convenient for joins; date strings
-- are used only for SQLite date arithmetic (it rejects bare YYYYMMDD).
CREATE TEMP TABLE d4_snapshots AS
WITH s(snapshot_date, split) AS (
    VALUES ('2026-01-14', 'train'),
           ('2026-02-11', 'train'),
           ('2026-03-11', 'validation'),
           ('2026-04-08', 'test')
)
SELECT snapshot_date,
       split,
       CAST(REPLACE(snapshot_date, '-', '') AS INT)                  AS snapshot_day,
       CAST(strftime('%Y%m%d', DATE(snapshot_date, '-13 days')) AS INT) AS d14_start,
       CAST(strftime('%Y%m%d', DATE(snapshot_date,  '-6 days')) AS INT) AS d7_start,
       CAST(strftime('%Y%m%d', DATE(snapshot_date, '-13 days')) AS INT) AS prev7_start,
       CAST(strftime('%Y%m%d', DATE(snapshot_date,  '+1 day'))  AS INT) AS outcome_start,
       CAST(strftime('%Y%m%d', DATE(snapshot_date, '+14 days')) AS INT) AS outcome_end
FROM s;


-- @4a_snapshots
-- Design table: window dates, raw active count, exclusions, eligible rows and
-- the observed 14-day churn rate in each snapshot.
WITH base_raw AS (
    SELECT s.snapshot_date, s.split, s.snapshot_day,
           p.device_id, p.install_date,
           CAST(julianday(s.snapshot_date) - julianday(DATE(p.install_date)) AS INT) AS tenure_days
    FROM d4_snapshots s
    JOIN active_days a ON a.day_id = s.snapshot_day
    JOIN player_profile p USING (device_id)
),
future AS (
    SELECT b.snapshot_day, b.device_id,
           EXISTS (SELECT 1 FROM active_days f
                   WHERE f.device_id = b.device_id
                     AND f.day_id BETWEEN s.outcome_start AND s.outcome_end) AS active_future
    FROM base_raw b JOIN d4_snapshots s USING (snapshot_day)
)
SELECT b.snapshot_date,
       b.split,
       b.snapshot_day,
       s.d14_start,
       s.snapshot_day                                      AS d14_end,
       s.outcome_start,
       s.outcome_end,
       COUNT(*)                                            AS active_on_snapshot,
       SUM(CASE WHEN b.tenure_days < 0 THEN 1 ELSE 0 END)  AS excluded_active_before_install,
       SUM(CASE WHEN b.tenure_days >= 0 THEN 1 ELSE 0 END) AS eligible,
       SUM(CASE WHEN b.tenure_days >= 0 AND f.active_future = 0 THEN 1 ELSE 0 END) AS churners,
       ROUND(100.0 * SUM(CASE WHEN b.tenure_days >= 0 AND f.active_future = 0 THEN 1 ELSE 0 END)
             / SUM(CASE WHEN b.tenure_days >= 0 THEN 1 ELSE 0 END), 2) AS churn_rate_pct
FROM base_raw b
JOIN d4_snapshots s USING (snapshot_day)
JOIN future f ON f.snapshot_day = b.snapshot_day AND f.device_id = b.device_id
GROUP BY b.snapshot_date, b.split, b.snapshot_day, s.d14_start,
         s.snapshot_day, s.outcome_start, s.outcome_end
ORDER BY b.snapshot_day;


-- @4a_model_dataset_build
-- One row per eligible player-snapshot. Every feature is computed from
-- [snapshot-13, snapshot] or earlier; churn14 uses only (snapshot, snapshot+14].
DROP TABLE IF EXISTS d4_model_dataset;
CREATE TEMP TABLE d4_model_dataset AS
WITH base AS (
    SELECT s.snapshot_date,
           s.split,
           s.snapshot_day,
           p.device_id,
           p.install_date,
           p.platform,
           p.country_tier,
           p.acquisition_channel,
           CAST(julianday(s.snapshot_date) - julianday(DATE(p.install_date)) AS INT) AS tenure_days,
           s.d14_start,
           s.d7_start,
           s.prev7_start,
           s.outcome_start,
           s.outcome_end
    FROM d4_snapshots s
    JOIN active_days a ON a.day_id = s.snapshot_day
    JOIN player_profile p USING (device_id)
    WHERE p.install_date IS NOT NULL
      AND p.install_date <= s.snapshot_date          -- no post-snapshot info
),
act AS (
    SELECT b.snapshot_day, b.device_id,
           COUNT(*)                                                       AS active_days_14,
           SUM(CASE WHEN a.day_id >= b.d7_start THEN 1 ELSE 0 END)        AS active_days_7,
           SUM(CASE WHEN a.day_id <  b.d7_start THEN 1 ELSE 0 END)        AS active_days_prev7
    FROM base b
    JOIN active_days a
      ON a.device_id = b.device_id
     AND a.day_id BETWEEN b.d14_start AND b.snapshot_day
    GROUP BY b.snapshot_day, b.device_id
),
pd AS (
    -- player_day rows only. Purchase-only active days have no recorded
    -- playtime, so they contribute 0 to playtime/sessions (same denominator
    -- convention as D1/D3) but still count in active_days above.
    SELECT b.snapshot_day, b.device_id,
           COUNT(*)                                                        AS recorded_days_14,
           SUM(pd.session_count)                                           AS sessions_14,
           SUM(CASE WHEN pd.activity_date >= b.d7_start THEN pd.session_count ELSE 0 END) AS sessions_7,
           SUM(CASE WHEN pd.activity_date <  b.d7_start THEN pd.session_count ELSE 0 END) AS sessions_prev7,
           SUM(pd.playtime_minutes)                                        AS playtime_14,
           SUM(CASE WHEN pd.activity_date >= b.d7_start THEN pd.playtime_minutes ELSE 0 END) AS playtime_7,
           SUM(CASE WHEN pd.activity_date <  b.d7_start THEN pd.playtime_minutes ELSE 0 END) AS playtime_prev7,
           MAX(pd.player_level)                                            AS level_last
    FROM base b
    JOIN player_day pd
      ON pd.device_id = b.device_id
     AND pd.activity_date BETWEEN b.d14_start AND b.snapshot_day
    GROUP BY b.snapshot_day, b.device_id
),
pur AS (
    SELECT b.snapshot_day, b.device_id,
           SUM(CASE WHEN p.tx_date <= b.snapshot_day THEN p.usd_amount ELSE 0 END) AS spend_lifetime,
           SUM(CASE WHEN p.tx_date BETWEEN b.d14_start AND b.snapshot_day
                    THEN p.usd_amount ELSE 0 END)                                 AS spend_14,
           SUM(CASE WHEN p.tx_date BETWEEN b.d14_start AND b.snapshot_day
                    THEN 1 ELSE 0 END)                                            AS purchases_14,
           MAX(CASE WHEN p.tx_date <= b.snapshot_day THEN p.tx_dstr END)          AS last_purchase_date
    FROM base b
    JOIN purchase_dedup p
      ON p.device_id = b.device_id
     AND p.tx_date <= b.snapshot_day
     AND p.usd_amount > 0
    GROUP BY b.snapshot_day, b.device_id
),
ads AS (
    SELECT b.snapshot_day, b.device_id,
           COUNT(*)                 AS ads_completed_14,
           COUNT(DISTINCT a.local_day) AS ad_days_14
    FROM base b
    JOIN ad_local a
      ON a.device_id = b.device_id
     AND a.local_day BETWEEN b.d14_start AND b.snapshot_day
    WHERE a.status = 'completed'
    GROUP BY b.snapshot_day, b.device_id
),
future AS (
    SELECT b.snapshot_day, b.device_id,
           CASE WHEN COUNT(f.day_id) = 0 THEN 1 ELSE 0 END AS churn14
    FROM base b
    LEFT JOIN active_days f
      ON f.device_id = b.device_id
     AND f.day_id BETWEEN b.outcome_start AND b.outcome_end
    GROUP BY b.snapshot_day, b.device_id
)
SELECT b.snapshot_date,
       b.split,
       b.snapshot_day,
       b.device_id,
       f.churn14,
       b.tenure_days,
       COALESCE(pd.level_last, 0)                                        AS level_last,
       CASE WHEN pd.level_last IS NULL THEN 0 ELSE 1 END                 AS has_level,
       b.platform,
       b.country_tier,
       b.acquisition_channel,
       act.active_days_14,
       act.active_days_7,
       act.active_days_prev7,
       act.active_days_7 - act.active_days_prev7                         AS active_days_delta,
       COALESCE(pd.recorded_days_14, 0)                                  AS recorded_days_14,
       COALESCE(pd.sessions_7, 0)                                        AS sessions_7,
       COALESCE(pd.sessions_prev7, 0)                                    AS sessions_prev7,
       COALESCE(pd.sessions_7, 0) - COALESCE(pd.sessions_prev7, 0)       AS sessions_delta,
       ROUND(COALESCE(pd.playtime_7, 0), 1)                              AS playtime_7,
       ROUND(COALESCE(pd.playtime_prev7, 0), 1)                          AS playtime_prev7,
       ROUND(COALESCE(pd.playtime_7, 0) - COALESCE(pd.playtime_prev7, 0), 1) AS playtime_delta,
       ROUND(COALESCE(pd.playtime_14, 0) * 1.0 / act.active_days_14, 2)  AS playtime_per_active_day,
       ROUND(COALESCE(pd.sessions_14, 0) * 1.0 / act.active_days_14, 3)  AS sessions_per_active_day,
       ROUND(COALESCE(ads.ads_completed_14, 0) * 1.0 / act.active_days_14, 3) AS ads_per_active_day,
       COALESCE(pur.spend_lifetime, 0)                                   AS spend_lifetime,
       COALESCE(pur.spend_14, 0)                                         AS spend_14,
       COALESCE(pur.purchases_14, 0)                                     AS purchases_14,
       CASE WHEN COALESCE(pur.spend_lifetime, 0) > 0 THEN 1 ELSE 0 END   AS ever_payer,
       CASE
           WHEN pur.last_purchase_date IS NULL THEN 60
           ELSE MIN(60, CAST(julianday(b.snapshot_date)
                             - julianday(pur.last_purchase_date) AS INT))
       END                                                               AS days_since_purchase,
       COALESCE(ads.ads_completed_14, 0)                                 AS ads_completed_14,
       COALESCE(ads.ad_days_14, 0)                                       AS ad_days_14
FROM base b
JOIN act ON act.snapshot_day = b.snapshot_day AND act.device_id = b.device_id
JOIN future f ON f.snapshot_day = b.snapshot_day AND f.device_id = b.device_id
LEFT JOIN pd ON pd.snapshot_day = b.snapshot_day AND pd.device_id = b.device_id
LEFT JOIN pur ON pur.snapshot_day = b.snapshot_day AND pur.device_id = b.device_id
LEFT JOIN ads ON ads.snapshot_day = b.snapshot_day AND ads.device_id = b.device_id;


-- @4a_model_dataset
-- Export the built dataset (the model script reads this CSV).
SELECT * FROM d4_model_dataset
ORDER BY snapshot_day, device_id;


-- @4a_churn_baseline
-- Observed churn14 by snapshot and by the segments the model is later
-- evaluated on. This is descriptive, not model output.
WITH base AS (
    SELECT s.snapshot_date, s.split, s.snapshot_day, p.device_id, p.platform,
           p.country_tier, p.acquisition_channel,
           CAST(julianday(s.snapshot_date) - julianday(DATE(p.install_date)) AS INT) AS tenure_days,
           s.outcome_start, s.outcome_end
    FROM d4_snapshots s
    JOIN active_days a ON a.day_id = s.snapshot_day
    JOIN player_profile p USING (device_id)
    WHERE p.install_date <= s.snapshot_date
),
future AS (
    SELECT b.snapshot_day, b.device_id,
           CASE WHEN COUNT(f.day_id) = 0 THEN 1 ELSE 0 END AS churn14
    FROM base b
    LEFT JOIN active_days f
      ON f.device_id = b.device_id
     AND f.day_id BETWEEN b.outcome_start AND b.outcome_end
    GROUP BY b.snapshot_day, b.device_id
),
labelled AS (
    SELECT b.snapshot_date, b.split, b.platform, b.country_tier,
           b.acquisition_channel,
           CASE WHEN b.tenure_days < 7  THEN '0-6'
                WHEN b.tenure_days < 14 THEN '7-13'
                WHEN b.tenure_days < 30 THEN '14-29'
                WHEN b.tenure_days < 60 THEN '30-59'
                ELSE '60+' END AS tenure_bucket,
           f.churn14
    FROM base b JOIN future f USING (snapshot_day, device_id)
)
SELECT 'snapshot' AS cut, snapshot_date AS value, COUNT(*) AS n,
       SUM(churn14) AS churners, ROUND(100.0 * SUM(churn14) / COUNT(*), 2) AS churn_rate_pct
FROM labelled GROUP BY snapshot_date
UNION ALL
SELECT 'tenure_bucket', tenure_bucket, COUNT(*), SUM(churn14),
       ROUND(100.0 * SUM(churn14) / COUNT(*), 2)
FROM labelled GROUP BY tenure_bucket
UNION ALL
SELECT 'country_tier', CAST(country_tier AS TEXT), COUNT(*), SUM(churn14),
       ROUND(100.0 * SUM(churn14) / COUNT(*), 2)
FROM labelled GROUP BY country_tier
UNION ALL
SELECT 'acquisition_channel', acquisition_channel, COUNT(*), SUM(churn14),
       ROUND(100.0 * SUM(churn14) / COUNT(*), 2)
FROM labelled GROUP BY acquisition_channel
UNION ALL
SELECT 'platform', platform, COUNT(*), SUM(churn14),
       ROUND(100.0 * SUM(churn14) / COUNT(*), 2)
FROM labelled GROUP BY platform
ORDER BY cut, value;


-- @4a_feature_profile
-- Descriptive separation between churners and retained players (train rows
-- only). Not used to fit anything; it shows the write-up's intuition.
SELECT CASE WHEN churn14 = 1 THEN 'churn' ELSE 'retained' END AS group_label,
       COUNT(*)                                              AS n,
       ROUND(AVG(tenure_days), 2)                            AS avg_tenure_days,
       ROUND(AVG(active_days_7), 2)                          AS avg_active_days_7,
       ROUND(AVG(active_days_prev7), 2)                      AS avg_active_days_prev7,
       ROUND(AVG(active_days_delta), 2)                      AS avg_active_days_delta,
       ROUND(AVG(sessions_7), 2)                             AS avg_sessions_7,
       ROUND(AVG(playtime_7), 1)                             AS avg_playtime_7,
       ROUND(AVG(playtime_delta), 1)                         AS avg_playtime_delta,
       ROUND(AVG(level_last), 2)                             AS avg_level,
       ROUND(AVG(ads_completed_14), 2)                       AS avg_ads_14,
       ROUND(AVG(ever_payer), 4)                             AS payer_share,
       ROUND(AVG(days_since_purchase), 1)                    AS avg_days_since_purchase
FROM d4_model_dataset
WHERE split = 'train'
GROUP BY churn14
ORDER BY churn14;


-- @checks_d4
-- Reconciliation and leakage guards. Each row is (check, observed, expected).
SELECT '1 snapshot count and split assignment' AS check_item,
       (SELECT COUNT(*) || ' snapshots / ' || COUNT(DISTINCT split) || ' splits'
        FROM d4_snapshots) AS observed,
       '4 / 3' AS expected
UNION ALL
SELECT '2 one row per (snapshot, device)',
       CAST((SELECT COUNT(*) FROM (SELECT snapshot_day, device_id
                                   FROM d4_model_dataset
                                   GROUP BY snapshot_day, device_id
                                   HAVING COUNT(*) > 1)) AS TEXT),
       '0'
UNION ALL
SELECT '3 every outcome window is inside the extract',
       CAST((SELECT COUNT(*) FROM d4_snapshots
             WHERE outcome_start < 20260101 OR outcome_end > 20260430) AS TEXT),
       '0'
UNION ALL
SELECT '4 label present and binary',
       CAST((SELECT COUNT(*) FROM d4_model_dataset
             WHERE churn14 IS NULL OR churn14 NOT IN (0, 1)) AS TEXT),
       '0'
UNION ALL
SELECT '5 no NULLs in model features',
       CAST((SELECT COUNT(*) FROM d4_model_dataset
             WHERE tenure_days IS NULL OR level_last IS NULL
                OR active_days_14 IS NULL OR active_days_7 IS NULL
                OR active_days_prev7 IS NULL OR sessions_7 IS NULL
                OR sessions_prev7 IS NULL OR playtime_7 IS NULL
                OR playtime_prev7 IS NULL OR spend_lifetime IS NULL
                OR spend_14 IS NULL OR purchases_14 IS NULL
                OR ever_payer IS NULL OR days_since_purchase IS NULL
                OR ads_completed_14 IS NULL OR ad_days_14 IS NULL) AS TEXT),
       '0'
UNION ALL
SELECT '6 eligible = active snapshot rows minus pre-install artefacts',
       CAST((SELECT COUNT(*) FROM d4_model_dataset) AS TEXT) || ' / ' ||
       CAST((SELECT COUNT(*)
             FROM d4_snapshots s
             JOIN active_days ad ON ad.day_id = s.snapshot_day
             JOIN player_profile p USING (device_id)
             WHERE p.install_date IS NOT NULL
               AND p.install_date <= s.snapshot_date) AS TEXT),
       'equal'
UNION ALL
SELECT '7 churners recomputed by an independent query',
       CAST((SELECT SUM(CASE WHEN NOT EXISTS (
                            SELECT 1 FROM active_days f
                            WHERE f.device_id = ad.device_id
                              AND f.day_id BETWEEN s.outcome_start AND s.outcome_end)
                        THEN 1 ELSE 0 END)
             FROM d4_snapshots s
             JOIN active_days ad ON ad.day_id = s.snapshot_day
             JOIN player_profile a USING (device_id)
             WHERE a.install_date IS NOT NULL
               AND a.install_date <= s.snapshot_date) AS TEXT),
       CAST((SELECT SUM(churn14) FROM d4_model_dataset) AS TEXT)
UNION ALL
SELECT '8 split order is strictly temporal (train < validation < test)',
       CAST((SELECT MAX(snapshot_day) FROM d4_snapshots WHERE split = 'train') AS TEXT)
       || ' < ' ||
       CAST((SELECT MAX(snapshot_day) FROM d4_snapshots WHERE split = 'validation') AS TEXT)
       || ' < ' ||
       CAST((SELECT MAX(snapshot_day) FROM d4_snapshots WHERE split = 'test') AS TEXT),
       'true'
UNION ALL
SELECT '9 consecutive snapshots 28 days apart (non-overlapping windows)',
       CAST((SELECT COUNT(*) FROM (
                 SELECT CAST(julianday(snapshot_date)
                             - julianday(LAG(snapshot_date) OVER
                                         (ORDER BY snapshot_date)) AS INT) AS gap
                 FROM d4_snapshots) WHERE gap <> 28) AS TEXT),
       '0'
UNION ALL
SELECT '10 purchase-only snapshot actives included by D4 (union rule)',
       CAST((SELECT COUNT(*) FROM d4_snapshots s
             JOIN active_days ad ON ad.day_id = s.snapshot_day
             WHERE NOT EXISTS (
                 SELECT 1 FROM player_day pd
                 WHERE pd.device_id = ad.device_id
                   AND pd.activity_date = s.snapshot_day)) AS TEXT),
       '>0'
UNION ALL
SELECT '11 no eligible player has a feature window before the extract',
       CAST((SELECT MIN(d14_start) FROM d4_snapshots) AS TEXT),
       '20260101'
ORDER BY check_item;
