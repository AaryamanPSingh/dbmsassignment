# Deliverable 4a — Predict which active players will stop playing

**Scope.** Predict, for every player active on a snapshot date, whether they
will have **no active day at all in the next 14 days**. The live-ops team wants
to spend a re-engagement offer, so the write-up covers the label, the
out-of-time evaluation, where the model is weak, and the offer-cost threshold
that decides whether targeting is worth it.

All numbers come from `sql/deliverable4.sql`, executed by
`scripts/run_deliverable4.py`; figures come from `scripts/charts_deliverable4.py`.
Every claim cites its CSV.

**Reproduce from a clean checkout:**

```bash
python3 scripts/load_data.py            # CSVs -> telemetry.db (applies fix D1)
python3 scripts/run_deliverable4.py     # SQL + model -> outputs/deliverable4/*.csv
python3 scripts/charts_deliverable4.py  # figures -> outputs/deliverable4/figs/
```

---

## 0. What "churn" means here, and why

| decision | definition | why |
|---|---|---|
| **Label** | `churn14 = 1` iff the player has **zero active days in `[t+1, t+14]`** | The live-ops question is "who will stop playing", not "who will skip day 14". D1's D14 retention (19.7% active *exactly* on day 14) would label ~80% of players churned; that is normal intermittent play, not a stopped player. Requiring **no return at all** gives a 15.1% base rate, which is the population an offer should address. |
| **Active day** | `player_day` row **or** a positive purchase that day (D4, unchanged) | A purchase proves the player was in the game. 196 snapshot actives are purchase-only; excluding them would mislabel real spenders as gone. |
| **Snapshot `t`** | a date on which the player is active; all features use `[t-13, t]` or earlier | Mirrors deployment: today's activity is known, tomorrow is not. |
| **Horizon** | 14 days, fixed | Matches the brief and a typical re-engagement offer cycle; long enough that "no return" is meaningful, short enough to act on. |
| **Eligible** | every player active on `t`, with `install_date <= t` | Directly answers "currently active players". No minimum tenure: pre-install days are genuine zeros and `tenure_days` is a feature. The 9 snapshot actives whose `install_date` is **after** the snapshot (Apr-08 only) are a data artefact and are excluded. |

**One-line caveat:** this labels a player churned if they do not return within
14 days; a player who returns on day 15 is counted as churned at day 14. It is
a fixed-horizon classification, not a survival model.

## 1. Snapshot design (`4a_snapshots`)

Four snapshots, spaced 28 days so that feature and outcome windows never
overlap. That avoids the same player-day contributing to two labels and keeps
the evaluation honest.

| snapshot | split | feature window | outcome window | eligible | churners | churn rate |
|---|---|---|---|---:|---:|---:|
| 2026-01-14 | train | 01-01…01-14 | 01-15…01-28 | 2,755 | 392 | 14.23% |
| 2026-02-11 | train | 01-29…02-11 | 02-12…02-25 | 3,921 | 642 | 16.37% |
| 2026-03-11 | validation | 02-26…03-11 | 03-12…03-25 | 5,514 | 857 | 15.54% |
| 2026-04-08 | **test** | 03-26…04-08 | 04-09…04-22 | 8,786 | 1,278 | 14.55% |

20,976 player-snapshots, 3,169 churners (15.11% pooled). The churn rate is
stable at 14–16%, despite the install ramp, because the population is
"players active today", not "players who installed in a given week".

**Churn is strongly a tenure phenomenon** (`4a_churn_baseline`): 3.1% for
0–6-day players, 6.9% for 7–13, 12.6% for 14–29, 17.2% for 30–59 and **31.3%
for 60+ days**. That single fact drives most of the model's ranking power and
is also why its within-tenure performance is weaker (§4.4).

## 2. Model and split

**Model.** L2-regularised logistic regression, fitted with Newton/IRLS in
NumPy (no scikit-learn dependency; the repo already has NumPy/SciPy). 22
predictors: tenure, level, 7-day and prior-7-day active days, sessions,
playtime, playtime/sessions per active day, ads per active day, lifetime and
14-day spend, days since purchase, completed ads/ad days, plus one-hot
platform, country tier and acquisition channel. Numeric predictors are
standardised on the fitting rows; spend and ad counts are `log1p`.

**Split.** Out of time, not random:

- **Train:** Jan-14 + Feb-11 (6,676 rows, 1,034 churners).
- **Validation:** Mar-11 (5,514 rows, 857 churners) — used **only** to pick the
  L2 penalty; λ = 10 minimised validation log loss (0.3770).
- **Test:** Apr-08 (8,786 rows, 1,278 churners) — untouched until the final
  evaluation.
- The final model is refit on **train + validation** with λ = 10, then scored
  once on April.

A random split would be wrong here: the same player can appear in several
snapshots, and the business deploys forward in time. Out-of-time evaluation
answers the deployment question, at the cost of being a harder test.

**The test set is a genuine distribution shift**, not a random holdout: paid_video
is 44.0% of test rows vs 15.4% of train, and tier 4 is 42.3% vs 18.5%. That is
exactly the April channel/tier ramp documented in D2/D3, and it is the main
reason test performance is below validation.

## 3. Results (`4a_metrics`, fig4a)

| sample | n | churners | AUC (95% CI) | PR-AUC (95% CI) | Brier | log loss |
|---|---:|---:|---|---|---:|---:|
| train (in-sample) | 12,190 | 1,891 | 0.775 | — | 0.1144 | 0.3695 |
| validation (out-of-time) | 5,514 | 857 | 0.770 [0.752, 0.787] | 0.364 [0.333, 0.398] | 0.1154 | 0.3734 |
| **test (out-of-time)** | **8,786** | **1,278** | **0.742 [0.728, 0.757]** | **0.333 [0.307, 0.359]** | **0.1124** | **0.3691** |
| no-skill baseline | 8,786 | 1,278 | 0.500 | 0.146 | 0.1243 | 0.4148 |

- **Ranking:** test AUC 0.742; PR-AUC 0.333 is **2.29×** the 14.55% base rate.
  The bootstrap CIs are sampling-noise intervals for one April snapshot.
- **Calibration:** Brier and log loss beat the base-rate baseline, and the
  mean calibration error across deciles is **2.16 pp**. It is not perfect:
  deciles 8–9 are under-predicted by 4.1–4.4 pp, while the top decile is
  over-predicted (47.3% predicted vs 40.2% observed, fig4b). Use the score for
  **ranking**, or recalibrate (Platt/isotonic) before quoting probabilities.

## 4. Where it works, and where it works badly

### 4.1 Targeting gain (`4a_thresholds`, fig4c)

On the untouched April snapshot, highest-risk first:

| top % targeted | score cutoff | precision | recall | lift vs random | flagged who do **not** churn |
|---:|---:|---:|---:|---:|---:|
| 5% | 0.459 | **46.9%** | 16.1% | 3.23× | 53.1% |
| 10% | 0.288 | 40.2% | 27.6% | 2.76× | 59.8% |
| 20% | 0.192 | 33.9% | 46.6% | 2.33× | 66.1% |
| 30% | 0.149 | 29.6% | 61.0% | 2.03× | 70.4% |
| 50% | 0.101 | 23.0% | 79.2% | 1.58× | 77.0% |

The top decile contains 2.76× as many churners as a random decile, but
**60% of the people it flags do not churn**. That is the unavoidable cost of a
15% base rate, and it is why the offer economics in §5 matter more than AUC.

### 4.2 What the model has learned (`4a_coefficients`, `4a_feature_profile`)

Churners are **older, higher-level and less active**: mean tenure 106 days vs
45 for retained players, level 13.9 vs 9.0, 1.65 vs 2.15 active days in the
last week, 30 vs 47 playtime minutes, 1.45 vs 2.57 completed ads. Payer share
is similar (8.3% vs 9.6%). This is a "content-complete veteran" profile, not a
monetisation problem.

Largest standardised coefficients (conditional associations, **not causal**):
tenure +0.62, prior-week active days +0.51, current-week sessions −0.29,
prior-week sessions −0.36, current-week playtime −0.19, 14-day spend −0.11,
completed ads −0.16, paid_social vs organic +0.11, paid_video vs organic
−0.09. Active days and sessions point in opposite directions because they are
conditional on each other: for a fixed session volume, activity spread across
more days means lower intensity. Do not read a single coefficient as "playing
more causes churn".

### 4.3 Does the rest of the feature set add anything? (`4a_baseline`)

| model | AUC | PR-AUC | Brier | log loss |
|---|---:|---:|---:|---:|
| no skill (train prevalence) | 0.500 | 0.147 | 0.1244 | 0.4151 |
| **tenure only (1 feature)** | **0.741** | **0.318** | **0.1159** | **0.3820** |
| full model (22 predictors) | 0.742 | 0.333 | 0.1124 | 0.3691 |

A one-variable tenure logistic gets **AUC 0.7409 vs 0.7424** for the full
model — a gain of 0.0015 — and **PR-AUC 0.318 vs 0.333**. The other 21
predictors add almost no ranking power. They do improve calibration and log
loss (Brier 0.1159 → 0.1124, log loss 0.382 → 0.369), so the full model is the
better probability estimate, but **the model is essentially a well-calibrated
tenure curve plus a small within-tenure ordering**. If the live-ops team wants
a rule it can audit in one line, a tenure cutoff is nearly as good; if it needs
probabilities for a cost formula, use the full model. Do not sell this as
personalised targeting it has not earned.

### 4.4 Segment performance (`4a_segment_metrics`, fig4d)

| segment | AUC | PR-AUC | churn rate |
|---|---:|---:|---:|
| tenure 0–6 | 0.623 | 0.055 | 3.6% |
| tenure 7–13 | 0.641 | 0.112 | 6.6% |
| tenure 14–29 | 0.670 | 0.209 | 12.4% |
| tenure 30–59 | 0.635 | 0.254 | 17.7% |
| tenure 60+ | 0.647 | 0.416 | 29.5% |
| tier 1 / 2 / 3 / 4 | 0.724 / 0.708 / 0.732 / 0.752 | 0.360 / 0.338 / 0.346 / 0.304 | 18.5 / 16.9 / 16.3 / 10.8% |
| Android / iOS | 0.747 / 0.728 | 0.319 / 0.361 | 13.6 / 16.9% |
| organic / paid_social / paid_video | 0.738 / 0.715 / 0.715 | 0.393 / 0.342 / 0.241 | 18.1 / 18.8 / 9.6% |

**This is the main weakness.** The overall AUC of 0.742 is flattered by
ranking *across* tenure groups; within any narrow tenure band the AUC falls to
0.62–0.67. Most of the model's value is "older players are more likely to
leave", a fact a tenure rule already captures. Within a tenure band it adds a
real but modest amount of ordering. It is weakest for the 0–6-day group, where
churn is rare (3.6%) and the model has almost no signal (AUC 0.623, PR-AUC
0.055). For new-player offers, do not rely on this model.

## 5. Where to set the threshold — the offer economics

Let:

- `c` = cost of one offer,
- `e` = offer's **incremental** retention effect among would-be churners,
- `V` = value of one retained player over the relevant lifetime.

Targeting a player with predicted churn probability `p` is worth it when

```
p × e × V  >  c        ⇔        p  >  c / (e × V)
```

This is the whole threshold rule. The model supplies `p`; the business must
supply `c`, `e` and `V` — none of which are in this extract.

**Break-even churn probability `p* = c/(e·V)`:**

| offer cost `c` | effect `e` | V = $25 | V = $50 | V = $100 |
|---:|---:|---:|---:|---:|
| $1.00 | 5% | 80% | 40% | 20% |
| $0.50 | 5% | 40% | 20% | 10% |
| $1.00 | 10% | 40% | 20% | 10% |

Read against §4.1: `p* = 40%` is roughly the **top 10%** cutoff (40.2%
observed precision, 28.8% score), and `p* = 20%` is roughly the **top 20%**
cutoff (19.2% score, 33.9% precision). So:

- **If a retained player is worth ~$50 and the offer costs ~$1 with a 5% lift,
  target the top ~10%.** Expected value per offer is only marginally positive
  (≈$0.00–0.20), so this is not a licence to scale spend.
- **If V ≈ $25, the break-even is 80%**, far above the top-5% cutoff (score
  0.459, observed precision 47%). Paid re-engagement is not viable at that
  value unless the offer is much cheaper or much more effective; only a tiny
  slice the model scores above 80% could clear the bar, and the top decile is
  already over-predicted.
- **If the offer is cheaper ($0.50) or more effective (10%), the top 20%
  clears the bar at V = $50.**

**Cost per incremental save** (illustrative: $1 offer, 5% effect):

| targeting | offers per save | cost per save |
|---|---:|---:|
| top 5% | 42.6 | $42.62 |
| top 10% | 49.8 | $49.80 |
| top 20% | 59.1 | $59.06 |
| random | 137.5 | $137.50 |

At a 5% effect, even the best decile produces only **2.0 saves per 100
offers**: 98 of 100 offers produce no incremental retention. The model triples
the saves per offer versus random targeting (2.35 vs 0.73 per 100 in the top
5%), but it cannot make a bad offer economics work. The recommendation is
therefore conditional, not "deploy the model":

1. **Do not use a single global cutoff.** Set `p* = c/(e·V)` per campaign and
   per segment (the model is weaker for new players and paid_video).
2. **Start with the top 10% as a pilot**, measure `e` with a holdout (offered
   vs not offered), and only scale if the measured `e` clears the break-even.
3. **Do not target the 0–6-day group with this model**; its AUC is 0.62 and
   churn is 3.6%. Onboarding is a separate problem.
4. **Recalibrate before using probabilities in a budget formula.** The top
   decile is over-predicted by ~7 pp; the mid-high deciles are under-predicted
   by ~4 pp. Re-fit on a rolling window or apply isotonic calibration.

## 6. What this cannot tell you

1. **The effect of the offer (`e`) is unknown and not identified here.** The
   data are observational; there is no holdout, no randomised offer, and no
   record of who received one. A model that ranks churn risk well can still
   produce no incremental retention if the offer does not change behaviour.
   The only way to fill this is an A/B or geo-holdout.
2. **`V` is unknown.** The extract has IAP revenue but no margin, no ad
   revenue, no subscription revenue, and no lifetime beyond 2026-04-30. A
   30-day revenue/install figure ($1.08–$3.49 by tier, D2) is **not** the value
   of a retained player over a realistic lifetime.
3. **`c` is unknown** — the offers may be in-game currency (low marginal cost)
   or paid rewards (real cost).
4. **One test snapshot.** The April snapshot is a different channel/tier mix
   from training (paid_video 44% vs 15%). Performance will drift with the UA
   mix; re-train and re-evaluate monthly, not once.
5. **14-day horizon only.** A player who returns on day 15 is labelled churned.
   If the business cares about 30/60-day return, the label and model must change.
6. **No survival/timing model.** A discrete classifier throws away *when*
   within the 14 days the player leaves; a hazard model would support
   time-to-offer decisions.
7. **No hyperparameter or feature search beyond λ.** That is deliberate: an
   interpretable logistic regression with a small, pre-specified feature set is
   easier to defend than a tuned black box. The ceiling is visible in §4.4.

## 7. Reconciliation and checks (`checks_d4.csv`, 11/11)

| # | check | result |
|---|---|---|
| 1 | snapshot count and split assignment | 4 snapshots / 3 splits |
| 2 | one row per (snapshot, device) | 0 duplicates |
| 3 | every outcome window inside the extract | 0 violations |
| 4 | label present and binary | 0 violations |
| 5 | no NULLs in model features | 0 |
| 6 | eligible rows = active snapshot rows minus pre-install artefacts | 20,976 = 20,976 |
| 7 | churners recomputed by an independent query | 3,169 = 3,169 |
| 8 | split order strictly temporal | 2026-02-11 < 2026-03-11 < 2026-04-08 |
| 9 | consecutive snapshots 28 days apart | 0 exceptions |
| 10 | purchase-only snapshot actives included by D4 | 196 (>0) |
| 11 | no feature window before extract start | 2026-01-01 |

Definitions D1–D5 are unchanged from D1–D3. The model dataset is built only
from `[snapshot-13, snapshot]`; churn uses only `(snapshot, snapshot+14]`.

## 8. Files

| file | contents |
|---|---|
| `sql/deliverable4.sql` | `@setup`, `@4a_snapshots`, `@4a_model_dataset_build` / `@4a_model_dataset`, `@4a_churn_baseline`, `@4a_feature_profile`, `@checks_d4` |
| `scripts/run_deliverable4.py` | executes SQL, fits logistic regression, writes metrics/calibration/thresholds/segments |
| `scripts/charts_deliverable4.py` | fig4a ROC/PR, fig4b calibration, fig4c gain, fig4d segment AUC |
| `outputs/deliverable4/4a_model_dataset.csv` | 20,976 labelled player-snapshots with all features |
| `outputs/deliverable4/4a_metrics.csv` | train/validation/test AUC, PR-AUC, Brier, log loss, bootstrap CIs |
| `outputs/deliverable4/4a_thresholds.csv` | precision, recall, lift, waste, offers per save, cost per save |
| `outputs/deliverable4/4a_break_even.csv` | `p* = c/(e·V)` grid |
| `outputs/deliverable4/4a_segment_metrics.csv` | AUC/AP by tenure, tier, platform, channel |
| `outputs/deliverable4/4a_calibration.csv` | decile calibration |
| `outputs/deliverable4/4a_coefficients.csv` | standardised coefficients and odds ratios |
| `outputs/deliverable4/checks_d4.csv` | 11 reconciliation/leakage checks |
| `outputs/deliverable4/figs/fig4a–4d` | deck-ready figures |
