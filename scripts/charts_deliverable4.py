#!/usr/bin/env python3
"""Generate Deliverable-4a figures from the churn output CSVs.

Run after scripts/run_deliverable4.py:
    python3 scripts/charts_deliverable4.py
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

metrics = pd.read_csv(IN / "4a_metrics.csv")
test = metrics[metrics["sample"].str.startswith("test")].iloc[0]
base = test.churn_rate_pct / 100

# --------------------------------------------------------------- 4a ROC / PR
roc = pd.read_csv(IN / "4a_roc_curve.csv")
pr = pd.read_csv(IN / "4a_pr_curve.csv")

fig, axes = plt.subplots(1, 2, figsize=(9.6, 4.0))
ax = axes[0]
ax.plot(roc.fpr, roc.tpr, color=BLUE, lw=2)
ax.plot([0, 1], [0, 1], "--", color=GREY, lw=1)
ax.set_xlabel("False positive rate")
ax.set_ylabel("True positive rate")
ax.set_title(f"ROC — test AUC = {test.roc_auc:.3f}")
ax.text(0.52, 0.12, "random ranking\n(AUC 0.50)", color=GREY, fontsize=8)

ax = axes[1]
ax.plot(pr.recall, pr.precision, color=RED, lw=2)
ax.axhline(base, ls="--", color=GREY, lw=1)
ax.set_xlabel("Recall (share of churners found)")
ax.set_ylabel("Precision (share flagged who churn)")
ax.set_ylim(0, 0.85)
ax.set_title(f"Precision–recall — test AP = {test.pr_auc:.3f}")
ax.text(0.05, base + 0.02, f"base rate {100*base:.1f}%", color=GREY, fontsize=8)
fig.suptitle("14-day churn ranking on the untouched Apr-08 snapshot", fontsize=10)
fig.tight_layout()
fig.savefig(OUT / "fig4a_roc_pr.png")
plt.close(fig)

# --------------------------------------------------------------- 4b calibration
cal = pd.read_csv(IN / "4a_calibration.csv")
ece = float((cal.n / cal.n.sum() * (cal.predicted_pct - cal.observed_pct).abs()).sum())
top_pred = float(cal.iloc[-1].predicted_pct)
top_obs = float(cal.iloc[-1].observed_pct)
fig, ax = plt.subplots(figsize=(6.4, 4.2))
ax.plot(cal.predicted_pct, cal.observed_pct, "o-", color=BLUE, lw=1.8, ms=5,
        label="decile")
lim = max(cal.predicted_pct.max(), cal.observed_pct.max()) + 3
ax.plot([0, lim], [0, lim], "--", color=GREY, lw=1, label="perfect calibration")
for _, r in cal.iterrows():
    if r.decile in (1, 10):
        ax.annotate(f"{int(r.decile)}", (r.predicted_pct, r.observed_pct),
                    textcoords="offset points", xytext=(5, -10), fontsize=8)
ax.set_xlabel("Mean predicted churn probability (%)")
ax.set_ylabel("Observed churn rate (%)")
ax.set_title(f"Calibration by test decile — mean error {ece:.1f} pp;\n"
             f"the top decile is over-predicted ({top_pred:.0f}% vs {top_obs:.0f}%)")
ax.legend(fontsize=8)
fig.tight_layout()
fig.savefig(OUT / "fig4b_calibration.png")
plt.close(fig)

# --------------------------------------------------------------- 4c gain curve
pred = pd.read_csv(IN / "4a_test_predictions.csv")
pred = pred.sort_values("predicted_churn", ascending=False).reset_index(drop=True)
cum_pos = pred.churn14.cumsum() / pred.churn14.sum()
share = np.arange(1, len(pred) + 1) / len(pred)
# down-sample for plotting
idx = np.linspace(0, len(pred) - 1, 400).astype(int)

fig, ax = plt.subplots(figsize=(6.6, 4.2))
ax.plot(100 * share[idx], 100 * cum_pos.iloc[idx], color=GREEN, lw=2,
        label="model ranking")
ax.plot([0, 100], [0, 100], "--", color=GREY, lw=1, label="random targeting")
for pct in (5, 10, 20, 30, 50):
    k = int(round(len(pred) * pct / 100))
    gain = 100 * cum_pos.iloc[k - 1]
    ax.plot(pct, gain, "o", color=GREEN, ms=4)
    ax.annotate(f"{gain:.0f}%", (pct, gain),
                textcoords="offset points", xytext=(-6, 7), fontsize=7.5)
ax.set_xlim(0, 55)
k10 = int(round(len(pred) * 0.10))
gain10 = 100 * cum_pos.iloc[k10 - 1]
ax.set_xlabel("% of active players targeted, highest risk first")
ax.set_ylabel("% of 14-day churners captured")
ax.set_title(f"Targeting the top 10% reaches {gain10:.0f}% of churners "
             f"({gain10/10:.1f}× random);\n"
             f"the other {100-100*pred.churn14[:k10].mean():.0f}% of that decile do not churn")
ax.legend(fontsize=8, loc="lower right")
fig.tight_layout()
fig.savefig(OUT / "fig4c_gain.png")
plt.close(fig)

# --------------------------------------------------------- 4d segment AUC gaps
seg = pd.read_csv(IN / "4a_segment_metrics.csv")
seg = seg[seg.split == "test"].copy()
seg["label"] = seg.segment.str.replace("_", " ") + ": " + seg.value.astype(str)
seg = seg.sort_values(["segment", "roc_auc"])
colors = {"tenure_bucket": ORANGE, "country_tier": BLUE,
          "platform": GREEN, "acquisition_channel": RED}

fig, ax = plt.subplots(figsize=(7.6, 5.2))
bars = ax.barh(seg.label, seg.roc_auc, color=[colors[s] for s in seg.segment],
               alpha=0.9)
ax.axvline(test.roc_auc, color="black", ls="--", lw=1.2,
           label=f"overall AUC {test.roc_auc:.3f}")
for b, (_, r) in zip(bars, seg.iterrows()):
    ax.text(b.get_width() - 0.02, b.get_y() + b.get_height() / 2,
            f"{r.roc_auc:.2f} (n={int(r.n):,})", va="center", ha="right",
            fontsize=7, color="white")
ax.set_xlim(0.5, 0.8)
ax.set_xlabel("ROC AUC within the segment")
ax.set_title("Where it works badly: within narrow tenure bands AUC is 0.62–0.67.\n"
             "Most of the overall 0.743 lift is ranking across tenure, not inside it.",
             fontsize=9.5)
ax.legend(fontsize=8, loc="lower right")
fig.tight_layout()
fig.savefig(OUT / "fig4d_segment_auc.png")
plt.close(fig)

print("wrote:", ", ".join(sorted(p.name for p in OUT.glob("*.png"))))
