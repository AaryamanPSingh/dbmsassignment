# Deliverable 3 — "Is one acquisition channel better than another?"

**Scope.** Compare `organic`, `paid_social` and `paid_video` on at least one
engagement and one revenue measure, each defined precisely; put a confidence
interval on the headline difference and call its significance; separate
"artefact" from "real but unresolvable at this sample size"; and say whether
the difference is big enough to move budget. All numbers come from
`sql/deliverable3.sql`, executed by `scripts/run_deliverable3.py`; every
claim cites its query section and CSV.

**Reproduce from a clean checkout:**

```bash
python3 scripts/load_data.py            # CSVs -> telemetry.db (applies fix D1)
python3 scripts/run_deliverable3.py     # SQL + bootstrap/z-tests -> outputs/deliverable3/*.csv
python3 scripts/charts_deliverable3.py  # figures -> outputs/deliverable3/figs/
```

---

## 0. Definitions and method (carried over unchanged from deliverables 1–2)

Decisions **D1–D5** (zero-padded timestamps; `purchase_id` dedup; gross =
positive `usd_amount`; active = `player_day` ∪ purchase days; ads shifted −8 h)
are reused verbatim, so D1–D3 numbers reconcile by construction (§6).
Channels are complete, no NULLs (check 4): organic 24,554 installs,
paid_social 21,705, paid_video 34,036.

**The four measures, stated once:**

| # | Measure | Definition | Why this one |
|---|---|---|---|
| R1 (headline) | **30-day IAP revenue per install** | installs 2026-01-01…03-31; gross deduplicated revenue in days `[install, install+30)`; mean across installs in the channel; **also reported tier-standardised** (direct standardisation to the pooled Jan–Mar install tier mix) | per-**install** cohort: immune to how big the channel's DAU got and when; every in-scope install has a full 30 days of follow-up inside the extract (no right-censoring); the standardised variant answers "same kind of player, different channel" |
| R2 | **30-day payer rate** | share of those installs with ≥1 gross purchase in `[install, install+30)`; also tier-standardised | separates "pays more" from "pays more often" |
| E1 | **D7 retention** | share of an install-week × channel cohort active exactly on `install_date+7`, **matured-cell rule from D1b verbatim**: the cell exists only if `install+7` lies inside 2026-01-01…04-30 for *every* install in the cohort | player-quality measure, unaffected by channel DAU growth; no censored denominators; broken out by install month to test calendar confounding |
| E2 | **Playtime minutes per recorded day** | `SUM(playtime_minutes) / recorded player_day rows` inside P1/P2, period-matched; also per tier | intensity of play among current players. Purchase-only device-days carry no recorded playtime and are **excluded** from this denominator (stated, not zero-filled) |
| X (exhibit only) | channel ARPDAU on device-days | gross / active device-days | kept *because* it is the obvious comparison and it is badly misleading — §2 |

Statistics: bootstrap 95% CIs (10,000 resamples, fixed seed) for the two
continuous measures — revenue per install is heavily skewed so its mean needs
resampling; **stratified** bootstrap (resample within channel × tier cells,
reweight to the pooled tier mix) for the standardised variants; device-level
resampling for playtime (days within a device are correlated); two-proportion
z-tests for the two proportions (D7, payer rate). All 18 pairwise results are
in `3g_significance.csv`; three pairwise comparisons per metric ⇒ a
multiple-comparison caveat applies (§5).

---

## 1. The naive comparison (the exhibit, `3a_channel_period`)

| period | organic | paid_social | paid_video |
|---|---|---|---|
| P1 first 30d (Jan) ARPDAU | $0.353 | $0.341 | **$0.385** |
| P2 last 30d (Apr) ARPDAU | $0.372 | $0.378 | **$0.210** |
| share of device-days P1→P2 | 46.7% → 28.0% | 38.5% → 23.6% | 14.8% → **48.5%** |

A reader comparing pooled channel ARPDAU (`3b_naive_vs_std`) concludes:
organic $0.366, paid_social $0.366, **paid_video $0.224 — 39% worse**.
That comparison is the trap the brief warns about, for two independent
reasons visible in the same section's siblings:

**Confound 1 — tier mix** (`3a_channel_tier`): paid_video's device-days skew
to the low-monetising tiers (D2: 76% of P2 paid_video actives are tier 4;
`3c_ltv30_channel_tier` shows 65% of its Jan–Mar installs are tier 4 vs 18%
of organic's). Tier-4 players earn ~$1.0–1.1 per install vs ~$3.4–3.8 for
tier 1.

**Confound 2 — calendar/timing** (`3a_channel_install_month`, fig3b): until
Feb 2026 paid_video was ~13–19% of monthly installs; it was 53.7% in March
and **69.2% in April**. Its DAU in P2 is dominated by a giant, young,
payer-immature ramp cohort, while organic's DAU spans the whole history.
ARPDAU inside a window mechanically penalises a channel whose players just
arrived (D1 Q8: never-pay rises with recency).

## 2. The adjusted ARPDAU comparison (`3b_naive_vs_std`, fig3a)

Direct standardisation: every channel reweighted to the *same* tier mix
(pooled P1+P2 tier shares of device-days), computed within each period so
the calendar comparison is like-for-like.

| period | organic raw → std | paid_social raw → std | paid_video raw → std |
|---|---|---|---|
| P1 (Jan) | 0.353 → 0.353 | 0.341 → 0.339 | 0.385 → 0.389 |
| P2 (Apr) | 0.372 → **0.293** | 0.378 → **0.284** | 0.210 → **0.297** |
| pooled | 0.366 → 0.304 | 0.366 → 0.300 | 0.224 → **0.319** |

**The headline gap does not just shrink — it flips sign.** Pooled,
tier-standardised ARPDAU makes paid_video the *best* channel (0.319 vs
0.304 organic), and inside January paid_video was already the best raw
channel (0.385) before any adjustment. What looks like "paid_video players
monetise 40% worse" is almost entirely *which* players (tier) and *when*
(April ramp) the naive metric happened to average over. Note the
standardisation also demotes organic and paid_social in P2: their DAU skews
to high-tier survivors, so their raw ARPDAU was flattered, not earned.

## 3. The headline revenue measures: naive gap vs adjusted gap (`3c_*`)

Because R1/R2 are per-install cohorts measured over a fixed 30 days, neither
confound inflates them the same way — but tier mix still matters, and it
matters almost as much. Jan–Mar installs (37,489 total; check 5):

| channel | installs | naive rev/install | **tier-std** | naive payer rate | **tier-std** |
|---|---|---|---|---|---|
| organic | 12,948 | **$2.4627** [2.269, 2.660] | $2.149 [1.98, 2.32] | 13.31% | **11.99%** |
| paid_social | 11,511 | **$2.2167** [2.030, 2.410] | $1.958 [1.79, 2.13] | 13.15% | **11.78%** |
| paid_video | 13,030 | **$1.5418** [1.386, 1.706] | $2.046 [1.79, 2.31] | 8.86% | **11.27%** |

**The naive gap is the trap; the adjusted gap is the answer**
(`3g_significance.csv`, fig3c):

| A − B | naive Δ rev/install | p | **tier-std Δ** | 95% CI | p |
|---|---|---|---|---|---|
| organic − paid_video | **+$0.921 (+59.7%)** | <1e-4 | **+$0.103 (+5.0%)** | [−0.212, +0.406] | **0.52** |
| paid_social − paid_video | **+$0.675 (+43.8%)** | <1e-4 | −$0.088 (−4.3%) | [−0.406, +0.221] | 0.58 |
| organic − paid_social | +$0.246 (+11.1%) | 0.076 | +$0.191 (+9.7%) | [−0.063, +0.436] | 0.13 |

**~89% of the famous "+60% revenue advantage" disappears when every channel
is scored on the same tier mix**, and what remains is not distinguishable
from zero. Payer rate behaves identically: the naive 4.45 pp gap
(p < 1e-26) shrinks to **0.72 pp [−0.20, 1.59], p = 0.12** after
standardisation. The per-tier table (`3c_ltv30_channel_tier`) shows why:
within tier 1, organic $3.75 vs paid_video $3.43 (−8.5%); within tier 4,
paid_video $1.10 vs organic $1.02 (**+8.3%**). paid_video is not buying
*worse* players — it is buying *tier-4* players, who behave like tier-4
players no matter which channel delivered them.

So the honest statement has two layers, and conflating them is the mistake
the brief is guarding against:

- **As bought (total effect):** organic returns $2.46/install vs paid_video
  $1.54 — that is real cash, +$0.92, and it is what a budget actually
  experiences *if CPIs are equal*.
- **Same player, different channel (per-player quality):** no resolvable
  difference on either revenue measure (all adjusted p ≥ 0.12). The as-bought
  gap is the channel's **tier targeting**, not its traffic quality.

## 4. The engagement measures survive adjustment (`3d_*`, `3e_*`)

These are the comparisons where a genuine channel difference *does* appear —
and both persist inside every stratum we can cut by.

**D7 retention** (matured cells only — `3d_retention_channel_pooled`):

| channel | matured installs | D7 | 95% CI |
|---|---|---|---|
| organic | 15,838 | 26.46% | [25.77, 27.15] |
| paid_social | 13,991 | 25.67% | [24.94, 26.39] |
| paid_video | 24,338 | 24.94% | [24.39, 25.48] |

organic − paid_video = **+1.53 pp** [+0.65, +2.40], p = 0.0006. Is this the
Feb–Mar calendar artefact (D1 Q7) or tier mix? No: `3d_retention_channel_month`
shows organic ahead of paid_video in **every** install month separately
(Jan +2.6 pp, Feb +1.4 pp, Mar +2.0 pp), and D1 established retention is
flat across tiers (~25% everywhere). organic − paid_social (+0.80 pp,
p = 0.12) and paid_social − paid_video (+0.73 pp, p = 0.11) are **not**
resolvable at this sample size. The ordering matches revenue ordering, which
is at least internally consistent — but the effect is 6% relative on a 25%
base.

**Playtime per recorded day** (`3e_playtime_channel`,
`3e_playtime_channel_tier`, device-bootstrap):

| channel | min/day | 95% CI | vs organic |
|---|---|---|---|
| organic | 19.36 | [19.24, 19.48] | — |
| paid_social | 18.71 | [18.58, 18.84] | −0.64 [−0.82, −0.47], p < 1e-4 |
| paid_video | 18.68 | [18.57, 18.78] | −0.68 [−0.85, −0.52], p < 1e-4 |

organic players play ~3.5% longer per day — and this one is **not** tier
composition either: inside every tier, organic leads (21.1–21.4 min/day
across tiers 1–4 vs paid_social 20.3–20.5 and paid_video 20.0–20.3,
`3e_playtime_channel_tier`). paid_social vs paid_video is +0.04 min
[−0.13, +0.20], p = 0.64: **the CI is narrow and centred on zero** — this is
resolved as "no meaningful difference", not merely "underpowered".

## 5. Significance ≠ business relevance; what would make it real

**Every pairwise comparison, sorted into the brief's bins** (fig3c):

| comparison | bin | evidence |
|---|---|---|
| channel ARPDAU (naive, pooled) | **artefact** | §2: sign flips under tier standardisation; within-January paid_video was already best raw |
| revenue/install & payer rate, naive | **artefact** | §3: +60% → +5% (p = 0.52) and 4.45 pp → 0.72 pp (p = 0.12) once tiers are equalised |
| organic vs paid_video on E1/E2 | **real, small** | CIs exclude zero, persist within every month and every tier — but +1.5 pp retention and +0.7 min/day are ~3–6% relative |
| organic vs paid_social on R1/R2/E1 | **real but underpowered** | +11% revenue, +0.8 pp D7 — all CIs cross zero (p = 0.08–0.13). Could be a genuine ordering we cannot resolve, or no difference at all |
| paid_social vs paid_video on E2 | **resolved: negligible** | CI [−0.13, +0.20] min/day rules out any meaningful playtime difference |
| residual tier-std revenue gaps | **real but underpowered** | adjusted CIs [−10%, +20%] cannot distinguish a small genuine edge from zero at n ≈ 37k with heavy skew |

Note the asymmetry the brief hints at: the *obvious* comparison (naive
ARPDAU, naive revenue) is the misleading one, while the differences that
survive adjustment are real but land in the "too small to resolve or too
small to matter" bins — with exactly one borderline case (organic vs
paid_social revenue, +11%, p = 0.076) sitting in "genuine but unprovable at
this sample size".

**Multiple comparisons:** 6 metrics × 3 pairs = 18 tests. The engagement
results (E1 organic−paid_video p = 0.0006; E2 both p < 1e-4) survive
Bonferroni (α = 0.0028). The naive revenue results would too — but they are
artefacts, which correction cannot fix (a biased estimate stays biased with a
tiny p-value; that is the whole point of §2–§3). The borderline
organic−paid_social revenue result (p = 0.076) is not significant even
uncorrected, and we do not claim it.

**What would be needed to conclude a difference is real rather than a
collection artefact:**

1. **Cost side — the missing input that decides the budget question.** The
   extract has no CPI/spend by channel (flagged in D2 §missing inputs). We
   can say organic returns $2.46/install and paid_video $1.54; we **cannot**
   say organic has the better *ROI* without cost per install. A channel
   returning half the revenue at a quarter the CPI is the better buy — and
   note the tier-mix finding cuts both ways: if paid_video is the cheapest
   source of *any* tier-4 volume, its as-bought gap may be an efficient
   trade, not a quality problem. This single table would change the verdict.
2. **Randomised or geo-holdout assignment.** Channels are not randomised:
   organic players self-select (they sought the game out), so part of the
   organic engagement premium is selection, not channel. A holdout geo where
   budget mix is randomly assigned is what converts "associated with" into
   "caused by". Our CIs cover *sampling noise only* — they do not and cannot
   cover this bias, which is why the artefact analysis is a separate section
   rather than a wider error bar.
3. **Maturity/calendar-matched cohorts.** R1/R2 already fix this by design
   (same 30-day follow-up for every in-scope install); E1 was checked
   month-by-month (§4); the remaining exposure is the Feb–Mar data gap (D1
   Q7), which we have bracketed rather than removed.
4. **Ad revenue.** All revenue here is IAP; channels may differ sharply in
   ad-monetised engagement (paid_video's tier-4 audience may watch more
   ads), and we cannot see that at all.
5. **A tier-mix change experiment.** Since §3 shows targeting (not quality)
   drives the revenue gap, the actionable test is whether paid_video can be
   re-targeted toward tiers 1–2 at acceptable CPI — a targeting change, not
   a channel verdict.

**Is the difference big enough to move budget?** On player quality: **no.**
After adjustment there is no resolved revenue difference at all, and the
surviving engagement edges (+1.5 pp D7, +0.7 min/day) are real but worth
roughly nothing against an unknown CPI — a 1.5 pp retention gain on a 25%
base does not move LTV enough to offset even a small CPI difference. On
as-bought cash: the $0.67–0.92/install gap is economically large (+44–60%)
and survives at p < 1e-4 *as a total effect*, so the conditional statement
stands: **shift spend away from paid_video only if its CPI advantage is
smaller than ~$0.7–0.9/install.** Without the CPI table (missing input,
§5.1) the defensible recommendation is: pull spend/CPI by channel, re-run
`3c_ltv30_channel` against it, and separately test re-targeting paid_video
away from tier 4 — because §3 shows that is where the gap lives.

---

## 6. Reconciliation and checks (`checks_d3.csv`, 10/10 pass)

| # | check | result |
|---|---|---|
| 1 | channel active device-days sum to P1+P2 total | 366,421 = 366,421 |
| 2 | channel gross sums to period gross | 112,836.82 = 112,836.82 |
| 3 | channel installs sum to `player_profile` | 80,295 = 80,295 |
| 4 | no NULL `acquisition_channel` | 0 |
| 5 | R1/R2 in-scope installs, channel vs total | 37,489 = 37,489 |
| 6 | R1 revenue channel sums = D2 tier sums | 77,493.58 = 77,493.58 (D2 `2a_ltv30_proxy`) |
| 7 | Σ share×raw ARPDAU = blended ARPDAU (identity) | 0.3079 = 0.3079 |
| 8 | D7 retained ≤ matured installs (matured-cell rule) | 13,851 ≤ 54,167 |
| 9 | standardised-section naive R1 = headline R1 (two independent query paths) | max abs diff 0.0 |
| 10 | D7 by install month sums to pooled D7 retained (Jan–Mar) | 9,591 = 9,591 |

Cross-deliverable ties: R1/R2 totals equal D2's `2a_ltv30_proxy` (37,489
installs, $77,493.58 — recomputed independently by channel here, check 6);
ARPDAU identity ties to D2's blended ARPDAU; definitions D1–D5 unchanged
(§0).

---

## 7. Figures

| figure | file | shows |
|---|---|---|
| fig3a | `figs/fig3a_naive_vs_adjusted.png` | raw vs tier-standardised ARPDAU by period — the sign flip |
| fig3b | `figs/fig3b_install_mix.png` | confound 2: paid_video install share 15% → 69% |
| fig3c | `figs/fig3c_forest.png` | all 18 pairwise differences with 95% CIs, naive and tier-standardised side by side |
| fig3d | `figs/fig3d_channel_means.png` | the six headline means ± 95% CI |

## 8. Missing inputs (ranked by how much they'd change the answer)

1. **CPI / spend by channel** — without it the budget verdict is
   conditional, not a recommendation (§5.1). It also decides whether
   paid_video's tier-4 targeting is an efficient trade or a leak.
2. **Ad-revenue by channel** — half the monetisation story is invisible.
3. **Experiment/holdout data** — the only way to separate selection from
   causation (§5.2), and to test tier re-targeting (§5.5).
4. **Promo/discount depth by period** (inherited from D2) — a channel-heavy
   promo in April would contaminate P2 channel comparisons.
