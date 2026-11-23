-- ============================================================================
-- DBMS Lab End-Sem — Deliverable 1: Get to know the data, in SQL
--
-- Run with:  python3 scripts/run_deliverable1.py
--
-- Global data-quality decisions (made once, applied everywhere):
--   D1. event_ts with single-digit hours ("2026-01-01 6:58:57") are normalised
--       to zero-padded form at LOAD time (scripts/load_data.py). Without this
--       SQLite's DATE() returns NULL and rows silently vanish from aggregates.
--   D2. purchase rows are deduplicated by purchase_id (122 duplicate ids,
--       same device/amount/day; a purchase_id is a unique key by definition).
--       purchase_dedup keeps the earliest event_ts of each id.
--   D3. "gross revenue" = sum of usd_amount over deduplicated POSITIVE rows.
--       Negative rows are refunds/chargebacks (228 rows, -$3,274.72) and are
--       reported separately; net = gross + refunds.
--   D4. A player is "active" on a date if they have a player_day row OR a
--       purchase that date (a purchase proves the player was in the game).
--       2,663 purchases (17%, $33.6k) land on dates with no player_day row;
--       without this rule revenue sits in the numerator while the payer is
--       missing from the DAU denominator, inflating ARPDAU.
--   D5. ad_view timestamps run exactly 8 hours ahead of every other table
--       (raw hours 08:00-13:59 are empty; shifting by -8h maps 392,949 of
--       392,949 ad device-days onto player_day). ad_local applies
--       DATE(event_ts, '-8 hours').
-- ============================================================================

-- @setup
DROP TABLE IF EXISTS purchase_dedup;
DROP TABLE IF EXISTS active_days;
DROP TABLE IF EXISTS ad_local;
DROP TABLE IF EXISTS dau_daily;

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
       CAST(strftime('%Y%m%d', DATE(event_ts)) AS INT) AS tx_date,  -- D1
       pack_name,
       usd_amount,
       currency_granted,
       sale_flag
FROM ranked
WHERE rn = 1;                                                       -- D2
CREATE INDEX idx_pur_dev ON purchase_dedup(device_id, tx_date);

-- D4: active device-days (player_day UNION purchase-days)
CREATE TEMP TABLE active_days AS
SELECT device_id, activity_date AS day_id FROM player_day
UNION
SELECT device_id, tx_date FROM purchase_dedup WHERE usd_amount > 0;
CREATE INDEX idx_act ON active_days(device_id, day_id);
CREATE INDEX idx_act_day ON active_days(day_id);

-- D5: ad interactions on local (game) dates
CREATE TEMP TABLE ad_local AS
SELECT device_id,
       DATE(event_ts, '-8 hours')              AS local_date,
       CAST(strftime('%Y%m%d', DATE(event_ts, '-8 hours')) AS INT) AS local_day,
       status,
       ad_daily_count,
       ad_daily_cap
FROM ad_view;
CREATE INDEX idx_adl ON ad_local(device_id, local_day);
CREATE INDEX idx_adl_day ON ad_local(local_day);

-- daily DAU (same definition as deliverable 1a, for the ad series)
CREATE TEMP TABLE dau_daily AS
SELECT day_id, COUNT(DISTINCT device_id) AS dau FROM active_days GROUP BY day_id;
CREATE INDEX idx_dd ON dau_daily(day_id);


-- @1a_daily_health
-- Daily health by platform: DAU, gross revenue, ARPDAU, same-day payer share.
-- Numerator/denominator care (D4): every purchaser is in DAU by construction,
-- so payer share is bounded and ARPDAU is not inflated by orphan revenue.
WITH dau AS (
    SELECT day_id,
           r.platform,
           COUNT(DISTINCT a.device_id) AS dau
    FROM active_days a
    JOIN player_profile r USING (device_id)
    GROUP BY day_id, r.platform
),
rev AS (
    SELECT tx_date,
           r.platform,
           SUM(CASE WHEN p.usd_amount > 0 THEN p.usd_amount ELSE 0 END) AS gross_rev,
           SUM(CASE WHEN p.usd_amount < 0 THEN p.usd_amount ELSE 0 END) AS refunds,
           COUNT(DISTINCT CASE WHEN p.usd_amount > 0 THEN p.device_id END) AS purchasers
    FROM purchase_dedup p
    JOIN player_profile r USING (device_id)
    GROUP BY tx_date, r.platform
)
SELECT d.day_id,
       d.platform,
       d.dau,
       ROUND(COALESCE(v.gross_rev, 0), 2)                       AS gross_revenue,
       ROUND(COALESCE(v.gross_rev, 0) / d.dau, 4)               AS arpdau,
       COALESCE(v.purchasers, 0)                                AS purchasers,
       ROUND(100.0 * COALESCE(v.purchasers, 0) / d.dau, 2)      AS payer_pct
FROM dau d
LEFT JOIN rev v ON v.tx_date = d.day_id AND v.platform = d.platform
ORDER BY d.day_id, d.platform;


-- @1a_monthly_summary
-- Sanity rollup: monthly totals per platform (check vs 1a_daily).
WITH dau AS (
    SELECT day_id, r.platform, COUNT(DISTINCT a.device_id) AS dau
    FROM active_days a JOIN player_profile r USING (device_id)
    GROUP BY day_id, r.platform
),
rev AS (
    SELECT tx_date, r.platform,
           SUM(CASE WHEN p.usd_amount > 0 THEN p.usd_amount ELSE 0 END) AS gross_rev,
           SUM(CASE WHEN p.usd_amount < 0 THEN p.usd_amount ELSE 0 END) AS refunds,
           COUNT(DISTINCT CASE WHEN p.usd_amount > 0 THEN p.device_id END) AS purchasers
    FROM purchase_dedup p JOIN player_profile r USING (device_id)
    GROUP BY tx_date, r.platform
)
SELECT SUBSTR(CAST(d.day_id AS TEXT), 1, 6)                        AS month,
       d.platform,
       SUM(d.dau)                                                  AS active_player_days,
       COUNT(DISTINCT d.day_id)                                    AS days,
       ROUND(SUM(COALESCE(v.gross_rev, 0)), 2)                     AS gross_revenue,
       ROUND(SUM(CASE WHEN v.refunds < 0 THEN v.refunds ELSE 0 END), 2) AS refunds,
       ROUND(SUM(COALESCE(v.gross_rev, 0)) / SUM(d.dau), 4)        AS arpdau,
       SUM(COALESCE(v.purchasers, 0))                              AS payer_days,
       ROUND(100.0 * SUM(COALESCE(v.purchasers, 0)) / SUM(d.dau), 2) AS payer_pct
FROM dau d
LEFT JOIN rev v ON v.tx_date = d.day_id AND v.platform = d.platform
GROUP BY month, d.platform
ORDER BY month, d.platform;


-- @1b_retention_cohorts
-- Install-week cohort grid: share active on life-days 1/7/14/30.
--
-- Cell rule (one line): cell N is populated only if install_date + N falls
-- inside the extract window [2026-01-01, 2026-04-30] for EVERY player in the
-- cohort, otherwise NA — this handles both edges: recent cohorts are
-- right-censored (day N not yet reached by window end) and pre-2026 installs
-- are left-censored (their early life predates the window, which is why the
-- day-30 column reaches back to Dec 2025 while day-1 only starts in Jan).
-- A cohort row is kept if at least one of its four cells is populated.
--
-- "Active on day N" = active (D4) on install_date + N days exactly.
-- Denominator = all installs in the week, including the 1,114 devices that
-- never appear in player_day (they count as inactive; none of them purchased).
WITH cohort AS (
    SELECT device_id,
           install_date,
           DATE(install_date,
                '-' || ((CAST(strftime('%w', install_date) AS INT) + 6) % 7)
                || ' days') AS week_start                       -- Monday
    FROM player_profile
),
grid AS (
    SELECT c.week_start,
           COUNT(*)                                                   AS installs,
           MIN(c.install_date)                                        AS first_install,
           MAX(c.install_date)                                        AS last_install,
           SUM(EXISTS (SELECT 1 FROM active_days a
                       WHERE a.device_id = c.device_id
                         AND a.day_id = CAST(strftime('%Y%m%d',
                              DATE(c.install_date, '+1 day')) AS INT))) AS n_d1,
           SUM(EXISTS (SELECT 1 FROM active_days a
                       WHERE a.device_id = c.device_id
                         AND a.day_id = CAST(strftime('%Y%m%d',
                              DATE(c.install_date, '+7 day')) AS INT))) AS n_d7,
           SUM(EXISTS (SELECT 1 FROM active_days a
                       WHERE a.device_id = c.device_id
                         AND a.day_id = CAST(strftime('%Y%m%d',
                              DATE(c.install_date, '+14 day')) AS INT))) AS n_d14,
           SUM(EXISTS (SELECT 1 FROM active_days a
                       WHERE a.device_id = c.device_id
                         AND a.day_id = CAST(strftime('%Y%m%d',
                              DATE(c.install_date, '+30 day')) AS INT))) AS n_d30
    FROM cohort c
    GROUP BY c.week_start
),
flags AS (
    SELECT grid.*,
           DATE(first_install, '+1 day')  >= '2026-01-01'
       AND DATE(last_install,  '+1 day')  <= '2026-04-30'        AS pop_d1,
           DATE(first_install, '+7 day')  >= '2026-01-01'
       AND DATE(last_install,  '+7 day')  <= '2026-04-30'        AS pop_d7,
           DATE(first_install, '+14 day') >= '2026-01-01'
       AND DATE(last_install,  '+14 day') <= '2026-04-30'        AS pop_d14,
           DATE(first_install, '+30 day') >= '2026-01-01'
       AND DATE(last_install,  '+30 day') <= '2026-04-30'        AS pop_d30
    FROM grid
)
SELECT week_start,
       installs,
       first_install,
       last_install,
       CASE WHEN pop_d1  THEN ROUND(100.0 * n_d1  / installs, 1) END AS d1_pct,
       CASE WHEN pop_d7  THEN ROUND(100.0 * n_d7  / installs, 1) END AS d7_pct,
       CASE WHEN pop_d14 THEN ROUND(100.0 * n_d14 / installs, 1) END AS d14_pct,
       CASE WHEN pop_d30 THEN ROUND(100.0 * n_d30 / installs, 1) END AS d30_pct
FROM flags
WHERE pop_d1 OR pop_d7 OR pop_d14 OR pop_d30
ORDER BY week_start;


-- @1c1_revenue_concentration
-- Share of revenue from top 1% / 10% / 50%, computed on TWO populations so the
-- denominator choice is explicit (the brief's "which denominator did you use"
-- trap): payers only, and all installed players (non-payers contribute $0).
-- Ranking everyone puts the same rich payers inside a much bigger denominator
-- and reads lower — both are defensible, we state both.
-- Per-payer revenue is net of refunds (D3), deduplicated (D2).
WITH payer_rev AS (
    SELECT device_id, SUM(usd_amount) AS rev
    FROM purchase_dedup
    GROUP BY device_id
),
pop AS (
    SELECT 'payers_only' AS population, device_id, rev FROM payer_rev
    UNION ALL
    SELECT 'all_players', r.device_id, COALESCE(p.rev, 0)
    FROM player_profile r LEFT JOIN payer_rev p USING (device_id)
),
ranked AS (
    SELECT population,
           rev,
           ROW_NUMBER() OVER (PARTITION BY population ORDER BY rev DESC) AS rn,
           COUNT(*)        OVER (PARTITION BY population)                AS n,
           SUM(rev)        OVER (PARTITION BY population)                AS total
    FROM pop
)
SELECT population,
       n                                     AS ranked_players,
       ROUND(total, 2)                       AS total_revenue,
       ROUND(100.0 * SUM(CASE WHEN rn <= (n + 99) / 100 THEN rev END) / total, 1)
                                             AS top_1pct_share,
       ROUND(100.0 * SUM(CASE WHEN rn <= (n + 9)  / 10  THEN rev END) / total, 1)
                                             AS top_10pct_share,
       ROUND(100.0 * SUM(CASE WHEN rn <= (n + 1)  / 2   THEN rev END) / total, 1)
                                             AS top_50pct_share
FROM ranked
GROUP BY population
ORDER BY population;


-- @1c2_time_to_first_purchase
-- Distribution of days from install to first purchase.
-- Population: installs on/after 2026-01-01 only. For earlier installs the
-- extract cannot see purchases made before 2026-01-01, so their "first"
-- purchase may not be their first (left censoring) — excluded, counted in
-- 1c2c. 110 payers have first_purchase before install_date (ordering/device-
-- link artefacts); they get negative day counts, bucketed separately.
WITH in_window AS (
    SELECT device_id FROM player_profile WHERE install_date >= '2026-01-01'
),
first_tx AS (
    SELECT p.device_id,
           r.install_date,
           MIN(DATE(p.event_ts)) AS first_purchase
    FROM purchase_dedup p
    JOIN player_profile r USING (device_id)
    WHERE p.usd_amount > 0
    GROUP BY p.device_id
),
days AS (
    SELECT device_id,
           install_date,
           CAST(julianday(first_purchase) - julianday(install_date) AS INT) AS d
    FROM first_tx JOIN in_window USING (device_id)
),
bucketed AS (
    SELECT CASE
             WHEN d < 0        THEN '00 negative (data issue, excluded)'
             WHEN d = 0        THEN '01 same day'
             WHEN d = 1        THEN '02 1 day'
             WHEN d <= 3       THEN '03 2-3 days'
             WHEN d <= 7       THEN '04 4-7 days'
             WHEN d <= 14      THEN '05 8-14 days'
             WHEN d <= 30      THEN '06 15-30 days'
             WHEN d <= 60      THEN '07 31-60 days'
             WHEN d <= 90      THEN '08 61-90 days'
             ELSE                  '09 90+ days'
           END AS bucket,
           d
    FROM days
)
SELECT bucket,
       COUNT(*)                                                    AS payers,
       ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM days), 1)    AS pct_of_payers,
       ROUND(AVG(d), 1)                                            AS mean_days
FROM bucketed
GROUP BY bucket
ORDER BY bucket;


-- @1c2b_time_to_first_stats
-- Headline stats for time-to-first-purchase + share who never pay.
WITH in_window_installs AS (
    SELECT device_id FROM player_profile WHERE install_date >= '2026-01-01'
),
first_tx AS (
    SELECT p.device_id, r.install_date, MIN(DATE(p.event_ts)) AS fp
    FROM purchase_dedup p JOIN player_profile r USING (device_id)
    WHERE p.usd_amount > 0
    GROUP BY p.device_id
),
days AS (
    SELECT CAST(julianday(fp) - julianday(install_date) AS INT) AS d
    FROM first_tx JOIN in_window_installs USING (device_id)
    WHERE install_date >= '2026-01-01' AND julianday(fp) >= julianday(install_date)
),
d_ranked AS (
    SELECT d, ROW_NUMBER() OVER (ORDER BY d) AS rn, COUNT(*) OVER () AS n FROM days
)
SELECT (SELECT COUNT(*) FROM in_window_installs)                 AS installs_in_window,
       (SELECT COUNT(*) FROM days)                               AS payers_in_window,
       ROUND(100.0 * (SELECT COUNT(*) FROM days)
             / (SELECT COUNT(*) FROM in_window_installs), 1)     AS pct_ever_paid,
       ROUND(100.0 * ((SELECT COUNT(*) FROM in_window_installs)
             - (SELECT COUNT(*) FROM days))
             / (SELECT COUNT(*) FROM in_window_installs), 1)     AS pct_never_paid,
       (SELECT MIN(d) FROM d_ranked)                             AS min_days,
       (SELECT d FROM d_ranked WHERE rn = (n + 1) / 2)           AS median_days,
       (SELECT d FROM d_ranked WHERE rn = (n * 3 + 3) / 4)       AS p75_days,
       (SELECT d FROM d_ranked WHERE rn = (n * 9 + 9) / 10)      AS p90_days,
       (SELECT MAX(d) FROM d_ranked)                             AS max_days;


-- @1c2c_never_pay_maturity
-- "Share who never pay" is right-censored for recent installs (the window
-- ends before they get a chance to pay). Split by follow-up maturity.
WITH payers AS (
    SELECT DISTINCT device_id FROM purchase_dedup WHERE usd_amount > 0
)
SELECT CASE
         WHEN r.install_date <= '2026-01-31' THEN '01 installed Jan (>=90d follow-up)'
         WHEN r.install_date <= '2026-02-28' THEN '02 installed Feb (>=60d follow-up)'
         WHEN r.install_date <= '2026-03-31' THEN '03 installed Mar (>=30d follow-up)'
         ELSE                                      '04 installed Apr (short follow-up)'
       END AS install_month,
       COUNT(*)                                                        AS installs,
       SUM(p.device_id IS NOT NULL)                                    AS payers,
       ROUND(100.0 * SUM(p.device_id IS NULL) / COUNT(*), 1)           AS never_paid_pct
FROM player_profile r
LEFT JOIN payers p USING (device_id)
WHERE r.install_date >= '2026-01-01'
GROUP BY install_month
ORDER BY install_month;


-- @1c3_repeat_purchase_gap
-- Days between consecutive purchases, buyers with >= 2 purchases only.
-- Window function (LAG) instead of a self-join, as the brief suggests.
-- Refunds excluded (D3): a chargeback is not a repeat purchase.
WITH tx AS (
    SELECT device_id,
           event_ts,
           julianday(event_ts)
             - julianday(LAG(event_ts) OVER (PARTITION BY device_id
                                              ORDER BY event_ts)) AS gap_days
    FROM purchase_dedup
    WHERE usd_amount > 0
),
gaps AS (
    SELECT device_id, gap_days FROM tx WHERE gap_days IS NOT NULL
),
ranked AS (
    SELECT gap_days,
           ROW_NUMBER() OVER (ORDER BY gap_days) AS rn,
           COUNT(*) OVER ()                     AS n
    FROM gaps
)
SELECT (SELECT COUNT(DISTINCT device_id) FROM gaps)              AS repeat_buyers,
       n                                                         AS purchase_pairs,
       ROUND(AVG(gap_days), 1)                                   AS mean_days,
       ROUND(MAX(CASE WHEN rn <= (n + 3) / 4     THEN gap_days END), 1) AS p25,
       ROUND(MAX(CASE WHEN rn <= (n + 1) / 2     THEN gap_days END), 1) AS median,
       ROUND(MAX(CASE WHEN rn <= (n * 3 + 3) / 4 THEN gap_days END), 1) AS p75,
       ROUND(MAX(CASE WHEN rn <= (n * 9 + 9) / 10 THEN gap_days END), 1) AS p90
FROM ranked;


-- @1c3b_repeat_gap_buckets
WITH tx AS (
    SELECT device_id, event_ts,
           julianday(event_ts)
             - julianday(LAG(event_ts) OVER (PARTITION BY device_id
                                              ORDER BY event_ts)) AS gap_days
    FROM purchase_dedup
    WHERE usd_amount > 0
)
SELECT CASE
         WHEN gap_days < 1  THEN '01 same day (<24h)'
         WHEN gap_days < 3  THEN '02 1-2 days'
         WHEN gap_days < 7  THEN '03 3-6 days'
         WHEN gap_days < 14 THEN '04 7-13 days'
         WHEN gap_days < 30 THEN '05 14-29 days'
         WHEN gap_days < 60 THEN '06 30-59 days'
         ELSE                    '07 60+ days'
       END AS gap_bucket,
       COUNT(*)                                               AS pairs,
       ROUND(100.0 * COUNT(*) / (SELECT COUNT(*)
              FROM (SELECT 1 FROM tx WHERE gap_days IS NOT NULL)), 1) AS pct
FROM tx
WHERE gap_days IS NOT NULL
GROUP BY gap_bucket
ORDER BY gap_bucket;


-- @1d1_cap_hit_by_cap
-- Share of ad-watching player-days that hit the daily cap, by cap value.
-- ad-watch day = a local (D5) device-day with >= 1 COMPLETED ad.
-- hit = some row on that day has ad_daily_count >= ad_daily_cap (row-level
-- pair, robust to the cap changing mid-day). Cap values are 5 and 8; a
-- device's cap changes over the window (45,551 devices move 5 -> 8), hence
-- per-device-day grouping, not per-device.
-- Two hit definitions reported: by the ad_daily_Counter (as stored) and by
-- completed views (the intuitive meaning) — they differ because the counter
-- also increments on started-but-not-completed views.
WITH dd AS (
    SELECT device_id,
           local_day,
           MAX(ad_daily_cap)                                        AS cap,
           MIN(ad_daily_cap)                                        AS cap_min,
           MAX(CASE WHEN ad_daily_count >= ad_daily_cap
                    THEN 1 ELSE 0 END)                              AS hit,
           COUNT(*)                                                AS interactions,
           SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END)    AS completed,
           SUM(CASE WHEN status = 'started'   THEN 1 ELSE 0 END)    AS started,
           SUM(CASE WHEN status = 'abandoned' THEN 1 ELSE 0 END)    AS abandoned
    FROM ad_local
    GROUP BY device_id, local_day
)
SELECT cap,
       COUNT(*)                                                        AS ad_days,
       SUM(cap <> cap_min)                                             AS days_cap_changed,
       SUM(CASE WHEN completed > 0 THEN 1 ELSE 0 END)                  AS watch_days,
       SUM(hit)                                                        AS counter_hit_days,
       SUM(CASE WHEN completed >= cap THEN 1 ELSE 0 END)               AS completed_hit_days,
       ROUND(100.0 * SUM(hit) / COUNT(*), 2)                           AS counter_hit_pct_of_ad_days,
       ROUND(100.0 * SUM(CASE WHEN completed >= cap THEN 1 ELSE 0 END)
             / NULLIF(SUM(CASE WHEN completed > 0 THEN 1 ELSE 0 END), 0), 2)
                                                                       AS completed_hit_pct_of_watch_days,
       ROUND(AVG(interactions), 2)                                     AS avg_interactions_per_day,
       ROUND(AVG(completed), 2)                                        AS avg_completed_per_day,
       SUM(CASE WHEN hit = 1 AND completed < cap THEN 1 ELSE 0 END)    AS counter_hit_but_completed_short,
       SUM(CASE WHEN interactions > completed THEN 1 ELSE 0 END)       AS days_counter_gt_completed
FROM dd
GROUP BY cap
ORDER BY cap;


-- @1d1b_cap_class_profile
-- Who sees which cap? Three classes: always 5, always 8, or moved 5 -> 8 at
-- some point (45,551 devices). Association only — devices that changed cap
-- have also played longer, so this is not a causal subscription effect.
WITH caps AS (
    SELECT device_id, MAX(ad_daily_cap) AS mx, MIN(ad_daily_cap) AS mn
    FROM ad_view GROUP BY device_id
)
SELECT CASE WHEN mx = 8 AND mn = 5 THEN 'changed_5_to_8'
            WHEN mx = 8            THEN 'always_8'
            ELSE                          'always_5' END AS cap_class,
       COUNT(*)                                        AS devices,
       ROUND(100.0 * SUM(EXISTS (
             SELECT 1 FROM currency_spend c
             WHERE c.device_id = caps.device_id
               AND c.spend_type = 'subscription')) / COUNT(*), 1)
                                                       AS pct_subscription,
       ROUND(100.0 * SUM(EXISTS (
             SELECT 1 FROM currency_spend c
             WHERE c.device_id = caps.device_id
               AND c.spend_type = 'paid')) / COUNT(*), 1)
                                                       AS pct_paid_currency,
       ROUND(100.0 * SUM(EXISTS (
             SELECT 1 FROM purchase p
             WHERE p.device_id = caps.device_id)) / COUNT(*), 1)
                                                       AS pct_iap_payer
FROM caps
GROUP BY cap_class
ORDER BY cap_class;


-- @1d2_daily_ad_views
-- Total daily ad views across the window (local dates, D5) with DAU context
-- and an anomaly flag vs the trailing 7-day average. Driven from dau_daily so
-- days with ZERO recorded ad rows appear explicitly (and get flagged) instead
-- of silently dropping out of the series.
WITH series AS (
    SELECT local_day,
           SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed,
           SUM(CASE WHEN status = 'started'   THEN 1 ELSE 0 END) AS started,
           SUM(CASE WHEN status = 'abandoned' THEN 1 ELSE 0 END) AS abandoned,
           COUNT(*)                                              AS interactions,
           COUNT(DISTINCT device_id)                             AS ad_users
    FROM ad_local
    GROUP BY local_day
),
flagged AS (
    SELECT d.day_id                AS local_day,
           COALESCE(s.completed, 0) AS completed,
           COALESCE(s.started, 0)   AS started,
           COALESCE(s.abandoned, 0) AS abandoned,
           COALESCE(s.interactions, 0) AS interactions,
           COALESCE(s.ad_users, 0)  AS ad_users,
           d.dau,
           AVG(COALESCE(s.completed, 0)) OVER (ORDER BY d.day_id
                ROWS BETWEEN 6 PRECEDING AND 1 PRECEDING)        AS prev7_avg
    FROM dau_daily d
    LEFT JOIN series s ON s.local_day = d.day_id
)
SELECT local_day,
       completed,
       started,
       abandoned,
       interactions,
       ad_users,
       dau,
       ROUND(100.0 * completed / NULLIF(dau, 0), 1)               AS completed_per_100_dau,
       ROUND(prev7_avg, 0)                                        AS prev7_avg_completed,
       CASE WHEN prev7_avg IS NOT NULL AND completed < 0.6 * prev7_avg
            THEN 'SUSPICIOUS (<60% of prior 7-day avg)' END      AS flag
FROM flagged
ORDER BY local_day;


-- @1d3_raw_vs_shifted_ad_days
-- Proof of the 8h offset (D5): raw ad dates vs player_day presence, before
-- and after the shift.
SELECT 'raw' AS basis,
       COUNT(*) AS ad_devdays,
       SUM(EXISTS (SELECT 1 FROM player_day p
                   WHERE p.device_id = a.device_id
                     AND p.activity_date = a.raw_day))           AS matched_player_day
FROM (SELECT DISTINCT device_id,
             CAST(strftime('%Y%m%d', DATE(event_ts)) AS INT) AS raw_day
      FROM ad_view) a
UNION ALL
SELECT 'shifted_-8h',
       COUNT(*),
       SUM(EXISTS (SELECT 1 FROM player_day p
                   WHERE p.device_id = a.device_id
                     AND p.activity_date = a.local_day))
FROM (SELECT DISTINCT device_id, local_day FROM ad_local) a;


-- @1d4_ad_dark_days
-- Anomaly scan part 1: days where players were active (in DAU) but the ad
-- table has zero rows — a telemetry outage, not player absence.
SELECT d.day_id,
       d.dau,
       (SELECT COUNT(*) FROM player_day p WHERE p.activity_date = d.day_id) AS pd_rows
FROM dau_daily d
WHERE NOT EXISTS (SELECT 1 FROM ad_local a WHERE a.local_day = d.day_id)
ORDER BY d.day_id;


-- @1d5_outage_raw_hours
-- Anomaly scan part 2: raw hourly shape of the ad outage. Rows exist only in
-- raw hours 00-07 and 14-23 normally; the gap spans raw 2026-03-05 08:00 to
-- 2026-03-07 07:59 = exactly 48h = local (D5) 2026-03-05 00:00 to 2026-03-06
-- 23:59 — two whole local days, which is why local Mar 5 and Mar 6 are absent
-- from 1d2 while local Mar 4 and Mar 7 are complete.
SELECT DATE(event_ts) AS raw_date,
       SUM(CASE WHEN CAST(SUBSTR(event_ts,12,2) AS INT) < 8
                THEN 1 ELSE 0 END)                            AS h00_07,
       SUM(CASE WHEN CAST(SUBSTR(event_ts,12,2) AS INT) BETWEEN 8 AND 13
                THEN 1 ELSE 0 END)                            AS h08_13_dead,
       SUM(CASE WHEN CAST(SUBSTR(event_ts,12,2) AS INT) >= 14
                THEN 1 ELSE 0 END)                            AS h14_23
FROM ad_view
WHERE DATE(event_ts) BETWEEN '2026-03-03' AND '2026-03-09'
GROUP BY raw_date
ORDER BY raw_date;


-- @checks_reconciliation
-- Sanity-check totals against each other (the brief asks for this explicitly).
SELECT '1 purchase rows raw vs deduplicated' AS check_item,
       CAST((SELECT COUNT(*) FROM purchase) AS TEXT)                       AS a,
       CAST((SELECT COUNT(*) FROM purchase_dedup) AS TEXT)                  AS b
UNION ALL
SELECT '2 purchase revenue raw vs deduplicated',
       CAST((SELECT ROUND(SUM(usd_amount), 2) FROM purchase) AS TEXT),
       CAST((SELECT ROUND(SUM(usd_amount), 2) FROM purchase_dedup) AS TEXT)
UNION ALL
SELECT '3 gross vs net (refunds)',
       CAST((SELECT ROUND(SUM(CASE WHEN usd_amount > 0 THEN usd_amount END), 2)
             FROM purchase_dedup) AS TEXT),
       CAST((SELECT ROUND(SUM(usd_amount), 2) FROM purchase_dedup) AS TEXT)
UNION ALL
SELECT '4 payers: profile first_purchase_date vs distinct tx devices',
       CAST((SELECT COUNT(*) FROM player_profile
             WHERE first_purchase_date IS NOT NULL) AS TEXT),
       CAST((SELECT COUNT(DISTINCT device_id) FROM purchase_dedup) AS TEXT)
UNION ALL
SELECT '5 active dev-days: player_day only vs union w/ purchases',
       CAST((SELECT COUNT(DISTINCT device_id || activity_date)
             FROM player_day) AS TEXT),
       CAST((SELECT COUNT(*) FROM (SELECT DISTINCT device_id, day_id
                                   FROM active_days)) AS TEXT)
UNION ALL
SELECT '6 ad dev-days matched to player_day (shifted)',
       CAST((SELECT COUNT(*) FROM (SELECT DISTINCT device_id, local_day
                                   FROM ad_local)) AS TEXT),
       CAST((SELECT COUNT(*) FROM (SELECT DISTINCT device_id, local_day
                                   FROM ad_local) a
             WHERE EXISTS (SELECT 1 FROM player_day p
                           WHERE p.device_id = a.device_id
                             AND p.activity_date = a.local_day)) AS TEXT)
UNION ALL
SELECT '7 revenue on days with no player_day row (D4 impact)',
       CAST((SELECT COUNT(*) FROM purchase_dedup p WHERE usd_amount > 0
             AND NOT EXISTS (SELECT 1 FROM player_day d
                             WHERE d.device_id = p.device_id
                               AND d.activity_date = p.tx_date)) AS TEXT),
       CAST((SELECT ROUND(SUM(usd_amount), 2) FROM purchase_dedup p
             WHERE usd_amount > 0
             AND NOT EXISTS (SELECT 1 FROM player_day d
                             WHERE d.device_id = p.device_id
                               AND d.activity_date = p.tx_date)) AS TEXT)
UNION ALL
SELECT '8 DAU: (day x platform) split sums to total active dev-days',
       CAST((SELECT SUM(dau) FROM (
            SELECT day_id, r.platform, COUNT(DISTINCT a.device_id) AS dau
            FROM active_days a JOIN player_profile r USING (device_id)
            GROUP BY day_id, r.platform)) AS TEXT),
       CAST((SELECT COUNT(*) FROM (SELECT DISTINCT device_id, day_id
                                   FROM active_days)) AS TEXT)
UNION ALL
SELECT '9 total active dev-days and DAU date range',
       CAST((SELECT COUNT(*) FROM (SELECT DISTINCT device_id, day_id
                                   FROM active_days)) AS TEXT),
       CAST((SELECT MIN(day_id) || '-' || MAX(day_id) FROM dau_daily) AS TEXT)
UNION ALL
SELECT '10 positive tx rows vs payers + repeat pairs (1c1/1c3 identity)',
       CAST((SELECT COUNT(*) FROM purchase_dedup WHERE usd_amount > 0) AS TEXT),
       CAST((SELECT COUNT(DISTINCT device_id) FROM purchase_dedup
             WHERE usd_amount > 0)
          + (SELECT COUNT(*) FROM (
               SELECT device_id, julianday(event_ts)
                 - julianday(LAG(event_ts) OVER (PARTITION BY device_id
                                                  ORDER BY event_ts)) AS g
               FROM purchase_dedup WHERE usd_amount > 0)
              WHERE g IS NOT NULL) AS TEXT)
UNION ALL
SELECT '11 ad rows on DAU days: dark days (expect 2 = Mar 5-6 outage)',
       CAST((SELECT COUNT(*) FROM dau_daily d
             WHERE NOT EXISTS (SELECT 1 FROM ad_local a
                               WHERE a.local_day = d.day_id)) AS TEXT),
       CAST((SELECT GROUP_CONCAT(day_id) FROM dau_daily d
             WHERE NOT EXISTS (SELECT 1 FROM ad_local a
                               WHERE a.local_day = d.day_id)) AS TEXT);
