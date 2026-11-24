-- ============================================================================
-- DBMS Lab End-Sem — Deliverable 3
--               "Is one acquisition channel better than another?"
--
-- Run with:  python3 scripts/run_deliverable3.py
--
-- Brief requirements (section 3):
--   * compare channels on >= 1 engagement measure and >= 1 revenue measure,
--     each defined precisely
--   * a confidence interval on the headline difference + significance call
--   * say what would be needed to tell a real difference from a collection
--     artefact
--   * distinguish "real but underpowered" from "artefact", and "significant"
--     from "worth moving budget over"
--
-- Conventions carried over unchanged from deliverables 1-2:
--   D1  event_ts zero-padded at load time
--   D2  purchases deduplicated by purchase_id
--   D3  gross revenue = positive usd_amount on deduplicated rows
--   D4  active = player_day row OR a purchase that day
--   D5  ad_view shifted -8h (only used here as an engagement feature)
--
-- MEASURES (stated once, used everywhere below):
--   revenue      30-day IAP revenue per install — installs 2026-01-01..03-31
--                (every install gets a full 30-day follow-up inside the
--                extract: no right censoring); plus 30-day payer rate.
--   engagement   (i) D7 retention: install-week x channel cohort active on
--                install+7, matured-cell rule inherited from deliverable 1b;
--                (ii) playtime minutes per RECORDED activity day
--                (player_day rows inside the period; purchase-only device-days
--                have no recorded playtime and are excluded from this
--                denominator — stated, not silently zero-filled).
--   naive        channel ARPDAU on device-days — computed ONLY as the exhibit
--                shown to be confounded (tier mix + calendar/timing mix).
--
-- Statistics (bootstrap CIs, z-tests) are computed by scripts/run_deliverable3.py
-- from sections 3c3 / 3d2 / 3e2 and written to 3g_significance.csv.
-- ============================================================================

-- @setup
DROP TABLE IF EXISTS purchase_dedup;
DROP TABLE IF EXISTS day_map;
DROP TABLE IF EXISTS active_days;
DROP TABLE IF EXISTS period_dd;
DROP TABLE IF EXISTS period_rev;

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
CREATE INDEX idx_pur_tx ON purchase_dedup(tx_date);
CREATE INDEX idx_pur_dev ON purchase_dedup(device_id);

-- Calendar helper (SQLite date functions reject bare YYYYMMDD integers)
CREATE TEMP TABLE day_map AS
WITH RECURSIVE seq(i) AS (
    SELECT 0 UNION ALL SELECT i + 1 FROM seq WHERE i < 119   -- 2026-01-01..04-30
)
SELECT CAST(strftime('%Y%m%d', d) AS INT) AS day_id,
       d                                  AS dstr,
       DATE(d, '-' || ((CAST(strftime('%w', d) AS INT) + 6) % 7) || ' days')
                                          AS week_start
FROM (SELECT DATE('2026-01-01', '+' || i || ' days') AS d FROM seq);
CREATE INDEX idx_daymap ON day_map(day_id);

-- D4: active device-days
CREATE TEMP TABLE active_days AS
SELECT device_id, activity_date AS day_id FROM player_day
UNION
SELECT device_id, tx_date FROM purchase_dedup WHERE usd_amount > 0;
CREATE INDEX idx_act ON active_days(device_id, day_id);

-- P1/P2 windows (same as deliverable 2 — lets 3a/3b state the naive
-- channel ARPDAU per period, matching the D2 numbers exactly)
CREATE TEMP TABLE period_dd AS
SELECT CASE WHEN day_id BETWEEN 20260101 AND 20260130 THEN 1
            WHEN day_id BETWEEN 20260401 AND 20260430 THEN 2 END AS pid,
       device_id,
       day_id
FROM active_days
WHERE day_id BETWEEN 20260101 AND 20260130
   OR day_id BETWEEN 20260401 AND 20260430;
CREATE INDEX idx_pdd ON period_dd(pid, device_id, day_id);

CREATE TEMP TABLE period_rev AS
SELECT CASE WHEN tx_date BETWEEN 20260101 AND 20260130 THEN 1
            WHEN tx_date BETWEEN 20260401 AND 20260430 THEN 2 END AS pid,
       device_id,
       tx_date,
       usd_amount
FROM purchase_dedup
WHERE tx_date BETWEEN 20260101 AND 20260130
   OR tx_date BETWEEN 20260401 AND 20260430;
CREATE INDEX idx_prev ON period_rev(pid, tx_date);


-- @3a_channel_period
-- Composition + the NAIVE channel ARPDAU (the exhibit). Channel shares of
-- active device-days move sharply between the two windows; revenue/arpdau
-- here is what a casual reader would compare.
SELECT pd.pid,
       r.acquisition_channel AS channel,
       COUNT(*)              AS active_dd,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY pd.pid), 1)
                             AS share_pct,
       ROUND(COALESCE(v.gross, 0), 2)                  AS gross,
       ROUND(COALESCE(v.gross, 0) / COUNT(*), 4)       AS arpdau
FROM period_dd pd
JOIN player_profile r USING (device_id)
LEFT JOIN (
    SELECT pid, r.acquisition_channel AS channel,
           SUM(CASE WHEN usd_amount > 0 THEN usd_amount ELSE 0 END) AS gross
    FROM period_rev JOIN player_profile r USING (device_id)
    GROUP BY pid, r.acquisition_channel
) v ON v.pid = pd.pid AND v.channel = r.acquisition_channel
GROUP BY pd.pid, r.acquisition_channel
ORDER BY pd.pid, channel;


-- @3a_channel_tier
-- Confound 1: each channel's tier mix (paid_video skews tier-4).
SELECT pd.pid,
       r.acquisition_channel AS channel,
       r.country_tier        AS tier,
       COUNT(*)              AS active_dd,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY pd.pid, r.acquisition_channel), 1)
                             AS share_of_channel_pct
FROM period_dd pd
JOIN player_profile r USING (device_id)
GROUP BY pd.pid, r.acquisition_channel, r.country_tier
ORDER BY pd.pid, channel, tier;


-- @3a_channel_install_month
-- Confound 2: each channel's calendar mix (paid_video only ramped in Mar-Apr,
-- so its players are young and payer-immature inside any window).
SELECT substr(install_date, 1, 7) AS install_month,
       acquisition_channel        AS channel,
       COUNT(*)                   AS installs,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (
             PARTITION BY substr(install_date, 1, 7)), 1) AS share_of_month_pct
FROM player_profile
GROUP BY install_month, channel
ORDER BY install_month, channel;


-- @3b_naive_vs_std
-- The exhibit: naive channel ARPDAU vs tier-standardised ARPDAU (direct
-- standardisation — every channel reweighted to the same tier mix w_t =
-- that period's overall tier share of device-days). If the channel gap
-- shrinks, the naive gap was tier composition.
-- pid 1 = P1, pid 2 = P2, pid 0 = pooled.
WITH act AS (
    SELECT 1 AS pid, device_id, day_id FROM period_dd WHERE pid = 1
    UNION ALL
    SELECT 2 AS pid, device_id, day_id FROM period_dd WHERE pid = 2
    UNION ALL
    SELECT 0 AS pid, device_id, day_id FROM period_dd       -- pooled
),
rev AS (
    SELECT 1 AS pid, device_id, tx_date, usd_amount FROM period_rev WHERE pid = 1
    UNION ALL
    SELECT 2 AS pid, device_id, tx_date, usd_amount FROM period_rev WHERE pid = 2
    UNION ALL
    SELECT 0 AS pid, device_id, tx_date, usd_amount FROM period_rev  -- pooled
),
ddc AS (
    SELECT a.pid, r.acquisition_channel AS ch, r.country_tier AS tier,
           COUNT(*) AS dd
    FROM act a JOIN player_profile r USING (device_id)
    GROUP BY a.pid, r.acquisition_channel, r.country_tier
),
rgc AS (
    SELECT v.pid, r.acquisition_channel AS ch, r.country_tier AS tier,
           SUM(CASE WHEN v.usd_amount > 0 THEN v.usd_amount ELSE 0 END) AS gross
    FROM rev v JOIN player_profile r USING (device_id)
    GROUP BY v.pid, r.acquisition_channel, r.country_tier
),
tw AS (
    SELECT d.pid, d.tier,
           1.0 * SUM(d.dd) / (SELECT SUM(d2.dd) FROM ddc d2 WHERE d2.pid = d.pid) AS w
    FROM ddc d
    GROUP BY d.pid, d.tier
),
cells AS (
    SELECT d.pid, d.ch, d.tier, d.dd, COALESCE(g.gross, 0) AS gross,
           1.0 * d.dd / SUM(d.dd) OVER (PARTITION BY d.pid, d.ch) AS s_own,
           COALESCE(g.gross, 0) / d.dd                            AS r,
           t.w                                                    AS w
    FROM ddc d
    LEFT JOIN rgc g ON g.pid = d.pid AND g.ch = d.ch AND g.tier = d.tier
    JOIN tw t ON t.pid = d.pid AND t.tier = d.tier
)
SELECT pid,
       ch                                                        AS channel,
       SUM(dd)                                                   AS active_dd,
       ROUND(SUM(s_own * r), 4)                                  AS arpdau_raw,
       ROUND(SUM(w * r), 4)                                      AS arpdau_tier_std,
       ROUND(SUM(s_own * r) - SUM(w * r), 4)                     AS raw_minus_std
FROM cells
GROUP BY pid, ch
ORDER BY pid, channel;


-- @3c_ltv30_channel
-- HEADLINE REVENUE MEASURE: 30-day IAP revenue per install, by channel.
-- Installs 2026-01-01..03-31 only (full 30-day follow-up inside extract).
WITH inst AS (
    SELECT device_id, acquisition_channel AS channel, install_date
    FROM player_profile
    WHERE install_date BETWEEN '2026-01-01' AND '2026-03-31'
),
agg AS (
    SELECT i.channel,
           COUNT(DISTINCT i.device_id)                        AS installs,
           COUNT(DISTINCT CASE WHEN p.usd_amount > 0
                               THEN i.device_id END)          AS payers_30d,
           COALESCE(SUM(CASE WHEN p.usd_amount > 0
                             THEN p.usd_amount ELSE 0 END), 0) AS rev30
    FROM inst i
    LEFT JOIN purchase_dedup p
           ON p.device_id = i.device_id
          AND julianday(p.tx_dstr) - julianday(i.install_date) >= 0
          AND julianday(p.tx_dstr) - julianday(i.install_date) < 30
    GROUP BY i.channel
)
SELECT channel,
       installs,
       payers_30d,
       ROUND(100.0 * payers_30d / installs, 2)  AS payer_rate_30d_pct,
       ROUND(rev30, 2)                          AS rev30,
       ROUND(rev30 / installs, 4)               AS revenue_per_install_30d
FROM agg
ORDER BY channel;


-- @3c_ltv30_channel_tier
-- Same measure inside each tier: separates "channel brings worse players"
-- from "channel brings players from low-monetising tiers".
WITH inst AS (
    SELECT device_id, acquisition_channel AS channel,
           country_tier AS tier, install_date
    FROM player_profile
    WHERE install_date BETWEEN '2026-01-01' AND '2026-03-31'
),
agg AS (
    SELECT i.channel, i.tier,
           COUNT(DISTINCT i.device_id)                        AS installs,
           COUNT(DISTINCT CASE WHEN p.usd_amount > 0
                               THEN i.device_id END)          AS payers_30d,
           COALESCE(SUM(CASE WHEN p.usd_amount > 0
                             THEN p.usd_amount ELSE 0 END), 0) AS rev30
    FROM inst i
    LEFT JOIN purchase_dedup p
           ON p.device_id = i.device_id
          AND julianday(p.tx_dstr) - julianday(i.install_date) >= 0
          AND julianday(p.tx_dstr) - julianday(i.install_date) < 30
    GROUP BY i.channel, i.tier
)
SELECT channel,
       tier,
       installs,
       payers_30d,
       ROUND(100.0 * payers_30d / installs, 2)  AS payer_rate_30d_pct,
       ROUND(rev30, 2)                          AS rev30,
       ROUND(rev30 / installs, 4)               AS revenue_per_install_30d
FROM agg
ORDER BY channel, tier;


-- @3c_ltv30_install_rows
-- One row per in-scope install: the raw input for bootstrap confidence
-- intervals in the runner (rev30 is heavily skewed — means need resampling).
WITH inst AS (
    SELECT device_id, acquisition_channel AS channel,
           country_tier AS tier, install_date
    FROM player_profile
    WHERE install_date BETWEEN '2026-01-01' AND '2026-03-31'
)
SELECT i.device_id,
       i.channel,
       i.tier,
       i.install_date,
       ROUND(COALESCE(SUM(CASE WHEN p.usd_amount > 0
                               THEN p.usd_amount ELSE 0 END), 0), 4) AS rev30,
       CASE WHEN SUM(CASE WHEN p.usd_amount > 0 THEN 1 ELSE 0 END) > 0
            THEN 1 ELSE 0 END                                        AS paid30
FROM inst i
LEFT JOIN purchase_dedup p
       ON p.device_id = i.device_id
      AND julianday(p.tx_dstr) - julianday(i.install_date) >= 0
      AND julianday(p.tx_dstr) - julianday(i.install_date) < 30
GROUP BY i.device_id;


-- @3d_retention_channel_week
-- ENGAGEMENT MEASURE (i), by install-week x channel. Matured-cell rule is
-- deliverable 1b's verbatim: cell N exists only if install_date+N lies inside
-- [2026-01-01, 2026-04-30] for EVERY install in the cohort (right AND left
-- censoring handled), else NA.
WITH cohort AS (
    SELECT device_id,
           acquisition_channel AS channel,
           install_date,
           DATE(install_date,
                '-' || ((CAST(strftime('%w', install_date) AS INT) + 6) % 7)
                || ' days') AS week_start
    FROM player_profile
),
grid AS (
    SELECT channel, week_start,
           COUNT(*) AS installs,
           MIN(install_date) AS fi,
           MAX(install_date) AS li,
           SUM(EXISTS (SELECT 1 FROM active_days a
                       WHERE a.device_id = c.device_id
                         AND a.day_id = CAST(strftime('%Y%m%d',
                              DATE(c.install_date, '+1 day')) AS INT)))  AS n_d1,
           SUM(EXISTS (SELECT 1 FROM active_days a
                       WHERE a.device_id = c.device_id
                         AND a.day_id = CAST(strftime('%Y%m%d',
                              DATE(c.install_date, '+7 day')) AS INT)))  AS n_d7,
           SUM(EXISTS (SELECT 1 FROM active_days a
                       WHERE a.device_id = c.device_id
                         AND a.day_id = CAST(strftime('%Y%m%d',
                              DATE(c.install_date, '+14 day')) AS INT))) AS n_d14,
           SUM(EXISTS (SELECT 1 FROM active_days a
                       WHERE a.device_id = c.device_id
                         AND a.day_id = CAST(strftime('%Y%m%d',
                              DATE(c.install_date, '+30 day')) AS INT))) AS n_d30
    FROM cohort c
    GROUP BY channel, week_start
),
flags AS (
    SELECT grid.*,
           DATE(fi, '+1 day')  >= '2026-01-01' AND DATE(li, '+1 day')  <= '2026-04-30' AS p1,
           DATE(fi, '+7 day')  >= '2026-01-01' AND DATE(li, '+7 day')  <= '2026-04-30' AS p7,
           DATE(fi, '+14 day') >= '2026-01-01' AND DATE(li, '+14 day') <= '2026-04-30' AS p14,
           DATE(fi, '+30 day') >= '2026-01-01' AND DATE(li, '+30 day') <= '2026-04-30' AS p30
    FROM grid
)
SELECT channel, week_start, installs,
       CASE WHEN p1  THEN ROUND(100.0 * n_d1  / installs, 1) END AS d1_pct,
       CASE WHEN p7  THEN ROUND(100.0 * n_d7  / installs, 1) END AS d7_pct,
       CASE WHEN p14 THEN ROUND(100.0 * n_d14 / installs, 1) END AS d14_pct,
       CASE WHEN p30 THEN ROUND(100.0 * n_d30 / installs, 1) END AS d30_pct
FROM flags
WHERE p1 OR p7 OR p14 OR p30
ORDER BY week_start, channel;


-- @3d_retention_channel_pooled
-- Pooled matured-cell retention by channel (counts, so the runner can run
-- two-proportion z-tests). Pooled = sum retained over matured cohorts /
-- sum installs of matured cohorts, computed per day-offset independently.
WITH cohort AS (
    SELECT device_id,
           acquisition_channel AS channel,
           install_date,
           DATE(install_date,
                '-' || ((CAST(strftime('%w', install_date) AS INT) + 6) % 7)
                || ' days') AS week_start
    FROM player_profile
),
grid AS (
    SELECT channel, week_start,
           COUNT(*) AS installs,
           MIN(install_date) AS fi,
           MAX(install_date) AS li,
           SUM(EXISTS (SELECT 1 FROM active_days a
                       WHERE a.device_id = c.device_id
                         AND a.day_id = CAST(strftime('%Y%m%d',
                              DATE(c.install_date, '+1 day')) AS INT)))  AS n_d1,
           SUM(EXISTS (SELECT 1 FROM active_days a
                       WHERE a.device_id = c.device_id
                         AND a.day_id = CAST(strftime('%Y%m%d',
                              DATE(c.install_date, '+7 day')) AS INT)))  AS n_d7,
           SUM(EXISTS (SELECT 1 FROM active_days a
                       WHERE a.device_id = c.device_id
                         AND a.day_id = CAST(strftime('%Y%m%d',
                              DATE(c.install_date, '+14 day')) AS INT))) AS n_d14,
           SUM(EXISTS (SELECT 1 FROM active_days a
                       WHERE a.device_id = c.device_id
                         AND a.day_id = CAST(strftime('%Y%m%d',
                              DATE(c.install_date, '+30 day')) AS INT))) AS n_d30
    FROM cohort c
    GROUP BY channel, week_start
),
flags AS (
    SELECT grid.*,
           DATE(fi, '+1 day')  >= '2026-01-01' AND DATE(li, '+1 day')  <= '2026-04-30' AS p1,
           DATE(fi, '+7 day')  >= '2026-01-01' AND DATE(li, '+7 day')  <= '2026-04-30' AS p7,
           DATE(fi, '+14 day') >= '2026-01-01' AND DATE(li, '+14 day') <= '2026-04-30' AS p14,
           DATE(fi, '+30 day') >= '2026-01-01' AND DATE(li, '+30 day') <= '2026-04-30' AS p30
    FROM grid
)
SELECT channel,
       SUM(CASE WHEN p1  THEN installs END) AS d1_matured,
       SUM(CASE WHEN p1  THEN n_d1  END)    AS d1_retained,
       SUM(CASE WHEN p7  THEN installs END) AS d7_matured,
       SUM(CASE WHEN p7  THEN n_d7  END)    AS d7_retained,
       SUM(CASE WHEN p14 THEN installs END) AS d14_matured,
       SUM(CASE WHEN p14 THEN n_d14 END)    AS d14_retained,
       SUM(CASE WHEN p30 THEN installs END) AS d30_matured,
       SUM(CASE WHEN p30 THEN n_d30 END)    AS d30_retained,
       ROUND(100.0 * SUM(CASE WHEN p1  THEN n_d1  END)
             / NULLIF(SUM(CASE WHEN p1  THEN installs END), 0), 2) AS d1_pct,
       ROUND(100.0 * SUM(CASE WHEN p7  THEN n_d7  END)
             / NULLIF(SUM(CASE WHEN p7  THEN installs END), 0), 2) AS d7_pct,
       ROUND(100.0 * SUM(CASE WHEN p14 THEN n_d14 END)
             / NULLIF(SUM(CASE WHEN p14 THEN installs END), 0), 2) AS d14_pct,
       ROUND(100.0 * SUM(CASE WHEN p30 THEN n_d30 END)
             / NULLIF(SUM(CASE WHEN p30 THEN installs END), 0), 2) AS d30_pct
FROM flags
GROUP BY channel
ORDER BY channel;


-- @3e_playtime_channel
-- ENGAGEMENT MEASURE (ii): intensity among currently-playing devices.
-- Scope: player_day rows that fall inside P1/P2 (period_dd x player_day join);
-- purchase-only device-days carry no recorded playtime and are excluded from
-- this denominator by definition (stated, not zero-filled).
SELECT pd.pid,
       r.acquisition_channel AS channel,
       COUNT(*)              AS recorded_days,
       SUM(a.playtime_minutes) AS playtime_minutes,
       SUM(a.session_count)    AS sessions,
       ROUND(1.0 * SUM(a.playtime_minutes) / COUNT(*), 2) AS minutes_per_recorded_day,
       ROUND(1.0 * SUM(a.session_count) / COUNT(*), 2)    AS sessions_per_recorded_day
FROM period_dd pd
JOIN player_day a ON a.device_id = pd.device_id AND a.activity_date = pd.day_id
JOIN player_profile r USING (device_id)
GROUP BY pd.pid, r.acquisition_channel
ORDER BY pd.pid, channel;


-- @3e_playtime_device
-- Device-level averages for bootstrap resampling (days within a device are
-- correlated; the device is the defensible resampling unit).
SELECT r.acquisition_channel AS channel,
       COUNT(*)              AS devices,
       ROUND(AVG(pm), 4)     AS avg_device_minutes_per_day,
       ROUND(AVG(ps), 4)     AS avg_device_sessions_per_day
FROM (
    SELECT a.device_id,
           1.0 * SUM(a.playtime_minutes) / COUNT(*) AS pm,
           1.0 * SUM(a.session_count) / COUNT(*)    AS ps
    FROM player_day a
    JOIN period_dd pd ON pd.device_id = a.device_id AND pd.day_id = a.activity_date
    GROUP BY a.device_id
) d
JOIN player_profile r USING (device_id)
GROUP BY r.acquisition_channel
ORDER BY channel;


-- @3e_playtime_device_rows
-- Per-device rows (device_id, channel, avg minutes/day) for the bootstrap.
SELECT r.acquisition_channel AS channel,
       COUNT(*)              AS recorded_days,
       1.0 * SUM(a.playtime_minutes) / COUNT(*) AS avg_minutes_per_day
FROM player_day a
JOIN period_dd pd ON pd.device_id = a.device_id AND pd.day_id = a.activity_date
JOIN player_profile r USING (device_id)
GROUP BY a.device_id, r.acquisition_channel;


-- @3c_ltv30_tier_std
-- Tier-standardised revenue/install and payer rate: every channel reweighted
-- to the pooled Jan-Mar install tier mix (direct standardisation). If the
-- naive gap collapses here, the naive gap was install mix, not player quality.
WITH inst AS (
    SELECT device_id, acquisition_channel AS channel,
           country_tier AS tier, install_date
    FROM player_profile
    WHERE install_date BETWEEN '2026-01-01' AND '2026-03-31'
),
agg AS (
    SELECT i.channel, i.tier,
           COUNT(DISTINCT i.device_id)                        AS installs,
           COUNT(DISTINCT CASE WHEN p.usd_amount > 0
                               THEN i.device_id END)          AS payers,
           COALESCE(SUM(CASE WHEN p.usd_amount > 0
                             THEN p.usd_amount ELSE 0 END), 0) AS rev30
    FROM inst i
    LEFT JOIN purchase_dedup p
           ON p.device_id = i.device_id
          AND julianday(p.tx_dstr) - julianday(i.install_date) >= 0
          AND julianday(p.tx_dstr) - julianday(i.install_date) < 30
    GROUP BY i.channel, i.tier
),
w AS (
    SELECT tier, 1.0 * SUM(installs) / (SELECT SUM(installs) FROM agg) AS wt
    FROM agg GROUP BY tier
)
SELECT channel,
       SUM(installs)                                   AS installs,
       ROUND(100.0 * SUM(payers) / SUM(installs), 2)   AS payer_rate_naive_pct,
       ROUND(SUM(rev30) / SUM(installs), 4)            AS rpi_naive,
       ROUND(SUM(wt * payers / installs) * 100, 2)     AS payer_rate_std_pct,
       ROUND(SUM(wt * rev30 / installs), 4)            AS rpi_tier_std
FROM agg JOIN w USING (tier)
GROUP BY channel
ORDER BY channel;


-- @3d_retention_channel_month
-- D7 retention by channel x install month: is the channel retention gap a
-- calendar artefact (paid_video installs concentrate in Mar-Apr, cohorts
-- whose day-7 may straddle the Feb-Mar data gap from deliverable 1 Q7)?
-- Matured-cell rule as in 3d (all Jan-Mar cells mature for every offset).
WITH cohort AS (
    SELECT device_id, acquisition_channel AS channel, install_date,
           substr(install_date, 1, 7) AS install_month
    FROM player_profile
    WHERE install_date BETWEEN '2026-01-01' AND '2026-03-31'
),
grid AS (
    SELECT channel, install_month, COUNT(*) AS installs,
           SUM(EXISTS (SELECT 1 FROM active_days a
                       WHERE a.device_id = c.device_id
                         AND a.day_id = CAST(strftime('%Y%m%d',
                              DATE(c.install_date, '+7 day')) AS INT))) AS n_d7
    FROM cohort c
    GROUP BY channel, install_month
)
SELECT install_month, channel, installs, n_d7 AS d7_retained,
       ROUND(100.0 * n_d7 / installs, 2) AS d7_pct
FROM grid
ORDER BY install_month, channel;


-- @3e_playtime_channel_tier
-- Is the playtime-per-day gap tier composition? Minutes per recorded day
-- inside each channel x tier (P1+P2 recorded days pooled).
SELECT r.acquisition_channel AS channel,
       r.country_tier        AS tier,
       COUNT(*)              AS recorded_days,
       ROUND(1.0 * SUM(a.playtime_minutes) / COUNT(*), 2) AS minutes_per_recorded_day
FROM player_day a
JOIN period_dd pd ON pd.device_id = a.device_id AND pd.day_id = a.activity_date
JOIN player_profile r USING (device_id)
GROUP BY r.acquisition_channel, r.country_tier
ORDER BY channel, tier;


-- @checks_d3
-- Reconciliation: totals against each other and against deliverables 1-2.
SELECT '1 channel active_dd sums to period totals (P1 / P2 / pooled)' AS check_item,
       CAST((SELECT SUM(n) FROM (
             SELECT COUNT(*) n FROM period_dd pd JOIN player_profile r USING (device_id)
             GROUP BY r.acquisition_channel) ) AS TEXT),
       CAST((SELECT COUNT(*) FROM period_dd) || ' rows in P1+P2' AS TEXT)
UNION ALL
SELECT '2 channel gross sums to period gross (P1 + P2 = pooled)',
       CAST(ROUND((SELECT SUM(g) FROM (
             SELECT SUM(CASE WHEN usd_amount > 0 THEN usd_amount ELSE 0 END) g
             FROM period_rev JOIN player_profile r USING (device_id)
             GROUP BY r.acquisition_channel)), 2) AS TEXT),
       CAST(ROUND((SELECT SUM(CASE WHEN usd_amount > 0 THEN usd_amount ELSE 0 END)
                   FROM period_rev), 2) AS TEXT)
UNION ALL
SELECT '3 installs: channel sums vs player_profile total',
       CAST((SELECT SUM(n) FROM (
             SELECT COUNT(*) n FROM player_profile GROUP BY acquisition_channel)) AS TEXT),
       CAST((SELECT COUNT(*) FROM player_profile) AS TEXT)
UNION ALL
SELECT '4 no NULL acquisition_channel',
       CAST((SELECT COUNT(*) FROM player_profile WHERE acquisition_channel IS NULL) AS TEXT),
       '0'
UNION ALL
SELECT '5 LTV30 installs Jan-Mar: channel sums vs in-scope total (37,489)',
       CAST((SELECT SUM(n) FROM (
             SELECT COUNT(DISTINCT device_id) n FROM player_profile
             WHERE install_date BETWEEN '2026-01-01' AND '2026-03-31'
             GROUP BY acquisition_channel)) AS TEXT),
       CAST((SELECT COUNT(DISTINCT device_id) FROM player_profile
             WHERE install_date BETWEEN '2026-01-01' AND '2026-03-31') AS TEXT)
UNION ALL
SELECT '6 LTV30 revenue: channel sums vs D2 tier sums (77,493.58)',
       CAST(ROUND((SELECT SUM(r) FROM (
             SELECT COALESCE(SUM(CASE WHEN p.usd_amount > 0
                                      THEN p.usd_amount ELSE 0 END), 0) AS r
             FROM (SELECT device_id, acquisition_channel, install_date
                   FROM player_profile
                   WHERE install_date BETWEEN '2026-01-01' AND '2026-03-31') i
             LEFT JOIN purchase_dedup p ON p.device_id = i.device_id
              AND julianday(p.tx_dstr) - julianday(i.install_date) >= 0
              AND julianday(p.tx_dstr) - julianday(i.install_date) < 30
             GROUP BY i.acquisition_channel)), 2) AS TEXT),
       '77493.58'
UNION ALL
SELECT '7 identity: sum(share x raw ARPDAU) over channels = blended ARPDAU',
       CAST((SELECT ROUND(SUM(share * raw), 4) FROM (
             SELECT a.dd * 1.0 / (SELECT COUNT(*) FROM period_dd) AS share,
                    1.0 * b.gross / a.dd                          AS raw
             FROM (SELECT r.acquisition_channel AS ch, COUNT(*) AS dd
                   FROM period_dd pd JOIN player_profile r USING (device_id)
                   GROUP BY r.acquisition_channel) a
             JOIN (SELECT acquisition_channel AS ch,
                          SUM(CASE WHEN usd_amount > 0
                                   THEN usd_amount ELSE 0 END) AS gross
                   FROM period_rev JOIN player_profile r USING (device_id)
                   GROUP BY acquisition_channel) b ON b.ch = a.ch)) AS TEXT),
       CAST((SELECT ROUND(SUM(CASE WHEN usd_amount > 0
                              THEN usd_amount ELSE 0 END)
                     * 1.0 / (SELECT COUNT(*) FROM period_dd), 4)
             FROM period_rev) AS TEXT)
UNION ALL
SELECT '8 retention d7 pooled: retained <= matured (matured-cell rule, all weeks)',
       CAST((SELECT ret || ' <= ' || mat FROM (
             SELECT SUM(CASE WHEN ok7 THEN n_ret END) AS ret,
                    SUM(CASE WHEN ok7 THEN n_mat END) AS mat
             FROM (SELECT DATE(fi, '+7 day') >= '2026-01-01'
                        AND DATE(li, '+7 day') <= '2026-04-30' AS ok7,
                          n_mat, n_ret
                   FROM (SELECT MIN(c.install_date) AS fi,
                                MAX(c.install_date) AS li,
                                COUNT(*) AS n_mat,
                                SUM(EXISTS (SELECT 1 FROM active_days a
                                    WHERE a.device_id = c.device_id
                                      AND a.day_id = CAST(strftime('%Y%m%d',
                                           DATE(c.install_date, '+7 day')) AS INT)))
                                    AS n_ret
                         FROM (SELECT device_id, install_date FROM player_profile) c
                         GROUP BY DATE(c.install_date,
                              '-' || ((CAST(strftime('%w', c.install_date) AS INT) + 6) % 7)
                              || ' days'))))) AS TEXT),
       CAST((SELECT COUNT(*) FROM player_profile) || ' total installs' AS TEXT)
UNION ALL
SELECT '9 tier-std naive rpi == headline rpi (max abs diff, 2 query paths)',
       CAST((SELECT ROUND(MAX(ABS(a - b)), 6) FROM (
             WITH inst AS (
               SELECT device_id, acquisition_channel AS channel,
                      country_tier AS tier, install_date
               FROM player_profile
               WHERE install_date BETWEEN '2026-01-01' AND '2026-03-31'),
             dev AS (
               SELECT i.channel, i.tier, i.device_id,
                      COALESCE(SUM(CASE WHEN p.usd_amount > 0
                                        THEN p.usd_amount END), 0) AS rev30
               FROM inst i
               LEFT JOIN purchase_dedup p ON p.device_id = i.device_id
                AND julianday(p.tx_dstr) - julianday(i.install_date) >= 0
                AND julianday(p.tx_dstr) - julianday(i.install_date) < 30
               GROUP BY i.channel, i.tier, i.device_id),
             path_dev AS (          -- direct: one row per device
               SELECT channel, 1.0 * SUM(rev30) / COUNT(*) AS rpi
               FROM dev GROUP BY channel),
             path_cell AS (         -- via channel x tier cells, installs-weighted
               SELECT channel, 1.0 * SUM(cell_rev) / SUM(cell_n) AS rpi
               FROM (SELECT channel, tier, SUM(rev30) AS cell_rev,
                            COUNT(*) AS cell_n
                     FROM dev GROUP BY channel, tier)
               GROUP BY channel)
             SELECT d.channel, d.rpi AS a, c.rpi AS b
             FROM path_dev d JOIN path_cell c USING (channel))) AS TEXT),
       '0.0'
UNION ALL
SELECT '10 retention by month: Jan-Mar d7 retained sums to pooled cells',
       CAST((SELECT SUM(n_d7) FROM (
             SELECT c.install_month, c.channel,
                    SUM(EXISTS (SELECT 1 FROM active_days a
                        WHERE a.device_id=c.device_id
                          AND a.day_id=CAST(strftime('%Y%m%d',
                              DATE(c.install_date,'+7 day')) AS INT))) n_d7
             FROM (SELECT device_id, acquisition_channel channel,
                          install_date, substr(install_date,1,7) install_month
                   FROM player_profile
                   WHERE install_date BETWEEN '2026-01-01' AND '2026-03-31') c
             GROUP BY c.install_month, c.channel)) AS TEXT),
       CAST((SELECT SUM(d7_retained) FROM (
             SELECT channel,
                    SUM(EXISTS (SELECT 1 FROM active_days a
                        WHERE a.device_id=c.device_id
                          AND a.day_id=CAST(strftime('%Y%m%d',
                              DATE(c.install_date,'+7 day')) AS INT))) d7_retained
             FROM (SELECT device_id, acquisition_channel channel, install_date
                   FROM player_profile
                   WHERE install_date BETWEEN '2026-01-01' AND '2026-03-31') c
             GROUP BY c.channel)) AS TEXT);
