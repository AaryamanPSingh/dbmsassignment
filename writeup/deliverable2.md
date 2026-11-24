# Deliverable 2 — Deep dive (a): "ARPDAU is falling. Fix it."

**Scope.** First 30 days (P1 = 2026-01-01..01-30) vs last 30 days
(P2 = 2026-04-01..04-30): explain why blended ARPDAU fell ~16% while every
`country_tier` is flat or improving, and say what the business should do.
All numbers come from `sql/deliverable2.sql`, executed by
`scripts/run_deliverable2.py`; every claim cites its query section and CSV.

**Reproduce from a clean checkout:**

```bash
python3 scripts/load_data.py            # CSVs -> telemetry.db (applies fix D1)
python3 scripts/run_deliverable2.py     # runs all SQL -> outputs/deliverable2/*.csv
python3 scripts/charts_deliverable2.py  # figures -> outputs/deliverable2/figs/
```

---

## 0. Definitions and method (carried over unchanged from deliverable 1)

Decisions **D1–D5** (zero-padded timestamps; `purchase_id` dedup; gross =
positive `usd_amount`; active = `player_day` ∪ purchase days; ads shifted −8 h)
are reused verbatim, so D1 and D2 numbers reconcile by construction
(reconciliation in §6). Money in this deliverable is **IAP only** — the extract
contains no ad-revenue or marketing-spend data (see §5, missing inputs).

| Period | Days | Window |
|---|---|---|
| P1 first 30 | 2026-01-01 … 2026-01-30 | `day_id` 20260101–20260130 |
| P2 last 30 | 2026-04-01 … 2026-04-30 | `day_id` 20260401–20260430 |

**Unit of analysis:** the brief explicitly tells us countries are too sparse,
so everything headline-level is at `country_tier` (4 tiers, no NULLs —
check 9). Finer cuts (platform, channel) appear only as robustness checks.

**Decomposition method.** Blended ARPDAU is a weighted mean of tier ARPDAUs
with weights = each tier's share of active device-days, so the change splits
**exactly** (symmetric/Kitagawa shift-share, no interaction residual):

```
Δ ARPDAU = Σ_tier  (share₂ − share₁)·(rate₁ + rate₂)/2     <- "mix"
         + Σ_tier  (rate₂ − rate₁)·(share₁ + share₂)/2     <- "within"
```

The two terms sum to the headline −$0.0582 to the sixth decimal (check 1) —
the waterfall in fig2a has no "unexplained" bar.

---

## 1. The headline paradox (`2a_headline`, `2a_by_tier`)

| period | active device-days | gross $ | ARPDAU | payer share | ARPPU/purchasing dd |
|---|---|---|---|---|---|
| P1 first 30 | 82,694 | 29,188.90 | **0.3530** | 2.40% | $14.70 |
| P2 last 30 | 283,727 | 83,647.92 | **0.2948** | 2.07% | $14.26 |
| change | **+243.1%** | **+186.6%** | **−16.5%** | −13.9% rel | −3.0% rel |

ARPDAU = payer share × revenue per purchasing device-day:
0.861 × 0.970 = 0.835 → −16.5%. Both halves fell — but only in the blend.

**Split by tier — every tier improves while the blend falls**
(`2a_by_tier`; identity confirmed by check 5: 4 of 4):

| tier | ARPDAU P1→P2 | change | share of device-days P1→P2 | payer share P1→P2 |
|---|---|---|---|---|
| 1 | 0.5157 → 0.5516 | **+7.0%** | 34.5% → 20.5% | 3.55% → 3.91% |
| 2 | 0.3721 → 0.4013 | **+7.9%** | 26.1% → 15.6% | 2.44% → 2.72% |
| 3 | 0.2331 → 0.2600 | **+11.6%** | 21.8% → 18.0% | 1.63% → 1.81% |
| 4 | 0.1540 → 0.1575 | **+2.3%** | **17.6% → 45.9%** | 1.05% → 1.12% |

Textbook Simpson's paradox: within every tier, ARPDAU *and* payer share rose;
the blend falls because the weight moved from tiers earning $0.23–0.52 per
device-day to the tier earning $0.15. The blended payer-share drop (2.40% →
2.07%) is the same illusion — tier-4's payer rate (~1.1%) is a third of
tier-1's, so more tier-4 weight mechanically lowers the blend.

**The ratio trap, stated once:** revenue **+186.6%** looks like a boom;
ARPDAU **−16.5%** looks like a collapse. Same data — the denominator (active
device-days, +243.1%) grew faster than the numerator. Neither framing alone is
the business reality: absolute revenue grew **+$54,459 per 30 days**, and
per-active-day value genuinely fell *only because of who is now active*.

---

## 2. Exact decomposition: mix vs within (`2a_decomposition`, `2a_counterfactual`, fig2a)

| tier | ARPDAU P1 | ARPDAU P2 | share P1 | share P2 | mix effect | within effect |
|---|---|---|---|---|---|---|
| 1 | 0.5157 | 0.5516 | 34.5% | 20.5% | −0.07472 | +0.00988 |
| 2 | 0.3721 | 0.4013 | 26.1% | 15.6% | −0.04058 | +0.00608 |
| 3 | 0.2331 | 0.2600 | 21.8% | 18.0% | −0.00934 | +0.00536 |
| 4 | 0.1540 | 0.1575 | 17.6% | 45.9% | +0.04405 | +0.00110 |
| **TOTAL** | **0.3530** | **0.2948** | 100% | 100% | **−0.08058** | **+0.02243** |

- **Mix cost −$0.0806** (−22.8% of P1 ARPDAU); **within added +$0.0224**
  (+6.4%); net **−$0.0582 = −16.5%** exactly (check 1, zero residual).
- Per-tier mix terms are *attributions of each tier's share movement at its own
  average rate* — only the total is a counterfactual. The counterfactual is:

| scenario (evaluated at P2's 283,727 device-days) | ARPDAU | revenue | vs actual |
|---|---|---|---|
| 1 actual (P2 mix, P2 rates) | 0.2948 | $83,648 | — |
| 2 no mix shift (P1 shares held) | 0.3754 | $106,512 | **+$22,864 (+27.3%)** |
| 3 no within change (P1 rates held) | 0.2724 | $77,285 | −$6,363 (−7.6%) |

**Read scenario 2 two ways:** the mix shift *cost* ≈ **$22.9k per 30 days**,
and at January's tier mix April ARPDAU would have been $0.375 — **+6.4% above
January**, not −16.5% below. Monetisation improved; the KPI moved because the
player base did. fig2d shows this daily: the constant-mix line tracks January,
then separates from the observed line in April.

---

## 3. What moved the mix (`2a_installs_*`, `2a_dd_age`, `2a_channel*`)

1. **The UA ramp is almost entirely tier 4** (fig2c). Tier-1/2/3 monthly
   installs are flat (~3.1–4.3k each all year); tier 4 goes
   Jan 1,772 (18.1% of installs) → Feb 2,067 (21.8%) → **Mar 9,166 (50.3%) →
   Apr 16,807 (62.7%)**. In-period: P1 installs 9,494 (tier 4 = 18.1%) vs P2
   26,806 (**tier 4 = 62.7%**). This quantifies D1's Q7 13× weekly ramp.
2. **The channel doing it is `paid_video`** (`2a_channel`): its share of
   actives 14.8% → 48.5%; organic 46.7% → 28.0%, paid_social 38.5% → 23.6%.
   `paid_video` actives in P2 are **76% tier-4** (`2a_channel_tier`:
   paid_video×tier4 alone = 36.6% of *all* P2 actives, vs 2.7% of P1).
   Channel ARPDAU moves with that composition: paid_video $0.385 → $0.210
   while organic ($0.353 → $0.372) and paid_social ($0.341 → $0.378) *rise* —
   and paid_video's own tier-1 cell is fine ($0.574 → $0.580). The channel
   didn't get worse; its audience changed.
3. **P2's tier-4 DAU is fresh UA, not an ageing base** (`2a_dd_age`):
   54.5% of tier-4 P2 device-days are players installed *during* P2, 87.1%
   installed within 30 days, only 12.9% older than 31 days — vs tier 1 where
   50.6% of device-days are 31+ days old.
4. **Engagement is not the problem** (`2a_retention_tier`): tier-level
   retention is nearly identical — D7 mean 26.1/26.4/25.8/**24.8%** and D30
   14.8/14.3/13.9/**13.8%** for tiers 1–4 (mature cells only, same rule as
   D1b). Tier-4 traffic *plays* like tier-1 traffic.
5. **But it pays less, at equal follow-up** (`2a_ltv30_proxy`): installs
   2026-01-01..03-31 with a full 30 days of follow-up (no right-censoring):

| tier | installs | 30-day payer rate | 30-day IAP revenue/install |
|---|---|---|---|
| 1 | 9,775 | 18.3% | **$3.49** |
| 2 | 7,349 | 13.3% | $2.26 |
| 3 | 7,360 | 10.0% | $1.73 |
| 4 | 13,005 | 6.9% | **$1.08** |

   Tier-4 engages like tier-1 but converts at a third the rate — the mix shift
   is real economic weight moving toward lower-monetising players.

---

## 4. Scrutiny — the tempting answers that fall apart

**Tempting answer 1: "spending broke — run promos / fix the shop."**
Falls apart: within every tier both ARPDAU and payer share *rose*
(§1); the blended payer-share fall is tier composition. Emergency discounting
would trade real revenue for a ratio caused by weighting (scenario 3 shows
within-monetisation already *adds* $6.4k/30d). The one soft spot worth
watching: ARPPU per purchasing device-day is flat-to-slightly-down within
tiers (e.g. tier 1 $14.52 → $14.11) — payer-rate gains are doing the work —
which is a price-pack opportunity, not an emergency.

**Tempting answer 2: "cut the cheap tier-4 / paid_video traffic."**
Falls apart in the other direction: retention is identical (§3.4), tier-4
watched **101.8 completed ads per 100 device-days vs tier 1's 57.8**
(`2a_ad_engagement`), and total revenue is +$54.5k/30d on that traffic. What
the extract *cannot* tell us is whether it was *profitable* — no CPI/spend, no
ad revenue (§5). Cutting a channel on IAP-ARPDAU alone would be exactly the
ratio-trap error in reverse.

**Robustness checks — the decline is real, not an artefact:**

| check | result | verdict |
|---|---|---|
| Window length (`2a_window_sensitivity`) | −16.8% (28d), **−16.5% (30d)**, −13.4% (35d), −13.8% (60d) | direction robust; magnitude −13…−17% |
| Sale calendar (`2a_sale_density`) | 13 sale days in P1 vs 18 in P2, but sale revenue share 37.5% vs 38.6% | sale cadence does not explain the drop |
| Tier × platform (`2a_tier_platform`) | **7 of 8 cells improve**; only tier-4×iOS falls (−17.4%, tiny P1 base: 1,581 dd / $391) | platform story from D1 is composition too |
| Channel × tier (`2a_channel_tier_arpdau`) | **5 of 12 cells decline** (organic×1 −11.2%, paid_social×3 −27.2%, paid_video×2 −23.0%, paid_video×4 −8.0%, paid_social×4 −15.3%); if all had merely held their P1 rate, ≈$0.019 of the gap would vanish | within-tier gains are real but *not uniform* — do not claim "every cell improves" beyond tier level; the exact identity holds at any level |
| Tier-4 "they're just new" (`2a_ltv30_proxy`) | equal 30-day follow-up still gives $1.08 vs $3.49/install | maturity ≠ explanation (but 30d ≠ lifetime, §5) |

---

## 5. Missing inputs (named, not worked around)

1. **Marketing spend / CPI by channel × tier.** The studio's frame is "grow
   revenue without growing marketing spend" — `acquisition_channel` exists but
   no cost data, so tier-4 UA ROI (the decision §3 implicates) is
   *unanswerable* from this extract. Do not impute it.
2. **Ad revenue.** Ad telemetry exists (views, caps, completion) but no revenue
   per view; tier-4 completes ~2× the ads per device-day of tier 1. IAP-only
   ARPDAU therefore likely *understates* tier-4 value by an unknown amount.
3. **Subscription billing revenue.** D1 Q8: 17,747 devices receive
   subscription-granted currency with no `purchase` row — subscription income
   is outside the revenue numerator entirely.
4. **LTV beyond the window.** The extract ends 2026-04-30: P2 installs have
   ≤30 days of follow-up, and even the LTV30 cohort stops at 2026-03-31
   installs. 90/180-day tier-4 LTV — the number that would settle question 2 —
   does not exist yet.
5. **Country-level detail.** Sparse by construction (the brief directs us to
   tier level); geo-targeted policy inside tier 4 is not supportable here.
6. **Promo depth calendar.** `sale_flag` marks sale days but not discount
   size, so sale incrementality / elasticity stays out of scope (D2 candidate).

---

## 6. What the business should do

1. **Fix the KPI, not the game.** Report ARPDAU alongside a **constant-mix
   ARPDAU index** (fig2d): rebased to January's tier shares, April is ~$0.375
   (+6.4% vs January). Restate history at fixed weights so the ramp stops
   masquerading as deterioration. This costs nothing and changes no product
   decision — it changes *which* decisions get made.
2. **Do not run monetisation "rescue" promos for the ratio.** Every tier
   monetises better than in January; discounts would hand over real revenue to
   offset a composition artefact (scenario 3 already isolates the genuine
   within-gain at +$6.4k/30d).
3. **Gate the tier-4/paid_video scale-up on the missing inputs, not on
   ARPDAU.** Interim criteria until CPI and ad-revenue data arrive:
   (a) keep watching 30-day revenue/install by tier (currently $1.08 vs $3.49)
   as the least-bad unit-economics proxy; (b) require the tier-4 payer-rate
   trend (1.05% → 1.12% and rising) to hold; (c) treat the 2× ad engagement as
   *potential* offset only — quantify it the moment ad-revenue data exists.
   Cutting the channel today would sacrifice proven +$54.5k/30d of IAP revenue
   to improve a ratio.
4. **Instrument the missing inputs as an analytics backlog** (§5 items 1–4):
   a spend table keyed by channel×tier×date, ad-revenue attribution onto
   `ad_view`, subscription revenue joined to `device_id`, and extending the
   extract past 2026-04-30 for true cohort LTV. Until then, every UA
   scale-up/tighten decision is provisional and should be labelled as such.
5. **Track the decomposition monthly** (mix vs within + constant-mix index) in
   the standing pack, plus revenue-per-install by tier. The exact shift-share
   identity makes this a one-query routine — mix rising with within flat means
   *strategy* is driving the KPI; within falling means *product* is.

---

## 7. Reconciliation with deliverable 1

- Check 6: total gross across all periods = **$217,593.22 = D1's headline**
  (D3/D2 definitions carried over).
- D1's April ARPDAU $0.2948 (full month) = P2 exactly (Apr has 30 days);
  D1's January $0.3509 covers 31 days vs P1's 30 (Jan 31 excluded by the
  brief's "first 30 days"), hence 0.3530 vs 0.3509 — consistent by design.
- D1's Q7 install ramp (507 → 6,543/week) is the *engine* quantified in §3.
- D1's Android −17.5% decline is re-attributed in §4: composition, not
  platform-specific collapse.
- `checks_d2.csv` — **9/9 pass**: decomposition identity (mix+within = actual
  to 6 dp), tier sums = headline device-days/gross, shares = 100%, 4/4 tiers
  improving, gross and install totals split cleanly into P1+P2+outside,
  counterfactual identity (P1 + mix + within = P2), zero NULL tiers.

---

## 8. Files

| file | contents |
|---|---|
| `sql/deliverable2.sql` | sections `@setup` (+ `day_map` calendar), `@2a_headline` … `@2a_weekly_mix`, `@checks_d2` |
| `scripts/run_deliverable2.py` | executes sections → 19 CSVs + `summary.md` |
| `scripts/charts_deliverable2.py` | fig2a waterfall, fig2b share vs ARPDAU, fig2c install mix, fig2d constant-mix KPI |
| `outputs/deliverable2/*.csv` | headline, tier split, decomposition, counterfactual, ramp/channel/age/retention/LTV, 4 robustness tables, checks |
| `outputs/deliverable2/figs/*.png` | deck figures (fig2a/2b/2d are slide candidates) |
