#!/usr/bin/env python3
"""Generate Deliverable-4b figures from the install-value output CSVs.

Run after scripts/run_deliverable4b.py:
    python3 scripts/charts_deliverable4b.py
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
IN = ROOT / "outputs" / "deliverable4"
OUT = IN / "figs"
OUT.mkdir(parents=True, exist_ok=True)

plt.rcParams.update({"figure.dpi": 130, "axes.grid": True,
                     "grid.alpha": 0.3, "font.size": 9})

BLUE, RED, GREEN, ORANGE, GREY = "#4c78a8", "#d62728", "#2ca02c", "#ff7f0e", "#7f7f7f"

metrics = pd.read_csv(IN / "4b_metrics.csv")
test = metrics[metrics["sample"].str.startswith("test")].iloc[0]
pred = pd.read_csv(IN / "4b_test_predictions.csv")
dist = pd.read_csv(IN / "4b_revenue_distribution.csv")
base = float(test.mean_rev_90)

# ------------------------------------------------- 4b1 revenue concentration
fig, axes = plt.subplots(1, 2, figsize=(10.6, 4.2))
ax = axes[0]
x = np.arange(len(dist))
ax.bar(x - 0.2, dist.share_installs_pct, width=0.4, color=BLUE,
       label="% of installs")
ax.bar(x + 0.2, dist.share_revenue_pct, width=0.4, color=RED,
       label="% of 90-day revenue")
ax.set_xticks(x)
ax.set_xticklabels(dist.bucket, rotation=35, ha="right")
ax.set_ylabel("% of the test cohort")
zero_share = float(dist.iloc[0].share_installs_pct)
ax.set_title(f"{zero_share:.0f}% of installs never pay in 90 days")
ax.legend(fontsize=8)

ax = axes[1]
y = np.sort(pred.revenue_90.values)[::-1]
cum = np.cumsum(y) / y.sum()
share = np.arange(1, len(y) + 1) / len(y)
ax.plot(100 * share, 100 * cum, color=GREEN, lw=2, label="actual revenue")
ax.plot([0, 100], [0, 100], "--", color=GREY, lw=1, label="random installs")
for pct in (1, 5, 10, 25):
    k = max(1, int(round(len(y) * pct / 100)))
    ax.plot(pct, 100 * cum[k - 1], "o", color=GREEN, ms=4)
    ax.annotate(f"{100 * cum[k - 1]:.0f}%", (pct, 100 * cum[k - 1]),
                textcoords="offset points", xytext=(4, -11), fontsize=7.5)
ax.set_xlim(0, 50)
ax.set_xlabel("% of installs, sorted by actual 90-day revenue")
ax.set_ylabel("% of total 90-day revenue")
k10 = max(1, int(round(len(y) * 0.10)))
ax.set_title(f"The top 10% of installs carry {100 * cum[k10 - 1]:.0f}% of revenue")
ax.legend(fontsize=8, loc="lower right")
fig.suptitle("90-day revenue is extremely concentrated: most installs are worth $0",
             fontsize=10)
fig.tight_layout()
fig.savefig(OUT / "fig4b1_revenue_concentration.png")
plt.close(fig)

# --------------------------------------------------------- 4b2 lift curve
curve = pd.read_csv(IN / "4b_lift_curve.csv")
base_rows = pd.read_csv(IN / "4b_baselines.csv")
spend_row = base_rows[base_rows.model == "first-week spend only"].iloc[0]

fig, ax = plt.subplots(figsize=(6.8, 4.3))
ax.plot(curve.pct_targeted, curve.model_capture_pct, color=BLUE, lw=2,
        label="two-part expected value")
ax.plot(curve.pct_targeted, curve.week1_spend_capture_pct, color=ORANGE,
        lw=1.6, ls="--", label="first-week spend rank (simple baseline)")
ax.plot(curve.pct_targeted, curve.random_capture_pct, color=GREY, lw=1,
        ls=":", label="random bidding")
cap = float(test.top10_capture_pct)
ax.plot(10, cap, "o", color=BLUE, ms=5)
ax.annotate(f"{cap:.0f}%", (10, cap), textcoords="offset points",
            xytext=(-4, 8), fontsize=8, color=BLUE)
ax.set_xlim(0, 50)
ax.set_ylim(0, 80)
ax.set_xlabel("% of installs bid on, highest predicted value first")
ax.set_ylabel("% of total 90-day revenue captured")
ax.set_title(f"Top 10% captures {test.top10_capture_pct:.0f}% of revenue "
             f"({test.top10_lift:.1f}× random);\n"
             f"first-week spend alone captures {spend_row.top10_capture_pct:.0f}% "
             f"but falls behind deeper in the ranking")
ax.legend(fontsize=8, loc="lower right")
fig.tight_layout()
fig.savefig(OUT / "fig4b2_lift.png")
plt.close(fig)

# ------------------------------------------------------- 4b3 calibration
cal = pd.read_csv(IN / "4b_calibration.csv")
payer = cal[cal.kind == "payer_probability"]
rev = cal[cal.kind == "expected_revenue"]

fig, axes = plt.subplots(1, 2, figsize=(9.8, 4.2))
ax = axes[0]
ax.plot(100 * payer.predicted_mean, 100 * payer.observed_mean, "o-", color=BLUE,
        lw=1.8, ms=5)
lim = 75
ax.plot([0, lim], [0, lim], "--", color=GREY, lw=1)
ax.set_xlim(0, lim)
ax.set_ylim(0, lim)
ax.set_xlabel("Mean predicted P(pay in 90 days) (%)")
ax.set_ylabel("Observed payer rate (%)")
ax.set_title("Payer probability is close to calibrated\n"
             "(decile error 2.1 pp; top decile 68% predicted vs 70% observed)")

ax = axes[1]
ax.plot(rev.predicted_mean, rev.observed_mean, "o-", color=RED, lw=1.8, ms=5)
lim = max(rev.predicted_mean.max(), rev.observed_mean.max()) * 1.08
ax.plot([0, lim], [0, lim], "--", color=GREY, lw=1)
ax.set_xlim(0, lim)
ax.set_ylim(0, lim)
ax.set_xlabel("Mean predicted 90-day value per install ($)")
ax.set_ylabel("Observed mean 90-day revenue ($)")
top = rev.iloc[-1]
ax.annotate(f"top decile: ${top.predicted_mean:.1f} predicted\n"
            f"vs ${top.observed_mean:.1f} observed",
            (top.predicted_mean, top.observed_mean),
            textcoords="offset points", xytext=(-90, 8), fontsize=8)
ax.set_title("Expected-value calibration is rough in the tail:\n"
             "the top decile is over-predicted")
fig.suptitle("Test-set calibration of the two-part score", fontsize=10)
fig.tight_layout()
fig.savefig(OUT / "fig4b3_calibration.png")
plt.close(fig)

# --------------------------------------------------------- 4b4 segments
seg = pd.read_csv(IN / "4b_segment_metrics.csv")
seg = seg[seg.spearman.notna()].copy()
seg["label"] = seg.segment.str.replace("_", " ") + ": " + seg.value.astype(str)
seg = seg.sort_values("spearman")
colors = {"acquisition_channel": BLUE, "country_tier": GREEN,
          "platform": ORANGE, "first_week_payer": RED,
          "install_window": "#9467bd"}

fig, ax = plt.subplots(figsize=(7.6, 5.2))
bars = ax.barh(seg.label, seg.spearman, color=[colors[s] for s in seg.segment],
               alpha=0.9)
ax.axvline(test.spearman, color="black", ls="--", lw=1.2,
           label=f"overall Spearman {test.spearman:.3f}")
for b, (_, r) in zip(bars, seg.iterrows()):
    ax.text(b.get_width() + 0.006, b.get_y() + b.get_height() / 2,
            f"{r.spearman:.2f} (n={int(r.n):,})", va="center", fontsize=7)
ax.set_xlim(0, max(seg.spearman) * 1.22)
ax.set_xlabel("Spearman rank correlation, predicted vs actual 90-day revenue")
ax.set_title("Where the ranking is weakest: tier 4, Android, and the last\n"
             "five days of January (a within-test drift, not just noise)",
             fontsize=9.5)
ax.legend(fontsize=8, loc="lower right")
fig.tight_layout()
fig.savefig(OUT / "fig4b4_segment_rank.png")
plt.close(fig)

print("wrote:", ", ".join(sorted(p.name for p in OUT.glob("fig4b*.png"))))
