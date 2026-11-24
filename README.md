# Mobile Game Telemetry — Analytics & Modelling

End-semester DBMS lab project: a 120-day extract from a mobile game's telemetry,
taken from raw CSVs through SQL analysis, statistical testing and two predictive
models, to a Product Director readout deck.

Everything here is reproducible from the five source CSVs: one loader builds a
SQLite database, one script per deliverable runs its SQL and writes CSVs, and a
separate chart script turns those CSVs into the figures used in the write-ups
and the deck.

---

## Dataset

| File | Rows (approx.) | Grain | Key fields |
|------|----------------|-------|------------|
| `player_profile - player_profile.csv` | 80,295 | one row per install (64,295 in-window) | `device_id`, `install_date`, `platform`, `country_tier`, `acquisition_channel` |
| `player_day - player_day.csv` | 667,435 | player × active day | `activity_date`, `player_level`, `session_count`, `playtime_minutes` |
| `purchase - purchase.csv` | 15,426 | one row per IAP | `purchase_id`, `event_ts`, `usd_amount`, `pack_name` |
| `currency_spend - currency_spend.csv` | 489,892 | one row per soft-currency spend | `spend_type`, `currency_type`, `currency_value` |
| `ad_view - ad_view.csv` | 647,623 | one row per ad event | `event_ts`, `status`, `placement`, `ad_daily_count`, `ad_daily_cap` |

**Window:** 2026-01-01 → 2026-04-30 for activity; installs are visible from
2025-12-08. Money is **IAP only** — the extract contains no ad-revenue or
marketing-spend figures, which bounds several conclusions.

The raw CSVs are committed (about 100 MB). `telemetry.db` is built locally and
is gitignored.

---

## Deliverables

| # | Question | Headline result | Write-up |
|---|----------|-----------------|----------|
| 1 | Know the data: daily health, retention, spenders, ad engagement | D1 47.8% / D7 25.6% / D30 14.2%; top 1% of payers = 9.3% of revenue | [`writeup/deliverable1.md`](writeup/deliverable1.md) |
| 2 | "ARPDAU is falling. Fix it." | Revenue +186.6% while device-days +243.1%; ARPDAU −16.5%, but **+6.4% at constant tier mix** — the fall is mix, not monetisation | [`writeup/deliverable2.md`](writeup/deliverable2.md) |
| 3 | Is one acquisition channel better than another? | Naive `organic` vs `paid_video` gap is +59.7%; adjusted it is +$0.103 (+5.0%), p = 0.52 — the gap is tier targeting, not channel quality | [`writeup/deliverable3.md`](writeup/deliverable3.md) |
| 4a | Predict which active players churn in 14 days | Out-of-time AUC 0.742; top decile 40.2% precision (2.76× base); tenure alone gets 0.741 | [`writeup/deliverable4.md`](writeup/deliverable4.md) |
| 4b | Predict 90-day value of a new install (optional) | Payer AUC 0.702, top-decile lift 4.34×, 43.5% of revenue captured; amount is weak (Spearman 0.266), so use it to rank, not to price | [`writeup/deliverable4b.md`](writeup/deliverable4b.md) |
| 5 | Readout for the Product Director | 8 readout slides + 7 appendix slides, one weight-carrying chart per argument | [`outputs/deliverable5/README.md`](outputs/deliverable5/README.md) |

Each analysis directory under `outputs/` holds the result CSVs, its figures
(`figs/`) and a `summary.md` dump of the tables. Deliverables 1–4 also ship a
`checks_*.csv` file listing the reconciliation checks that passed (11/11, 9/9,
10/10, 11/11, 10/10).

---

## Reproduce

**Requirements:** Python 3.10+, plus

```bash
pip install pandas numpy scipy matplotlib pillow python-pptx
```

**Full pipeline**, from the repo root:

```bash
python3 scripts/load_data.py             # CSVs -> telemetry.db (zero-pads malformed timestamps)
python3 scripts/run_deliverable1.py      # SQL -> outputs/deliverable1/*.csv
python3 scripts/charts_deliverable1.py   #      -> outputs/deliverable1/figs/*.png
python3 scripts/run_deliverable2.py
python3 scripts/charts_deliverable2.py
python3 scripts/run_deliverable3.py      # SQL + bootstrap / z-tests
python3 scripts/charts_deliverable3.py
python3 scripts/run_deliverable4.py      # 4a: churn model
python3 scripts/charts_deliverable4.py
python3 scripts/run_deliverable4b.py     # 4b: 90-day value model
python3 scripts/charts_deliverable4b.py
python3 scripts/build_readout_deck.py    # -> outputs/deliverable5/readout.pptx
python3 scripts/validate_deck.py         # layout / text-fit / notes check
```

`run_deliverable4b.py` writes into `outputs/deliverable4/` alongside 4a, using
`4b_` prefixes, because the two models share a feature store.

The loader is idempotent: it drops and recreates the tables, so re-running the
pipeline never double-counts.

---

## Repo layout

```
.
├── DBMS-LAB-END-SEM.pdf          # assignment brief
├── *.csv                         # five source telemetry extracts
├── sql/                          # one .sql file per deliverable, split into named sections
│   ├── deliverable1.sql … deliverable4b.sql
├── scripts/
│   ├── load_data.py              # CSV -> SQLite, with timestamp normalisation
│   ├── profile_data.py           # column profiling used for the data-quality note
│   ├── run_deliverable*.py       # execute SQL, run models, write CSVs
│   ├── charts_deliverable*.py    # figures from those CSVs
│   ├── build_readout_deck.py     # 15-slide PPTX
│   └── validate_deck.py          # geometry / overflow checks on the deck
├── writeup/                      # the five written answers, with query + CSV citations
└── outputs/
    ├── deliverable1/ … deliverable4/   # CSVs, figs/, summary.md, checks_*.csv
    └── deliverable5/                   # readout.pptx + its README
```

---

## Method notes

**Shared definitions (D1–D5).** Applied identically in every deliverable so the
numbers reconcile by construction:

- **D1** — `event_ts` values with single-digit hours are zero-padded at load;
  without this, ~13% of rows silently vanish from SQLite date aggregates.
- **D2** — `purchase_id` deduplication (122 duplicate rows, $1,815.82).
- **D3** — gross = positive `usd_amount`; refunds are reported separately.
- **D4** — active = `player_day` ∪ purchase days, so payers who skip a session
  are not misclassified as churned.
- **D5** — ad events are shifted −8 h to align with the activity-day boundary.
  Raw ad days peak at 8 h and run to 100% after the shift.
- **Q6** — the 48-hour ad telemetry outage on March 5–6 (raw rows stop at
  07:59 and resume two days later) is flagged and excluded from ad-rate trends
  rather than treated as a behavioural dip.

**Known data issues** are quantified in the write-ups and the deck appendix:
13% malformed timestamps, 122 duplicate purchases, 2,449 refund rows
($35,732.51, 16.4% of gross), 1,114 never-active installs and 110
pre-install payers, plus a never-paid share that rises from 75.9% in January
to 93.7% in April as cheap installs mature.

**Statistical care.** Channel and tier comparisons use bootstrapped confidence
intervals and pooled two-proportion z-tests; engagement metrics carry a
Bonferroni correction (α = 0.0028) because several were tested at once. The
deck reports adjusted gaps, not naive ones.

**Modelling care.** Both models are evaluated out of time on untouched test
snapshots/cohorts, with regularisation chosen on a validation split. They are
framed as **ranking tools**: the churn model is useful at the top of the list
(2.76× lift) and the value model ranks installs (4.34× lift) but cannot price
individual installs (amount MAE $21.05, Spearman 0.266). No per-install dollar
claims are made.

---

## Deck

`outputs/deliverable5/readout.pptx` — 16:9, 8 readout slides for the Product
Director plus 7 appendix slides (data quality, per-deliverable numbers,
judgement calls, dead ends, next steps). Speaker notes on every slide.

```bash
python3 scripts/build_readout_deck.py   # regenerate
python3 scripts/validate_deck.py        # bounds, text fit, table growth, notes
```

Layout is validated programmatically because this environment has no
LibreOffice or Chrome to render slides; open the file once in PowerPoint to
confirm fonts before presenting.

---

## Limitations

- IAP-only revenue: no ad revenue, so ARPDAU understates total monetisation and
  the ad-supported tier looks worse than it is.
- No marketing spend, so channel comparisons are revenue-per-device-day, not
  ROAS.
- 120-day extract: only installs through 2026-01-30 have a complete 90-day
  label (9,494 of 64,295 installs), and the mature cohort skews toward early,
  cheaper installs.
- Observational data throughout: tier mix, channel and retention are correlated
  with unobserved acquisition intent, so adjusted gaps are associations, not
  causal effects.
