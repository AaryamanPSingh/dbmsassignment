# Deliverable 1 — Get to know the data, in SQL

**Scope.** Daily health by platform, install-week retention, spender behaviour,
ad engagement — plus the data-quality note. All numbers below come from
`sql/deliverable1.sql`, executed by `scripts/run_deliverable1.py`; every figure
cites its query section and output CSV so it can be re-derived.

**Reproduce from a clean checkout:**

```bash
python3 scripts/load_data.py            # CSVs -> telemetry.db (applies fix D1)
python3 scripts/run_deliverable1.py     # runs all SQL -> outputs/deliverable1/*.csv
python3 scripts/charts_deliverable1.py  # figures -> outputs/deliverable1/figs/
```

**Window.** 2026-01-01 to 2026-04-30 (120 days) for activity; installs are
observed from 2025-12-08 (earliest install visible in `player_profile`).

---

## 0. Definitions used everywhere (the numerator/denominator traps, stated up front)

| ID | Decision | Why |
|----|----------|-----|
| D1 | `event_ts` values with single-digit hours (`2026-01-01 6:58:57`) are zero-padded **at load time** | SQLite's `DATE()` returns NULL on them; 13% of rows would silently vanish from every date aggregate |
| D2 | Purchases **deduplicated by `purchase_id`** (15,426 → 15,304 rows, earliest `event_ts` kept) | 122 duplicate ids = $1,815.82 double-counted |
| D3 | **Gross revenue = positive `usd_amount` on deduplicated rows**; refunds reported separately; net = gross + refunds | 226 negative rows (refunds) are not sales |
| D4 | A device is **active** on a date iff it has a `player_day` row **or** a purchase that date | 2,449 deduplicated positive purchases ($35,732.51, 16.4% of gross) land on dates with no `player_day` row — a purchase proves the player was in the game |
| D5 | Ad timestamps are shifted **−8 h** to local game dates (`DATE(event_ts,'-8 hours')`) | raw ad hours 08:00–13:59 are empty; the shift maps 392,949/392,949 ad device-days onto `player_day` (vs 49.1% unshifted) |

**Revenue has four defensible totals** — we use the last one and say so:

| definition | amount |
|---|---|
| raw rows, positive only | $219,434.02 |
| raw rows, net of refunds | $216,159.30 |
| deduplicated, net of refunds | $214,343.48 |
| **deduplicated, positive only (gross, our D3)** | **$217,593.22** |

---

## 1. Data-quality note

Eight issues found, each with evidence, treatment, and impact. Issues 1, 4 and 5
are the ones that make plausible-looking-but-wrong numbers.

**Q1 — Single-digit-hour timestamps (13% of all rows).** `2026-01-01 6:58:57`
has no leading zero; SQLite `DATE()`/`strftime` return NULL on it, so those rows
silently drop out of every date-based join and grouping (and SQLite does not
error). *Treatment:* zero-pad at load (`scripts/load_data.py`). *Evidence it
worked:* `player_profile.first_purchase_date` now agrees with purchase-derived
first purchases for 11,054/11,054 payers (check 4). *If untreated:* daily
revenue/DAU undercounts concentrated in morning hours.

**Q2 — Refunds.** 228 raw rows (226 deduplicated) have negative `usd_amount`,
totalling −$3,274.72 raw / −$3,249.74 deduplicated. *Treatment:* D3 — gross
counts positives only; refunds reported as their own column (they are 1.5% of
gross). *If untreated:* revenue understated by ~$3.2k and a chargeback looks
like a repeat purchase (Q8's gap analysis excludes them).

**Q3 — Duplicate `purchase_id`.** 122 rows repeat an existing id (same device,
amount, day). *Treatment:* D2. *Impact:* $1,815.82 (0.8% of revenue) would be
double-counted; raw net $216,159.30 vs deduplicated $214,343.48 (check 2).

**Q4 — `player_day` under-covers purchase days (the big one).** 2,663 raw
purchase rows sit on device-days with **no** `player_day` row (deduplicated and
positive-only: 2,449 rows, **$35,732.51 = 16.4% of gross**). Not a timezone
sliver: purchase hours on those days span 06–23; none of the device-days has
same-day `currency_spend` either; distance to the nearest `player_day` row is
1 day for 1,031 device-days, 2 days for 758, 3–7 days for 819 — i.e. `player_day`
gaps cluster around purchases, so the table under-records, rather than the
purchase being off by a day. *Treatment:* D4 (union rule). *Impact if ignored:*
keeping the revenue but using `player_day`-only DAU (variant A) inflates ARPDAU
from $0.3248 to $0.3260 and counts purchasers that are missing from the
denominator; inner-joining revenue to `player_day` (variant B) throws away
$35.7k of revenue. No platform-day ends up with $0 DAU and positive revenue
(0 cells), so the damage is silent rather than a divide-by-zero — which is
exactly why it still "looks plausible".

**Q5 — Ad timestamps run 8 h ahead of every other table.** Raw ad hours
08:00–13:59 are completely empty (0 rows all window), and rows exist only in
hours 00–07 and 14–23 — a signature of a fixed offset, not of player behaviour.
Unshifted, only 227,810 of 463,952 ad device-days (49.1%) line up with a
`player_day` row; shifted −8 h, 392,949/392,949 = **100%** (check 6, query 1d3).
`currency_spend` needs no shift (0 mismatches), so the offset is ad-specific.
*Treatment:* D5.

**Q6 — 48-hour ad telemetry outage.** Raw ad rows stop at 2026-03-05 07:59 and
resume 2026-03-07 08:00 (query 1d5) — after the D5 shift that is exactly local
**2026-03-05 and 2026-03-06 with zero ad rows** while `player_day` was normal
both days (DAU 4,994 / 4,979, playtime 102k / 104k minutes) and purchases and
`currency_spend` continued (108 purchases on Mar 6). Both days trip the
`<60% of trailing 7-day average` flag in 1d2 and nowhere else does. *Treatment:*
kept in the series as explicit zeros and flagged — they are missing measurement,
not missing players; excluded from any statement about ad-behaviour trends.

**Q7 — Install volume is not flat.** Weekly installs run 507 (week of
2025-12-08) → ~2,200/week Jan–Feb → 6,543/week of 2026-04-20, a 13× ramp
(query 1b). *Impact:* cohort denominators swell with immature cohorts, payer-rate
comparisons across months are confounded by follow-up length (Q8), and the
platform/geo mix of DAU shifts — relevant to the ARPDAU decline in 1a.

**Q8 — Right/left censoring and small artefacts.**
- *"Never paid" is not a lifetime number:* share never paying rises monotonically
  with recency — Jan installs 75.9% → Apr installs 93.7% (1c2c) — because the
  window ends before recent installs get a chance to pay. We report it by
  follow-up maturity, never as one blended figure.
- **110 payers (1.3%) have a first purchase dated before `install_date`**
  (114 rows total): negative time-to-first-purchase. Bucketed separately (1c2)
  and excluded from median/percentiles, not silently dropped.
- **1,114 installs (1.4%) never appear in `player_day` at all** — none of them
  purchased; they stay in retention denominators as inactive.
- **17,747 devices have `subscription`-granted currency but no purchase row** —
  subscription billing flows outside the `purchase` table, so purchase-based
  payer counts (11,054) are IAP payers only; do not "fix" them by unioning
  `currency_spend`.
- 45 `player_day` rows have zero playtime; 114 purchases pre-date install.

**Reconciliation:** 11 checks in `outputs/deliverable1/checks_reconciliation.csv`
— all pass, including three identities built specifically for this deliverable:
(day × platform) DAU sums to total active device-days (669,864 = 669,864);
positive purchase rows = payers + repeat-purchase pairs (15,078 = 11,054 + 4,024);
exactly 2 ad-dark days (20260305, 20260306).

---

## 2. Findings

### 2a. Daily health by platform (`1a_daily_health`, `1a_monthly_summary`, fig1a)

120 days × 2 platforms = 240 rows; 669,864 active device-days; gross $217,593.

| month | platform | active player-days | gross $ | ARPDAU $ | payer share |
|---|---|---|---|---|---|
| Jan | Android | 54,870 | 15,393 | 0.2805 | 1.86% |
| Jan | iOS | 31,324 | 14,855 | 0.4742 | 3.33% |
| Feb | Android | 72,214 | 19,526 | 0.2704 | 1.87% |
| Feb | iOS | 41,805 | 22,200 | 0.5310 | 3.47% |
| Mar | Android | 125,772 | 30,311 | 0.2410 | 1.67% |
| Mar | iOS | 60,152 | 31,660 | 0.5263 | 3.52% |
| Apr | Android | 206,896 | 47,878 | 0.2314 | 1.56% |
| Apr | iOS | 76,831 | 35,770 | 0.4656 | 3.42% |

- iOS monetises ~1.7–2.2× Android on ARPDAU and ~2× on payer share; Android
  carries ~73% of active player-days by April.
- **Android ARPDAU falls 17.5% Jan→Apr (0.2805 → 0.2314) and payer share
  1.86% → 1.56% while active player-days grow 3.8×**; iOS is roughly flat
  (−1.8%). Overall ARPDAU $0.3248, blended payer share 2.23% of device-days.
- Revenue is **spiky on an ~weekly cadence** (fig1a, bottom) — and it is sales:
  58 of 120 days carry `sale_flag` revenue, which is **39.2% of gross**, and
  every one of the top-8 revenue days is 100% sale-flagged. Spikes grow over
  time and hit both platforms on the same day.

### 2b. Install-week retention (`1b_retention_cohorts`, fig1b)

**Cell rule (one line):** cell N is populated only if `install_date + N` falls
inside [2026-01-01, 2026-04-30] for *every* player in the cohort, otherwise NA —
so recent cohorts lose D30/D14/D7 from the right (right-censored) and Dec 2025
cohorts lose D1/D7 from the left (left-censored, their early life predates the
window); rows with all four cells NA are omitted. Denominator = all installs in
the week, including the 1,114 never-active devices.

| cell | cohorts with data | mean | min–max |
|---|---|---|---|
| D1 | 16 | **47.8%** | 46.2–50.4% |
| D7 | 16 | **25.6%** | 24.0–26.9% |
| D14 | 16 | **19.7%** | 18.8–21.4% |
| D30 | 16 | **14.2%** | 12.4–16.8% |

Retention is **remarkably stable across a 13× install ramp** — D1 spread is
only 46.2–50.4% with no trend in either direction, and D7/D14/D30 wobble inside
±1.5pp of their means. The April ARPDAU decline (2a) is therefore *not* a
retention problem; it points at monetisation mix, which is a deliverable-2
candidate.

### 2c. Spender behaviour (`1c1`–`1c3b`)

**Revenue concentration (1c1)** — the denominator changes the headline, so both
are reported:

| population | top 1% | top 10% | top 50% |
|---|---|---|---|
| payers only (11,054) | 9.3% | 47.9% | 90.2% |
| all installed players (80,295) | 40.2% | 96.9% | 100.0% |

The bottom half of payers contributes 9.8% of revenue; a small core (top 1,105
payers) takes almost half.

**Time to first purchase (1c2, 1c2b)** — installs on/after 2026-01-01 only
(64,295; earlier installs are left-censored for "first"):

- ever paid **12.9%** (8,269 payers); 87.1% have not paid *yet* — see Q8.
- **median 13 days**, p75 32, p90 57, max 117; same-day 7.6%; 36.7% within
  7 days, 52.5% within 14 days. 110 negative-day artefacts excluded (Q8).

**Never-pay by maturity (1c2c):** Jan 75.9% → Feb 79.5% → Mar 86.9% → Apr 93.7%
— monotonic in follow-up length, so only the Jan/Feb rows approximate a true
lifetime non-payer rate.

**Repeat purchase gap (1c3, 1c3b)** — window function `LAG`, positive rows only,
buyers with ≥ 2 purchases:

- 2,476 repeat buyers (22.4% of payers), 4,024 consecutive pairs.
- **median gap 15.3 days** (mean 22.7; p25 6.4, p75 32.8, p90 54.8).
- Distribution: same-day 6.1%, 1–2 d 8.0%, 3–6 d 12.9%, 7–13 d 18.5%,
  14–29 d 26.3%, 30–59 d 20.3%, 60+ d 8.0% — a broad monthly-ish rhythm.

### 2d. Ad engagement (`1d1`–`1d5`, fig1d)

**Cap structure.** Two cap values exist: 5 (294,861 ad device-days) and 8
(98,088). No device-day ever shows both values — 45,551 devices move 5 → 8
*between* days, 25,037 stay at 5, 3,454 stay at 8. Devices that moved have a
much higher subscription rate (35.8% vs 18.9% for always-5, 1d1b) — association
only; movers have also simply played longer.

**Cap-hit share (1d1)** — grouped per device-day, by cap:

| cap | ad days | watch days (≥1 completed) | hit by counter | hit by completed |
|---|---|---|---|---|
| 5 | 294,861 | 262,057 | **1.27%** of ad days | **0.54%** of watch days |
| 8 | 98,088 | 87,016 | **0.02%** of ad days | **0.001%** of watch days |

The cap is almost never binding. Two traps here:
1. `ad_daily_count` also increments on *started* (not completed) ads — the
   counter exceeds completed views on 26.8% of ad-days, and 62.6% of
   counter-based "hits" did not actually complete the cap in completed views.
   Reporting the raw counter as "cap hit" overstates it ~2.4×.
2. Per-device rather than per-device-day would mix caps: 45,551 devices change
   cap mid-window.

**Daily series (1d2, fig1d).** 120 days; completed ads track DAU tightly and
**completed per 100 DAU rises 73 → 87** over the window (growing ad engagement,
strongest in April). Exactly two days trip the `<60% of trailing 7-day avg`
flag — the Mar 5–6 outage (Q6) — and no genuine behavioural dip exists in the
window.

**Offset proof (1d3):** raw 49.1% device-day match vs shifted 100%.

---

## 3. What this sets up

- **Deliverable 2 candidates** (to be chosen after this profiling): (a) the
  Android ARPDAU −17.5% / payer-share decline against flat retention and 13×
  install growth — mix shift vs within-segment decline (Simpson's-paradox
  style; the brief hints country tiers are flat), or (b) sale incrementality
  using the weekly revenue spikes + `sale_flag` in `purchase`.
- Q4 (player_day gaps around purchases) and Q6 (ad outage) must be footnoted
  in any deck chart that touches those days.

## 4. Files

| file | contents |
|---|---|
| `sql/deliverable1.sql` | all queries, sections `@setup`, `@1a…@1d5`, `@checks_reconciliation` |
| `scripts/run_deliverable1.py` | executes sections, writes CSVs + `summary.md` |
| `scripts/charts_deliverable1.py` | fig1a–fig1d |
| `outputs/deliverable1/*.csv` | 16 result tables (240-row daily health, 20-cohort grid, 120-day ad series, …) |
| `outputs/deliverable1/summary.md` | headline tables in one place |
