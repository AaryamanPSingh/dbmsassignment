-- ============================================================================
-- DBMS Lab End-Sem — Deliverable 2: Deep dive (a)
--               "ARPDAU is falling. Fix it."
--
-- Run with:  python3 scripts/run_deliverable2.py
--
-- Question (brief): comparing the first 30 days of the window to the last 30,
-- overall ARPDAU is down ~16%, yet every country_tier is flat or improving.
-- Explain what is happening and recommend what the business should do.
--
-- Conventions carried over unchanged from deliverable 1 (see the header of
-- sql/deliverable1.sql for the full rationale):
--   D1  event_ts zero-padded at load time
--   D2  purchases deduplicated by purchase_id (purchase_dedup view)
--   D3  gross revenue = positive usd_amount on deduplicated rows
--   D4  active = player_day row OR a purchase that day (active_days view)
--   D5  ad_view shifted -8h to local dates (ad_local view)
--
-- Period definitions (the brief's own framing):
--   P1 = first 30 days = 2026-01-01 .. 2026-01-30  (day_id 20260101..20260130)
--   P2 = last  30 days = 2026-04-01 .. 2026-04-30  (day_id 20260401..20260430)
--
-- Method note (from the brief): countries are too sparse for stable ARPDAU
-- trends, so all headline analysis is at country_tier level (4 tiers).
--
-- Decomposition method: exact symmetric (Kitagawa) shift-share. For each tier
-- with share of active device-days s and ARPDAU r:
--   mix_t    = (s2 - s1) * (r1 + r2) / 2      (composition effect)
--   within_t = (r2 - r1) * (s1 + s2) / 2      (rate effect)
--   sum over tiers of (mix_t + within_t) == (blended ARPDAU P2 - P1) exactly,
-- with no interaction residual — so the waterfall sums to the headline number.
-- ============================================================================

-- @setup
DROP TABLE IF EXISTS purchase_dedup;
DROP TABLE IF EXISTS day_map;
DROP TABLE IF EXISTS active_days;
DROP TABLE IF EXISTS ad_local;
DROP TABLE IF EXISTS period_dd;
DROP TABLE IF EXISTS period_rev;
DROP TABLE IF EXISTS tier_period;
DROP TABLE IF EXISTS period_metric;

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

-- Calendar helper: SQLite date functions reject bare YYYYMMDD integers (they
-- are not a supported time-value format), so integer day_ids are converted via
-- this map before any date arithmetic — including Monday-week bucketing.
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

-- D4: active device-days (player_day UNION positive-purchase days)
CREATE TEMP TABLE active_days AS
SELECT device_id, activity_date AS day_id FROM player_day
UNION
SELECT device_id, tx_date FROM purchase_dedup WHERE usd_amount > 0;
CREATE INDEX idx_act ON active_days(device_id, day_id);

-- D5: ad interactions on local game dates (needed for the engagement check)
CREATE TEMP TABLE ad_local AS
SELECT device_id,
       DATE(event_ts, '-8 hours')              AS local_date,
       CAST(strftime('%Y%m%d', DATE(event_ts, '-8 hours')) AS INT) AS local_day,
       status,
       ad_daily_count,
       ad_daily_cap
FROM ad_view;
CREATE INDEX idx_adl ON ad_local(device_id, local_day);

-- Period-scoped building blocks (P1/P2 defined once, here)
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
       usd_amount,
       sale_flag
FROM purchase_dedup
WHERE tx_date BETWEEN 20260101 AND 20260130
   OR tx_date BETWEEN 20260401 AND 20260430;
CREATE INDEX idx_prev ON period_rev(pid, tx_date);

-- Period x tier metrics: the single source every tier query reads
CREATE TEMP TABLE tier_period AS
WITH dd AS (
    SELECT pd.pid,
           r.country_tier AS tier,
           COUNT(*)       AS active_dd
    FROM period_dd pd
    JOIN player_profile r USING (device_id)
    GROUP BY pd.pid, r.country_tier
),
rv AS (
    SELECT pr.pid,
           r.country_tier AS tier,
           COUNT(DISTINCT CASE WHEN pr.usd_amount > 0
                               THEN pr.device_id || ':' || pr.tx_date END) AS pur_dd,
           SUM(CASE WHEN pr.usd_amount > 0 THEN pr.usd_amount ELSE 0 END)  AS gross
    FROM period_rev pr
    JOIN player_profile r USING (device_id)
    GROUP BY pr.pid, r.country_tier
)
SELECT dd.pid,
       dd.tier,
       dd.active_dd,
       COALESCE(rv.pur_dd, 0)    AS pur_dd,
       COALESCE(rv.gross, 0.0)   AS gross
FROM dd
LEFT JOIN rv USING (pid, tier);

-- Period totals (independently aggregated — used by checks to catch any
-- silent drift between the tier table and the headline)
CREATE TEMP TABLE period_metric AS
SELECT pid,
       (SELECT COUNT(*) FROM period_dd  WHERE pid = m.pid) AS active_dd,
       (SELECT COUNT(DISTINCT CASE WHEN usd_amount > 0
                                   THEN device_id || ':' || tx_date END)
        FROM period_rev WHERE pid = m.pid)                 AS pur_dd,
       (SELECT COALESCE(SUM(CASE WHEN usd_amount > 0
                                 THEN usd_amount ELSE 0 END), 0)
        FROM period_rev WHERE pid = m.pid)                 AS gross
FROM (SELECT DISTINCT pid FROM period_dd) m;


-- @2a_headline
-- First 30 vs last 30 days: ARPDAU and the identity
--     ARPDAU = payer share (device-days) x revenue per purchasing device-day.
-- Also the ratio trap in one row: revenue vs active device-days growth.
SELECT CASE pid WHEN 1 THEN 'P1 first30' ELSE 'P2 last30' END AS period,
       active_dd,
       ROUND(gross, 2)                                          AS gross,
       ROUND(gross / active_dd, 4)                              AS arpdau,
       pur_dd,
       ROUND(100.0 * pur_dd / active_dd, 2)                     AS payer_pct,
       ROUND(gross / pur_dd, 2)                                 AS arppu_per_purch_dd,
       ROUND(100.0 * (gross / active_dd)
             / LAG(gross / active_dd) OVER (ORDER BY pid) - 100, 1)
                                                                AS arpdau_chg_pct,
       ROUND(100.0 * gross / LAG(gross) OVER (ORDER BY pid) - 100, 1)
                                                                AS gross_chg_pct,
       ROUND(100.0 * active_dd / LAG(active_dd) OVER (ORDER BY pid) - 100, 1)
                                                                AS active_dd_chg_pct,
       ROUND(100.0 * pur_dd / LAG(pur_dd) OVER (ORDER BY pid) - 100, 1)
                                                                AS pur_dd_chg_pct
FROM period_metric
ORDER BY pid;


-- @2a_by_tier
-- The brief's split: per country_tier, P1 vs P2. Share via window function,
-- change vs prior period via LAG. Flat-or-improving inside every tier while
-- shares move is the Simpson's-paradox pattern the question is about.
SELECT tier,
       CASE pid WHEN 1 THEN 'P1 first30' ELSE 'P2 last30' END AS period,
       active_dd,
       ROUND(100.0 * active_dd / SUM(active_dd) OVER (PARTITION BY pid), 1)
                                                               AS share_pct,
       ROUND(gross, 2)                                         AS gross,
       ROUND(gross / active_dd, 4)                             AS arpdau,
       ROUND(100.0 * pur_dd / active_dd, 2)                    AS payer_pct,
       ROUND(gross / NULLIF(pur_dd, 0), 2)                     AS arppu_per_purch_dd,
       ROUND(100.0 * (gross / active_dd)
             / LAG(gross / active_dd) OVER (PARTITION BY tier ORDER BY pid) - 100, 1)
                                                               AS arpdau_chg_pct,
       ROUND(100.0 * (1.0 * pur_dd / active_dd)
             / LAG(1.0 * pur_dd / active_dd)
               OVER (PARTITION BY tier ORDER BY pid) - 100, 1) AS payer_pct_chg_pct
FROM tier_period
ORDER BY tier, pid;


-- @2a_decomposition
-- Exact shift-share split of the blended ARPDAU change into "who is playing"
-- (mix) and "how well each tier monetises" (within). Rows sum to the
-- headline delta; the TOTAL row is what the waterfall chart is built from.
WITH piv AS (
    SELECT tier,
           MAX(CASE WHEN pid = 1 THEN 1.0 * active_dd
                    / (SELECT SUM(active_dd) FROM tier_period WHERE pid = 1) END) AS s1,
           MAX(CASE WHEN pid = 2 THEN 1.0 * active_dd
                    / (SELECT SUM(active_dd) FROM tier_period WHERE pid = 2) END) AS s2,
           MAX(CASE WHEN pid = 1 THEN 1.0 * gross / active_dd END)                AS r1,
           MAX(CASE WHEN pid = 2 THEN 1.0 * gross / active_dd END)                AS r2
    FROM tier_period
    GROUP BY tier
),
parts AS (
    SELECT tier, s1, s2, r1, r2,
           (s2 - s1) * (r1 + r2) / 2.0 AS mix,
           (r2 - r1) * (s1 + s2) / 2.0 AS within
    FROM piv
)
SELECT tier,
       ROUND(r1, 4)                                  AS arpdau_p1,
       ROUND(r2, 4)                                  AS arpdau_p2,
       ROUND(100.0 * s1, 1)                          AS share_p1_pct,
       ROUND(100.0 * s2, 1)                          AS share_p2_pct,
       ROUND(mix, 5)                                 AS mix_effect,
       ROUND(within, 5)                              AS within_effect,
       ROUND(mix + within, 5)                        AS delta
FROM parts
UNION ALL
SELECT 'TOTAL',
       ROUND((SELECT gross / active_dd FROM period_metric WHERE pid = 1), 4),
       ROUND((SELECT gross / active_dd FROM period_metric WHERE pid = 2), 4),
       100.0,
       100.0,
       ROUND((SELECT SUM(mix)    FROM parts), 5),
       ROUND((SELECT SUM(within) FROM parts), 5),
       ROUND((SELECT SUM(mix + within) FROM parts), 5);


-- @2a_counterfactual
-- The same decomposition in money terms leadership can use, evaluated at P2's
-- scale (283k+ active device-days):
--   actual world            = P1 rate + mix + within
--   no-mix-shift world      = P1 rate + within      (P1 tier shares held)
--   no-within-change world  = P1 rate + mix         (P1 tier rates held)
-- The gap between actual and no-mix-shift is what the mix move "cost" in the
-- last 30 days; the gap vs no-within-change is what better tier monetisation
-- "added".
WITH p AS (
    SELECT (SELECT gross / active_dd FROM period_metric WHERE pid = 1) AS r1,
           (SELECT gross / active_dd FROM period_metric WHERE pid = 2) AS r2,
           (SELECT active_dd        FROM period_metric WHERE pid = 2) AS dd2,
           (SELECT gross            FROM period_metric WHERE pid = 2) AS rev2
),
d AS (
    SELECT (SELECT SUM(mix) FROM (
                SELECT (s2 - s1) * (r1 + r2) / 2.0 AS mix FROM (
                    SELECT tier,
                           MAX(CASE WHEN pid = 1 THEN 1.0 * active_dd
                                / (SELECT SUM(active_dd) FROM tier_period WHERE pid = 1) END) s1,
                           MAX(CASE WHEN pid = 2 THEN 1.0 * active_dd
                                / (SELECT SUM(active_dd) FROM tier_period WHERE pid = 2) END) s2,
                           MAX(CASE WHEN pid = 1 THEN 1.0 * gross / active_dd END) r1,
                           MAX(CASE WHEN pid = 2 THEN 1.0 * gross / active_dd END) r2
                    FROM tier_period GROUP BY tier)))                        AS mix,
           (SELECT SUM(within) FROM (
                SELECT (r2 - r1) * (s1 + s2) / 2.0 AS within FROM (
                    SELECT tier,
                           MAX(CASE WHEN pid = 1 THEN 1.0 * active_dd
                                / (SELECT SUM(active_dd) FROM tier_period WHERE pid = 1) END) s1,
                           MAX(CASE WHEN pid = 2 THEN 1.0 * active_dd
                                / (SELECT SUM(active_dd) FROM tier_period WHERE pid = 2) END) s2,
                           MAX(CASE WHEN pid = 1 THEN 1.0 * gross / active_dd END) r1,
                           MAX(CASE WHEN pid = 2 THEN 1.0 * gross / active_dd END) r2
                    FROM tier_period GROUP BY tier)))                        AS within
),
scen AS (
    SELECT '1 actual (P2 mix, P2 rates)'        AS scenario, p.r2          AS arpdau, p.rev2 AS revenue
    FROM p
    UNION ALL
    SELECT '2 no mix shift (P1 shares held)', p.r1 + d.within, (p.r1 + d.within) * p.dd2
    FROM p, d
    UNION ALL
    SELECT '3 no within change (P1 rates held)', p.r1 + d.mix, (p.r1 + d.mix) * p.dd2
    FROM p, d
)
SELECT scenario,
       ROUND(arpdau, 4)                                   AS arpdau,
       ROUND(revenue, 0)                                  AS revenue_at_p2_scale,
       ROUND(revenue - (SELECT revenue FROM scen WHERE scenario LIKE '1%'), 0)
                                                           AS vs_actual_dollars,
       ROUND(100.0 * arpdau / (SELECT arpdau FROM scen WHERE scenario LIKE '1%') - 100, 1)
                                                           AS vs_actual_pct
FROM scen
ORDER BY scenario;


-- @2a_installs_by_tier
-- Supply side: where do actives come from? Installs inside each period window,
-- by tier, with shares — the ramp should be heavily tier-4.
SELECT CASE WHEN install_date BETWEEN '2026-01-01' AND '2026-01-30' THEN 'P1 first30'
            WHEN install_date BETWEEN '2026-04-01' AND '2026-04-30' THEN 'P2 last30'
       END                                                AS period,
       country_tier                                        AS tier,
       COUNT(*)                                            AS installs,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (
             PARTITION BY CASE WHEN install_date BETWEEN '2026-01-01' AND '2026-01-30'
                               THEN 1 ELSE 2 END), 1)      AS share_pct
FROM player_profile
WHERE install_date BETWEEN '2026-01-01' AND '2026-01-30'
   OR install_date BETWEEN '2026-04-01' AND '2026-04-30'
GROUP BY 1, country_tier
ORDER BY period, tier;


-- @2a_installs_month_tier
-- Install mix by calendar month (the ramp's shape), share within month.
SELECT substr(install_date, 1, 7)                          AS install_month,
       country_tier                                        AS tier,
       COUNT(*)                                            AS installs,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (
             PARTITION BY substr(install_date, 1, 7)), 1)  AS share_of_month_pct
FROM player_profile
GROUP BY install_month, tier
ORDER BY install_month, tier;


-- @2a_dd_age
-- Who is in each period's DAU: installs made during the period vs older
-- players. If P2's tier-4 device-days are dominated by fresh installs, the
-- mix shift is UA inflow, not existing players deteriorating.
SELECT pd.pid,
       r.country_tier AS tier,
       CASE
         WHEN r.install_date >= (CASE pd.pid WHEN 1 THEN '2026-01-01'
                                             ELSE '2026-04-01' END)
              THEN 'A installed during period'
         WHEN r.install_date >= DATE(CASE pd.pid WHEN 1 THEN '2026-01-01'
                                                 ELSE '2026-04-01' END, '-30 days')
              THEN 'B age 1-30 days'
         ELSE     'C age 31+ days'
       END                                                  AS age_bucket,
       COUNT(*)                                             AS active_dd,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY pd.pid, r.country_tier), 1)
                                                            AS share_of_tier_period_pct
FROM period_dd pd
JOIN player_profile r USING (device_id)
GROUP BY pd.pid, r.country_tier, age_bucket
ORDER BY pd.pid, tier, age_bucket;


-- @2a_channel
-- Which acquisition channel the actives (and revenue) come from, P1 vs P2.
SELECT pd.pid,
       r.acquisition_channel AS channel,
       COUNT(*)              AS active_dd,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY pd.pid), 1)
                              AS share_pct,
       ROUND(COALESCE(v.gross, 0), 2)                       AS gross,
       ROUND(COALESCE(v.gross, 0) / COUNT(*), 4)            AS arpdau
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


-- @2a_channel_tier
-- Channel x tier x period device-day shares — did a paid channel drive the
-- tier-4 mix shift?
SELECT pd.pid,
       r.acquisition_channel AS channel,
       r.country_tier        AS tier,
       COUNT(*)              AS active_dd,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY pd.pid), 2)
                              AS share_of_period_pct
FROM period_dd pd
JOIN player_profile r USING (device_id)
GROUP BY pd.pid, channel, tier
ORDER BY pd.pid, channel, tier;


-- @2a_retention_tier
-- Engagement by tier (same install-week cohorts and same cell-maturity rule
-- as deliverable 1b): is tier-4 as "cheap as it is low-spending"? A cell is
-- populated only if install_date+N lies inside [2026-01-01, 2026-04-30] for
-- every player in the cohort-tier cell, else NA (right-censored recent
-- cohorts, left-censored pre-2026 installs); all-NA rows are dropped.
WITH cohort AS (
    SELECT device_id,
           country_tier AS tier,
           install_date,
           DATE(install_date,
                '-' || ((CAST(strftime('%w', install_date) AS INT) + 6) % 7)
                || ' days') AS week_start
    FROM player_profile
),
grid AS (
    SELECT tier, week_start,
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
    GROUP BY tier, week_start
),
flags AS (
    SELECT grid.*,
           DATE(fi, '+1 day')  >= '2026-01-01' AND DATE(li, '+1 day')  <= '2026-04-30' AS p1,
           DATE(fi, '+7 day')  >= '2026-01-01' AND DATE(li, '+7 day')  <= '2026-04-30' AS p7,
           DATE(fi, '+14 day') >= '2026-01-01' AND DATE(li, '+14 day') <= '2026-04-30' AS p14,
           DATE(fi, '+30 day') >= '2026-01-01' AND DATE(li, '+30 day') <= '2026-04-30' AS p30
    FROM grid
)
SELECT tier, week_start, installs,
       CASE WHEN p1  THEN ROUND(100.0 * n_d1  / installs, 1) END AS d1_pct,
       CASE WHEN p7  THEN ROUND(100.0 * n_d7  / installs, 1) END AS d7_pct,
       CASE WHEN p14 THEN ROUND(100.0 * n_d14 / installs, 1) END AS d14_pct,
       CASE WHEN p30 THEN ROUND(100.0 * n_d30 / installs, 1) END AS d30_pct
FROM flags
WHERE p1 OR p7 OR p14 OR p30
ORDER BY week_start, tier;


-- @2a_ltv30_proxy
-- Revenue side of the "should we buy more tier-4 installs" decision, using
-- only what telemetry can support: installs 2026-01-01..2026-03-31 (full
-- 30-day follow-up fits inside the extract window — no right censoring) and
-- revenue strictly within each install's first 30 days. Pre-2026 installs are
-- excluded (their first days predate the window — left censoring).
WITH inst AS (
    SELECT device_id, country_tier AS tier, install_date
    FROM player_profile
    WHERE install_date BETWEEN '2026-01-01' AND '2026-03-31'
),
first30 AS (
    SELECT i.tier,
           COUNT(DISTINCT i.device_id)                        AS installs,
           COUNT(DISTINCT CASE WHEN p.usd_amount > 0
                               THEN p.device_id END)          AS payers_30d,
           COALESCE(SUM(CASE WHEN p.usd_amount > 0 THEN p.usd_amount ELSE 0 END), 0) AS rev_first30
    FROM inst i
    LEFT JOIN purchase_dedup p
           ON p.device_id = i.device_id
          AND julianday(p.tx_dstr) - julianday(i.install_date) >= 0
          AND julianday(p.tx_dstr) - julianday(i.install_date) < 30
    GROUP BY i.tier
)
SELECT tier,
       installs,
       payers_30d,
       ROUND(100.0 * payers_30d / installs, 2)      AS payer_rate_30d_pct,
       ROUND(rev_first30, 2)                        AS rev_first30,
       ROUND(rev_first30 / installs, 3)             AS revenue_per_install_30d
FROM first30
ORDER BY tier;


-- @2a_window_sensitivity
-- Is "-16%" an artefact of the exact 30-day cut? Recompute first-N vs last-N
-- for several N. The decline should persist at every window length.
WITH daily AS (
    SELECT a.day_id,
           COUNT(*)            AS dau,
           COALESCE(MAX(p.rev), 0) AS gross
    FROM active_days a
    LEFT JOIN (SELECT tx_date,
                      SUM(CASE WHEN usd_amount > 0
                               THEN usd_amount ELSE 0 END) AS rev
               FROM purchase_dedup
               GROUP BY tx_date) p ON p.tx_date = a.day_id
    GROUP BY a.day_id
),
bounds AS (
    SELECT 28 AS n, 20260101 AS f0,
           CAST(strftime('%Y%m%d', DATE('2026-01-01', '+27 days')) AS INT) AS f1,
           CAST(strftime('%Y%m%d', DATE('2026-04-30', '-27 days')) AS INT) AS l0,
           20260430 AS l1
    UNION ALL
    SELECT 30, 20260101,
           CAST(strftime('%Y%m%d', DATE('2026-01-01', '+29 days')) AS INT),
           CAST(strftime('%Y%m%d', DATE('2026-04-30', '-29 days')) AS INT),
           20260430
    UNION ALL
    SELECT 35, 20260101,
           CAST(strftime('%Y%m%d', DATE('2026-01-01', '+34 days')) AS INT),
           CAST(strftime('%Y%m%d', DATE('2026-04-30', '-34 days')) AS INT),
           20260430
    UNION ALL
    SELECT 60, 20260101,
           CAST(strftime('%Y%m%d', DATE('2026-01-01', '+59 days')) AS INT),
           CAST(strftime('%Y%m%d', DATE('2026-04-30', '-59 days')) AS INT),
           20260430
)
SELECT b.n AS window_days,
       (SELECT SUM(dau)   FROM daily d WHERE d.day_id BETWEEN b.f0 AND b.f1) AS first_dd,
       (SELECT SUM(gross) FROM daily d WHERE d.day_id BETWEEN b.f0 AND b.f1) AS first_rev,
       (SELECT SUM(dau)   FROM daily d WHERE d.day_id BETWEEN b.l0 AND b.l1) AS last_dd,
       (SELECT SUM(gross) FROM daily d WHERE d.day_id BETWEEN b.l0 AND b.l1) AS last_rev,
       ROUND((SELECT SUM(gross) FROM daily d WHERE d.day_id BETWEEN b.l0 AND b.l1)
           / (SELECT SUM(dau)   FROM daily d WHERE d.day_id BETWEEN b.l0 AND b.l1), 4)
                                                                           AS last_arpdau,
       ROUND((SELECT SUM(gross) FROM daily d WHERE d.day_id BETWEEN b.f0 AND b.f1)
           / (SELECT SUM(dau)   FROM daily d WHERE d.day_id BETWEEN b.f0 AND b.f1), 4)
                                                                           AS first_arpdau,
       ROUND(100.0 *
             ((SELECT SUM(gross) FROM daily d WHERE d.day_id BETWEEN b.l0 AND b.l1)
            / (SELECT SUM(dau)   FROM daily d WHERE d.day_id BETWEEN b.l0 AND b.l1))
           / ((SELECT SUM(gross) FROM daily d WHERE d.day_id BETWEEN b.f0 AND b.f1)
            / (SELECT SUM(dau)   FROM daily d WHERE d.day_id BETWEEN b.f0 AND b.f1))
           - 100, 1)                                                       AS arpdau_chg_pct
FROM bounds b
ORDER BY b.n;


-- @2a_tier_platform
-- Robustness: does "flat within tier" survive splitting by platform too? If
-- some tier x platform cells decline, mix still explains the total (the
-- identity holds at any level), but the "no cell is deteriorating" claim
-- would need qualifying.
WITH dd AS (
    SELECT pd.pid, r.country_tier AS tier, r.platform,
           COUNT(*) AS active_dd
    FROM period_dd pd JOIN player_profile r USING (device_id)
    GROUP BY pd.pid, r.country_tier, r.platform
),
rv AS (
    SELECT pr.pid, r.country_tier AS tier, r.platform,
           SUM(CASE WHEN usd_amount > 0 THEN usd_amount ELSE 0 END) AS gross
    FROM period_rev pr JOIN player_profile r USING (device_id)
    GROUP BY pr.pid, r.country_tier, r.platform
)
SELECT dd.tier, dd.platform, dd.pid, dd.active_dd,
       ROUND(COALESCE(rv.gross, 0), 2)                      AS gross,
       ROUND(COALESCE(rv.gross, 0) / dd.active_dd, 4)       AS arpdau,
       ROUND(100.0 * (COALESCE(rv.gross, 0) / dd.active_dd)
             / LAG(COALESCE(rv.gross, 0) / dd.active_dd)
               OVER (PARTITION BY dd.tier, dd.platform ORDER BY dd.pid) - 100, 1)
                                                            AS arpdau_chg_pct
FROM dd
LEFT JOIN rv ON rv.pid = dd.pid AND rv.tier = dd.tier AND rv.platform = dd.platform
ORDER BY dd.tier, dd.platform, dd.pid;


-- @2a_sale_density
-- Potential confound: are the two periods' revenue shapes different because
-- of sale cadence (13 sale days vs 18 in the calendar-month view)?
SELECT pid,
       COUNT(DISTINCT CASE WHEN sale_flag = 1 THEN tx_date END) AS sale_days,
       COUNT(DISTINCT tx_date)                                  AS days_with_tx,
       ROUND(SUM(CASE WHEN usd_amount > 0 THEN usd_amount ELSE 0 END), 2) AS gross,
       ROUND(SUM(CASE WHEN sale_flag = 1 AND usd_amount > 0
                      THEN usd_amount ELSE 0 END), 2)           AS sale_gross,
       ROUND(100.0 * SUM(CASE WHEN sale_flag = 1 AND usd_amount > 0
                              THEN usd_amount ELSE 0 END)
             / NULLIF(SUM(CASE WHEN usd_amount > 0
                               THEN usd_amount ELSE 0 END), 0), 1)
                                                                 AS sale_rev_share_pct
FROM period_rev
GROUP BY pid
ORDER BY pid;


-- @2a_ad_engagement
-- Context for the recommendation: rewarded-ad engagement (D5-shifted) per
-- active device-day by tier. No ad revenue exists in this extract — this is
-- an economy cost / engagement signal only (per the brief).
WITH comp AS (
    SELECT device_id, local_day,
           SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed
    FROM ad_local
    GROUP BY device_id, local_day
)
SELECT pd.pid,
       r.country_tier AS tier,
       COUNT(*)                          AS active_dd,
       SUM(COALESCE(c.completed, 0))     AS completed_ads,
       ROUND(100.0 * SUM(COALESCE(c.completed, 0)) / COUNT(*), 1)
                                         AS completed_per_100_active_dd
FROM period_dd pd
JOIN player_profile r USING (device_id)
LEFT JOIN comp c ON c.device_id = pd.device_id AND c.local_day = pd.day_id
GROUP BY pd.pid, r.country_tier
ORDER BY pd.pid, tier;


-- @2a_daily_mix
-- Day x tier series (60 days x 4 tiers) for the share-shift and
-- constant-mix charts; the chart script applies 7-day rolling sums.
SELECT pd.pid,
       pd.day_id,
       r.country_tier AS tier,
       COUNT(*)       AS dd,
       COALESCE(v.gross, 0.0) AS gross
FROM period_dd pd
JOIN player_profile r USING (device_id)
LEFT JOIN (
    SELECT pid, tx_date, r.country_tier AS tier,
           SUM(CASE WHEN usd_amount > 0 THEN usd_amount ELSE 0 END) AS gross
    FROM period_rev JOIN player_profile r USING (device_id)
    GROUP BY pid, tx_date, r.country_tier
) v ON v.pid = pd.pid AND v.tx_date = pd.day_id AND v.tier = r.country_tier
GROUP BY pd.pid, pd.day_id, r.country_tier
ORDER BY pd.day_id, tier;


-- @2a_channel_tier_arpdau
-- Scrutiny drill-down: the brief's "every tier improves" is a tier-level
-- claim — at channel x tier granularity some cells decline. This table shows
-- which, and whether any single cell is large enough to overturn the story.
WITH dd AS (
    SELECT pd.pid, r.acquisition_channel AS channel, r.country_tier AS tier,
           COUNT(*) AS active_dd
    FROM period_dd pd JOIN player_profile r USING (device_id)
    GROUP BY pd.pid, r.acquisition_channel, r.country_tier
),
rv AS (
    SELECT pr.pid, r.acquisition_channel AS channel, r.country_tier AS tier,
           SUM(CASE WHEN pr.usd_amount > 0 THEN pr.usd_amount ELSE 0 END) AS gross
    FROM period_rev pr JOIN player_profile r USING (device_id)
    GROUP BY pr.pid, r.acquisition_channel, r.country_tier
)
SELECT dd.channel, dd.tier, dd.pid, dd.active_dd,
       ROUND(COALESCE(rv.gross, 0), 2)                    AS gross,
       ROUND(COALESCE(rv.gross, 0) / dd.active_dd, 4)     AS arpdau,
       ROUND(100.0 * (COALESCE(rv.gross, 0) / dd.active_dd)
             / LAG(COALESCE(rv.gross, 0) / dd.active_dd)
               OVER (PARTITION BY dd.channel, dd.tier ORDER BY dd.pid) - 100, 1)
                                                            AS arpdau_chg_pct
FROM dd
LEFT JOIN rv ON rv.pid = dd.pid AND rv.channel = dd.channel AND rv.tier = dd.tier
ORDER BY dd.channel, dd.tier, dd.pid;


-- @2a_weekly_mix
-- Install-week x tier summary of the same series (compact form for tables).
-- Week bucketing goes through day_map (integer day_ids are not valid
-- SQLite time-values, so date arithmetic must convert them first).
WITH dd AS (
    SELECT pd.pid, m.week_start, r.country_tier AS tier,
           COUNT(*) AS active_dd
    FROM period_dd pd
    JOIN player_profile r USING (device_id)
    JOIN day_map m ON m.day_id = pd.day_id
    GROUP BY pd.pid, m.week_start, r.country_tier
),
rv AS (
    SELECT pr.pid, m.week_start, r.country_tier AS tier,
           SUM(CASE WHEN pr.usd_amount > 0 THEN pr.usd_amount ELSE 0 END) AS gross
    FROM period_rev pr
    JOIN player_profile r USING (device_id)
    JOIN day_map m ON m.day_id = pr.tx_date
    GROUP BY pr.pid, m.week_start, r.country_tier
)
SELECT dd.week_start, dd.tier, dd.active_dd,
       ROUND(COALESCE(rv.gross, 0), 2)                    AS gross,
       ROUND(COALESCE(rv.gross, 0) / dd.active_dd, 4)     AS arpdau,
       ROUND(100.0 * dd.active_dd
             / SUM(dd.active_dd) OVER (PARTITION BY dd.week_start), 1)
                                                           AS share_pct
FROM dd
LEFT JOIN rv ON rv.pid = dd.pid AND rv.week_start = dd.week_start AND rv.tier = dd.tier
ORDER BY dd.week_start, dd.tier;


-- @checks_d2
-- Reconciliation: the brief's "sanity-check totals against each other".
SELECT '1 decomposition identity: mix + within vs actual (ARPDAU delta)' AS check_item,
       CAST(ROUND((SELECT SUM(x) FROM (
           SELECT (s2 - s1) * (r1 + r2) / 2.0 + (r2 - r1) * (s1 + s2) / 2.0 AS x FROM (
               SELECT tier,
                      MAX(CASE WHEN pid = 1 THEN 1.0 * active_dd
                           / (SELECT SUM(active_dd) FROM tier_period WHERE pid = 1) END) s1,
                      MAX(CASE WHEN pid = 2 THEN 1.0 * active_dd
                           / (SELECT SUM(active_dd) FROM tier_period WHERE pid = 2) END) s2,
                      MAX(CASE WHEN pid = 1 THEN 1.0 * gross / active_dd END) r1,
                      MAX(CASE WHEN pid = 2 THEN 1.0 * gross / active_dd END) r2
               FROM tier_period GROUP BY tier))), 6) AS TEXT) AS a,
       CAST(ROUND((SELECT gross / active_dd FROM period_metric WHERE pid = 2)
                - (SELECT gross / active_dd FROM period_metric WHERE pid = 1), 6) AS TEXT) AS b
UNION ALL
SELECT '2 tier table sums to headline: P1 active_dd',
       CAST((SELECT SUM(active_dd) FROM tier_period WHERE pid = 1) AS TEXT),
       CAST((SELECT active_dd FROM period_metric WHERE pid = 1) AS TEXT)
UNION ALL
SELECT '3 tier table sums to headline: P2 gross',
       CAST(ROUND((SELECT SUM(gross) FROM tier_period WHERE pid = 2), 2) AS TEXT),
       CAST(ROUND((SELECT gross FROM period_metric WHERE pid = 2), 2) AS TEXT)
UNION ALL
SELECT '4 tier shares sum to 100% in each period',
       CAST((SELECT ROUND(100.0 * SUM(active_dd)
                    / (SELECT SUM(active_dd) FROM tier_period WHERE pid = 1), 4)
             FROM tier_period WHERE pid = 1) AS TEXT)
       || ' / ' ||
       CAST((SELECT ROUND(100.0 * SUM(active_dd)
                    / (SELECT SUM(active_dd) FROM tier_period WHERE pid = 2), 4)
             FROM tier_period WHERE pid = 2) AS TEXT),
       '100 / 100'
UNION ALL
SELECT '5 brief claim: every tier flat or improving (P2 >= P1 ARPDAU)',
       CAST((SELECT COUNT(*) FROM (
             SELECT tier,
                    MAX(CASE WHEN pid = 1 THEN gross * 1.0 / active_dd END) r1,
                    MAX(CASE WHEN pid = 2 THEN gross * 1.0 / active_dd END) r2
             FROM tier_period GROUP BY tier) WHERE r2 >= r1) AS TEXT),
       '4 of 4'
UNION ALL
SELECT '6 gross revenue: all-window total vs periods + outside (D1 cross-check)',
       CAST((SELECT ROUND(SUM(CASE WHEN usd_amount > 0 THEN usd_amount ELSE 0 END), 2)
             FROM purchase_dedup) AS TEXT),
       CAST(ROUND((SELECT ROUND(SUM(CASE WHEN usd_amount > 0 THEN usd_amount ELSE 0 END), 2)
             FROM purchase_dedup
             WHERE tx_date < 20260101 OR tx_date > 20260430
                OR (tx_date > 20260130 AND tx_date < 20260401))
           + (SELECT SUM(gross) FROM period_metric), 2) AS TEXT)
UNION ALL
SELECT '7 installs: all-window total vs periods + outside',
       CAST((SELECT COUNT(*) FROM player_profile) AS TEXT),
       CAST((SELECT COUNT(*) FROM player_profile
             WHERE install_date < '2026-01-01'
                OR install_date > '2026-04-30'
                OR (install_date > '2026-01-30' AND install_date < '2026-04-01'))
           + (SELECT COUNT(*) FROM player_profile
              WHERE install_date BETWEEN '2026-01-01' AND '2026-01-30'
                 OR install_date BETWEEN '2026-04-01' AND '2026-04-30') AS TEXT)
UNION ALL
SELECT '8 counterfactual identity: P1 + mix + within = P2 ARPDAU',
       CAST(ROUND((SELECT gross / active_dd FROM period_metric WHERE pid = 1)
                + (SELECT SUM(x) FROM (
                       SELECT (s2 - s1) * (r1 + r2) / 2.0 AS x FROM (
                           SELECT tier,
                           MAX(CASE WHEN pid = 1 THEN 1.0 * active_dd
                                    / (SELECT SUM(active_dd) FROM tier_period WHERE pid = 1) END) s1,
                                  MAX(CASE WHEN pid = 2 THEN 1.0 * active_dd
                                    / (SELECT SUM(active_dd) FROM tier_period WHERE pid = 2) END) s2,
                                  MAX(CASE WHEN pid = 1 THEN 1.0 * gross / active_dd END) r1,
                                  MAX(CASE WHEN pid = 2 THEN 1.0 * gross / active_dd END) r2
                           FROM tier_period GROUP BY tier)) )
                + (SELECT SUM(x) FROM (
                       SELECT (r2 - r1) * (s1 + s2) / 2.0 AS x FROM (
                           SELECT tier,
                           MAX(CASE WHEN pid = 1 THEN 1.0 * active_dd
                                    / (SELECT SUM(active_dd) FROM tier_period WHERE pid = 1) END) s1,
                                  MAX(CASE WHEN pid = 2 THEN 1.0 * active_dd
                                    / (SELECT SUM(active_dd) FROM tier_period WHERE pid = 2) END) s2,
                                  MAX(CASE WHEN pid = 1 THEN 1.0 * gross / active_dd END) r1,
                                  MAX(CASE WHEN pid = 2 THEN 1.0 * gross / active_dd END) r2
                           FROM tier_period GROUP BY tier)) ), 6) AS TEXT),
       CAST(ROUND((SELECT gross / active_dd FROM period_metric WHERE pid = 2), 6) AS TEXT)
UNION ALL
SELECT '9 country_tier completeness (NULL tier check)',
       CAST((SELECT COUNT(*) FROM player_profile WHERE country_tier IS NULL) AS TEXT),
       '0';
