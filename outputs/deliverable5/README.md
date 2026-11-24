# Deliverable 5 — Product Director readout

**File:** `readout.pptx` — 16:9, 8 readout slides + 7 appendix slides, speaker notes on every slide.

## Rebuild

```bash
python3 scripts/build_readout_deck.py    # writes outputs/deliverable5/readout.pptx
python3 scripts/validate_deck.py         # bounds / text-fit / table-growth / notes check
```

The builder reads the figures produced by deliverables 1–4b, so run those first if `outputs/*/figs` is empty:

```bash
python3 scripts/run_deliverable1.py
python3 scripts/run_deliverable2.py
python3 scripts/run_deliverable3.py
python3 scripts/run_deliverable4.py
python3 scripts/run_deliverable4b.py
```

## Slide map

| # | Slide | Evidence |
|---|-------|----------|
| 1 | Title + bottom line | — |
| 2 | The paradox: revenue +187%, ARPDAU −16.5% | D2 headline |
| 3 | Every tier improved; the blend fell | D2 by-tier + fig2a |
| 4 | Constant-mix ARPDAU +6.4% | D2 decomposition + fig2d |
| 5 | Channel gap is tier targeting | D3 forest + fig3c |
| 6 | Retention held through 13× ramp | D1 cohorts + fig1b |
| 7 | Recommendations: measure / acquire / model | D2–D4b |
| 8 | Five gaps that bound the answer | all |
| A1 | Data quality + judgement calls | D1 profiling |
| A2 | D1 retention and concentration | D1 |
| A3 | D2 exact decomposition + counterfactual | D2 |
| A4 | D3 adjusted channel comparisons | D3 |
| A5 | D4a churn model | D4a |
| A6 | D4b value model (optional) | D4b |
| A7 | Dead ends, limits, next week | all |

No renderer (LibreOffice/Chrome) is installed on this machine, so layout was checked programmatically rather than visually. Open the deck once in PowerPoint to confirm fonts and any auto-fit behaviour before submitting.
