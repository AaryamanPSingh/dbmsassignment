# Deliverable 4b (optional) — the value of a new install

**Scope.** Predict the in-app revenue a new install will generate in its first
**90 days**, using only what is known by the **end of day 7**. UA would use the
ranking to decide how much to bid for an install, so **ranking matters more
than average accuracy**. This is the optional 4b brief; 4a (14-day churn) is in
`writeup/deliverable4.md`.

All numbers come from `sql/deliverable4b.sql`, executed by
`scripts/run_deliverable4b.py`; figures come from
`scripts/charts_deliverable4b.py`. Every claim cites its CSV.

**Reproduce from a clean checkout:**

```bash
python3 scripts/load_data.py             # CSVs -> telemetry.db
python3 scripts/run_deliverable4b.py     # SQL + model -> outputs/deliverable4/4b_*.csv
python3 scripts/charts_deliverable4b.py  # figures -> outputs/deliverable4/figs/fig4b*.png
```

---

## 0. The binding constraint: who can be labelled at all

The extract is 120 days (2026-01-01 → 2026-04-30). A complete 90-day label needs
`install_date + 89 ≤ 2026-04-30`; a complete day-7 feature window needs
`install_date ≥ 2026-01-01`. Only installs from **2026-01-01 to 2026-01-30**
satisfy both.

| population | count | can be used? |
|---|---:|---|
| players in `player_profile` | 80,295 | — |
| installs before 2026-01-01 | 16,000 | no: days 0-6 unobserved (left-truncated) |
| installs 2026-01-01…2026-01-30 | **9,494** | **yes** |
| installs 2026-01-31…2026-04-30 | 54,801 | no: days 60-89 unobserved (right-censored) |

That is **14.8% of in-window installs** and 11.8% of all players. A naive
`SUM(usd_amount)` over `[install, install+90d]` for every profile row would
silently label 70,801 installs with a partial or empty window; the Feb–Apr
cohorts would look almost revenue-free because most of their 90 days fall
after the extract. Checks 1, 3, 4, 6 and 9 in `checks_d4b.csv` guard this.

The surviving cohort is also **not a random slice of traffic**:

| mix | labelable (Jan 1–30) | all in-window installs |
|---|---:|---:|
| organic | 45.8% | 27.0% |
| paid_social | 39.0% | 23.9% |
| paid_video | 15.2% | 49.1% |
| country_tier 4 | 18.1% | 46.4% |

January installs arrive at ~315/day; April at ~895/day (computed from
`player_profile`). So this is a model of **January's organic/tier-1–2-heavy
traffic**, not of the paid_video-heavy traffic UA is buying now. That is the
first thing to say in any readout, and it is why the recommendation is a capped
pilot rather than "use this to bid".

**One-line caveat:** a 90-day revenue label is right-censored by the extract;
it is not lifetime value. Players who would have paid on day 100 are counted at
$0.

## 1. Target, features and split

| decision | definition | why |
|---|---|---|
| **Population** | installs with `install_date` in `[2026-01-01, 2026-01-30]` | the only fully observed 90-day cohort, and the only one with a complete first week |
| **Label `revenue_90`** | gross IAP revenue on days 0–89 after install: positive, deduplicated `usd_amount` (D2/D3) | "how much revenue a new install generates in its first 90 days" |
| **`payer_90`** | `1` iff `revenue_90 > 0` | 77.0% of test installs are zero; a plain regression on dollars would predict near-zero for everyone |
| **Features** | days 0–6 only | the brief's "by the end of day 7" |
| **Split** | train Jan 1–14, validation Jan 15–20 (L2 only), test Jan 21–30 | out of time, because UA deploys forward; the test window is untouched |

| split | installs | payers | payer rate | mean 90d | p90 90d | week-1 share of 90d revenue |
|---|---:|---:|---:|---:|---:|---:|
| train (Jan 1–14) | 4,401 | 995 | 22.61% | $5.09 | $9.99 | 19.2% |
| validation (Jan 15–20) | 1,944 | 414 | 21.30% | $4.33 | $9.99 | 16.8% |
| **test (Jan 21–30)** | **3,149** | **724** | **22.99%** | **$4.51** | **$9.99** | **20.9%** |

The 20.9% week-1 share is important: a fifth of the target is already earned
inside the feature window. That is legitimate (it is known by day 7), but it
means part of any "prediction" is reading money already on the table, not
forecasting.

**Features (20):** first-week active days and recorded days, sessions,
playtime, last level; first-week revenue and purchase count; completed ads and
ad days; premium/social/grind spend-event counts and currency value; days to
first purchase; one-hot platform, country tier and acquisition channel. Spend,
ad and purchase counts are `log1p`; numeric features are standardised on the
fitting rows only.

## 2. Model

77% of installs never pay, and among payers the distribution is heavy-tailed
(median payer $9.99, p90 $54.98, max $251.96 in the full labelable cohort; the
test cohort tops out at $209.97, with 21 installs above $100). So a single regression is the wrong tool. The model
is **two-part**:

1. **P(payer in 90 days)** — L2 logistic regression, Newton/IRLS, λ chosen on
   the validation log loss (λ = 10).
2. **E[revenue | payer]** — ridge on `log1p(revenue_90)`, fitted on payers
   only, λ chosen on validation log-RMSE (λ = 0.1), with a Duan smearing factor
   (1.84) to undo the log transform.

Score = `P(payer) × E[revenue | payer]`, i.e. an expected 90-day value per
install. No scikit-learn: the repo's NumPy/SciPy convention is kept, and the
logistic IRLS code follows 4a.

**Why not rank by predicted revenue directly?** With 77% zeros, a squared-error
fit spends all its capacity predicting zero. **Why report the amount model
separately?** Because it turns out not to earn its place (§3.3) — a finding
worth stating rather than hiding inside an ensemble.

## 3. Results (`4b_metrics`, `4b_baselines`, `4b_amount_metrics`)

### 3.1 Headline

| sample | n | payers | payer AUC | payer PR-AUC | Brier | Spearman | top-10% lift | top-10% revenue capture |
|---|---:|---:|---|---|---:|---|---:|---:|
| train (in-sample) | 6,345 | 1,409 | 0.736 | 0.575 | 0.133 | 0.348 | 4.56× | 45.6% |
| validation (out-of-time) | 1,944 | 414 | 0.723 | 0.533 | 0.133 | 0.320 | 4.11× | 41.0% |
| **test (out-of-time)** | **3,149** | **724** | **0.702 [0.676, 0.725]** | **0.549 [0.510, 0.579]** | **0.143** | **0.298 [0.261, 0.334]** | **4.34× [3.77, 4.98]** | **43.5%** |

Bootstrap intervals are 1,000 resamples of the test cohort. The model ranks
*potential payers* moderately well (AUC 0.70; PR-AUC 0.55 against a 23% base
rate, 2.39× baseline). The **revenue** ranking is much weaker (Spearman 0.30):
knowing who will pay is not the same as knowing who will pay a lot.

Targeting gain, highest predicted value first (`4b_lift`):

| top % | installs | score cutoff (expected $) | mean actual 90d revenue | revenue lift | share of all revenue | payer precision |
|---:|---:|---:|---:|---:|---:|---:|
| 5% | 157 | $10.56 | **$32.23** | 7.14× | 35.6% | 96.2% |
| 10% | 315 | $6.41 | $19.61 | 4.34× | 43.5% | 68.9% |
| 20% | 630 | $4.80 | $12.25 | 2.71× | 54.3% | 49.7% |
| 30% | 945 | $3.93 | $9.40 | 2.08× | 62.5% | 41.5% |
| 50% | 1,574 | $2.89 | $6.85 | 1.52× | 75.9% | 32.0% |
| all | 3,149 | — | $4.51 | 1.00× | 100% | 23.0% |

The top 5% is almost pure payer identification (96% pay); the top decile still
contains 31% non-payers. Revenue is extremely concentrated: 77.0% of installs
pay nothing, the 2.4% above $50 carry 46.7% of revenue (the 54 installs in the
$50–100 band alone carry 28.2%), and the top 10% of installs carry 85.7%
(fig4b1).

### 3.2 Calibration (`4b_calibration`, fig4b3)

- **Payer probability is close:** decile expected calibration error **2.06 pp**;
  the top decile is 68.0% predicted vs 69.8% observed.
- **Expected value is not:** the top decile is **$25.86 predicted vs $19.67
  observed** (over-predicted by 31%), the bottom decile is $0.94 vs $2.30
  (under-predicted). Mid-decile gaps are at most $1.22. Use the score for
  **ordering**, and use observed decile means — not predicted dollars — for any
  bid formula.

### 3.3 Does the amount stage earn its place? (the honest answer: no)

| model (test, ranking by …) | Spearman | top-10% capture | top-20% capture |
|---|---:|---:|---:|
| no skill | — | 8.5% | 16.6% |
| **first-week spend only** | **0.475** | 41.0% | 45.2% |
| first-week payer flag only | 0.474 | 41.0% | 45.2% |
| 90-day payer probability only | 0.300 | 43.8% | 54.4% |
| two-part expected value (full) | 0.298 | 43.5% | 54.3% |

Two uncomfortable facts:

1. **A one-line rule is a strong baseline.** Ranking by first-week spend has a
   *higher* global rank correlation (0.475 vs 0.298) than the model,because it puts first-week payers (only 25.0% of payers, but all certain) at the top.
   The model only pulls ahead in the **top 10–20% capture** (43.5% vs 41.0%;
   54.3% vs 45.2%), which is the part bidding actually uses — and even there
   the gain is modest.
2. **The amount stage adds nothing.** Payer probability alone scores 43.8% /
   54.4% at top-10/20, marginally better than the two-part score. The reason is
   in `4b_amount_metrics`: among payers, predicted amount has **Spearman 0.266**
   against actual revenue, **MAE $21.05** and **RMSE $36.46** on a mean test payer
   of $19.63. The amount model is close to worthless at the individual level; the
   two-part score is effectively "payer probability plus noise".

So the deliverable's real conclusion is narrower than the brief's framing:
**you can rank new installs by their probability of paying at all (AUC 0.70),
but this data does not support per-install revenue forecasts.** If the business
needs a dollar value, use cohort/segment averages, not individual predictions.

## 4. Where it works badly (`4b_segment_metrics`, fig4b4)

| segment | n | payer AUC | Spearman | top-10% lift | reading |
|---|---:|---:|---:|---:|---|
| country_tier 1 | 1,089 | 0.698 | 0.322 | 4.00× | best-value tier, ranking OK |
| country_tier 4 | 538 | 0.607 | **0.138** | 2.35× | nearly no within-tier signal |
| Android | 2,026 | 0.674 | 0.240 | 3.88× | weaker than iOS |
| iOS | 1,123 | 0.716 | 0.347 | 4.42× | strongest large segment |
| first-week payer = 0 | 2,968 | 0.651 | 0.199 | 2.26× | 543 of 724 payers; hard |
| first-week payer = 1 | 181 | — (all pay) | 0.588 | 2.96× | the only group whose *amount* ranks |
| install Jan 21–25 | 1,583 | 0.747 | 0.369 | 4.83× | |
| install Jan 26–30 | 1,566 | 0.654 | **0.226** | 3.91× | drift inside the test window |

- **75% of payers do not pay in week 1** (543/724). They are the hard part: the
  model's within-group Spearman is 0.20 and top-decile lift 2.26. The brief's
  warning that ranking matters more than average accuracy bites here.
- **Tier 4 is close to unrankable** in this cohort (Spearman 0.138), and its
  revenue is small ($2.04 mean). Do not spend modelling effort there; bid a flat
  low value.
- **Within-test drift** (0.369 → 0.226 between the first and last five days of
  January) is larger than sampling noise would suggest for these sample sizes.
  It says the relationship is unstable week to week, so retrain and re-evaluate
  often rather than fit once.
- **The amount model is only informative inside first-week payers** (Spearman
  0.588, top-10% mean $89.92 vs $30.41 overall). If you must forecast dollars,
  do it conditional on "already paid in week 1", where there is signal, and
  treat everyone else as a probability.

## 5. Use: how much to bid

For an install with predicted 90-day value `v̂`, a bid is worth it while

```
v̂ × margin  >  bid        ⇔        bid  <  margin × v̂
```

where `margin` includes platform fees and content cost, and `v̂` must cover all
revenue the install brings — **IAP only here, because ad revenue is not in the
extract**. Using the *observed* decile means (safer than the over-predicted
model dollars) and an illustrative 30% margin:

| bid on | observed mean 90d revenue | max bid at 30% margin | payer precision |
|---|---:|---:|---:|
| top 5% | $32.23 | **$9.67** | 96.2% |
| top 10% | $19.61 | $5.88 | 68.9% |
| top 20% | $12.25 | $3.68 | 49.7% |
| top 30% | $9.40 | $2.82 | 41.5% |
| top 50% | $6.85 | $2.06 | 32.0% |
| all installs | $4.51 | $1.35 | 23.0% |

Read this as a **ceiling, not a target**: 90-day IAP understates lifetime value
(no ad revenue, no revenue after day 90), and the top half of the ranking is
where the model is least calibrated. Concretely:

1. **Do not bid per install from the model's dollar output.** Bid from the
   decile's observed mean, with a margin haircut, and cap at the top 10–20%.
2. **Use the score to sort, not to price.** The payer-probability ranking is
   the defensible part; the amount stage should be dropped from the production
   score (`first-week payer` flag + logistic probability is simpler and scores
   the same).
3. **Treat this as a January-traffic model.** Re-fit on a window whose label
   period is complete before using it on today's paid_video-heavy traffic.
4. **Run it against a holdout.** The data are observational: ranking an install
   as high-value does not mean bidding on it creates incremental value. UA may
   be selecting users who would have installed anyway. Without a holdout you
   cannot tell selection from lift.

## 6. What this cannot tell you

1. **Only 30 days of installs are labelable** (14.8% of in-window installs). A
   longer extract is the single highest-value fix: it would buy a
   representative cohort, a real temporal test, and enough high-value payers to
   validate the tail.
2. **90 days is right-censored**; no revenue after 2026-04-30. The label is not
   LTV, and the recommendation cannot be scaled to a lifetime-value bid.
3. **No ad revenue, no margin, no cost data.** "Revenue" is IAP only, and
   without CAC by channel there is no ROI calculation — only a bid ceiling.
4. **Device stitching is ignored.** `original_device_id` links reinstalls, but
   revenue is attributed to whichever `device_id` purchased. A player who
   reinstalls may split their value across rows, which biases both label and
   features. 4a has the same limitation.
5. **No experiment.** The model is a ranking model, not a causal uplift model;
   value per *won* install is unidentified.
6. **The amount stage does not work.** Per-install dollar forecasts should not
   be shipped on this evidence; segment averages are the honest alternative.
7. **No hyperparameter/feature search beyond λ.** Deliberate, for
   interpretability; §3.3 and §4 show the ceiling is data, not model class.

## 7. Reconciliation and checks (`checks_d4b.csv`, 10/10)

| # | check | result |
|---|---|---|
| 1 | labelable population matches an independent count | 9,494 = 9,494 |
| 2 | one row per device | 0 duplicates |
| 3 | every install inside the labelable window | 0 violations |
| 4 | every feature/label window inside the extract | 0 violations |
| 5 | no NULLs in model features | 0 |
| 6 | `revenue_90` recomputed independently | $45,045 = $45,045 |
| 7 | split strictly temporal | Jan 14 < Jan 15 < Jan 20 < Jan 21 |
| 8 | first-week revenue never exceeds 90-day revenue | 0 violations |
| 9 | labelable + excluded = in-window installs | 9,494 + 54,801 = 64,295 |
| 10 | feature window ends day 6; label ends day 89 | 0 deviations |

Definitions D1–D4 are unchanged from deliverables 1–4a. All features come from
`[install, install+6]`; the label uses `[install, install+89]` purchases. The
overlap between the two windows is intentional and known: revenue in days 0–6
is part of the target and is already observed at decision time.

## 8. Files

| file | contents |
|---|---|
| `sql/deliverable4b.sql` | `@setup`, `@4b_base_build`, `@4b_cohort_build`, `@4b_cohort`, `@4b_cohort_profile`, `@checks_d4b` |
| `scripts/run_deliverable4b.py` | executes SQL, fits two-part model, writes metrics/calibration/lift/segments |
| `scripts/charts_deliverable4b.py` | fig4b1 concentration, fig4b2 lift, fig4b3 calibration, fig4b4 segment ranking |
| `outputs/deliverable4/4b_cohort.csv` | 9,494 labelable installs with first-week features and the 90-day label |
| `outputs/deliverable4/4b_split_summary.csv` | split ranges, payer rates, revenue distribution |
| `outputs/deliverable4/4b_metrics.csv` | payer AUC/PR/Brier, Spearman, lift with bootstrap CIs |
| `outputs/deliverable4/4b_baselines.csv` | no-skill, first-week spend, payer flag, payer-only, full model |
| `outputs/deliverable4/4b_amount_metrics.csv` | amount-model error and within-payer ranking |
| `outputs/deliverable4/4b_lift.csv` | expected-value targeting table |
| `outputs/deliverable4/4b_calibration.csv` | payer-probability and expected-revenue deciles |
| `outputs/deliverable4/4b_segment_metrics.csv` | AUC/Spearman/lift by channel, tier, platform, week and first-week payer |
| `outputs/deliverable4/4b_revenue_distribution.csv` | installs and revenue share by 90-day revenue bucket |
| `outputs/deliverable4/4b_coefficients.csv` | standardised coefficients for both stages |
| `outputs/deliverable4/4b_payer_lambda_selection.csv`, `4b_amount_lambda_selection.csv` | validation selection |
| `outputs/deliverable4/checks_d4b.csv` | 10 label/window/leakage checks |
| `outputs/deliverable4/figs/fig4b1–4b4` | deck-ready figures |
