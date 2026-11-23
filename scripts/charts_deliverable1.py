#!/usr/bin/env python3
"""Generate Deliverable-1 figures from the query CSVs.

Run after scripts/run_deliverable1.py:
    python3 scripts/charts_deliverable1.py
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
IN = ROOT / "outputs" / "deliverable1"
OUT = IN / "figs"
OUT.mkdir(parents=True, exist_ok=True)

plt.rcParams.update({"figure.dpi": 130, "axes.grid": True,
                     "grid.alpha": 0.3, "font.size": 9})

# ---------------------------------------------------------------- 1a daily
d = pd.read_csv(IN / "1a_daily_health.csv")
d["date"] = pd.to_datetime(d["day_id"], format="%Y%m%d")

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9, 5.6), sharex=True)
for plat, g in d.groupby("platform"):
    ax1.plot(g["date"], g["dau"], label=plat, lw=1.4)
    ax2.plot(g["date"], g["gross_revenue"], label=plat, lw=1.4)
ax1.set_ylabel("DAU")
ax1.set_title("Daily DAU and gross revenue by platform (2026-01-01 to 2026-04-30)")
ax1.legend(loc="upper left")
ax2.set_ylabel("gross revenue ($, deduplicated, positive rows)")
ax2.legend(loc="upper left")
fig.tight_layout()
fig.savefig(OUT / "fig1a_daily_health.png")
plt.close(fig)

# ---------------------------------------------------------------- 1b retention
r = pd.read_csv(IN / "1b_retention_cohorts.csv")
r["label"] = pd.to_datetime(r["week_start"]).dt.strftime("%m-%d")
cols = [("d1_pct", "D1"), ("d7_pct", "D7"), ("d14_pct", "D14"), ("d30_pct", "D30")]
x = range(len(r))
width = 0.2
fig, ax = plt.subplots(figsize=(9, 4))
for i, (c, lab) in enumerate(cols):
    ax.bar([xi + i * width for xi in x], r[c].fillna(0), width,
           label=lab, edgecolor="white", lw=0.4)
ax.set_xticks([xi + 1.5 * width for xi in x])
ax.set_xticklabels(r["label"], rotation=90, fontsize=7)
ax.set_ylabel("% of cohort active")
ax.set_title("Install-week cohorts: retention at D1/D7/D14/D30 "
             "(missing bar = cohort not yet mature / left-censored)")
ax.legend(ncol=4)
fig.tight_layout()
fig.savefig(OUT / "fig1b_retention.png")
plt.close(fig)

# ---------------------------------------------------------------- 1c time to first
t = pd.read_csv(IN / "1c2_time_to_first_purchase.csv")
t = t[~t["bucket"].str.startswith("00")]
labels = t["bucket"].str.slice(3)
fig, ax = plt.subplots(figsize=(8, 3.8))
ax.bar(labels, t["pct_of_payers"], color="#4c78a8")
for i, v in enumerate(t["pct_of_payers"]):
    ax.text(i, v + 0.3, f"{v}%", ha="center", fontsize=8)
ax.set_ylabel("% of payers")
ax.set_title("Time from install to first purchase "
             "(in-window installs, negative-day anomalies excluded: 110)")
plt.setp(ax.get_xticklabels(), rotation=30, ha="right", fontsize=8)
fig.tight_layout()
fig.savefig(OUT / "fig1c_time_to_first.png")
plt.close(fig)

# ---------------------------------------------------------------- 1d ad series
a = pd.read_csv(IN / "1d2_daily_ad_views.csv")
a["date"] = pd.to_datetime(a["local_day"], format="%Y%m%d")
# reindex to a complete daily range so the outage renders as a real gap
a = (a.set_index("date")
       .reindex(pd.date_range(a["date"].min(), a["date"].max()))
       .rename_axis("date").reset_index())

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9, 5.6), sharex=True)
ax1.plot(a["date"], a["completed"], lw=1.3, label="completed ads")
ax1.plot(a["date"], a["dau"], lw=1.3, color="tab:orange", label="DAU")
ax1.axvspan(pd.Timestamp("2026-03-05"), pd.Timestamp("2026-03-07"),
            color="red", alpha=0.15, label="ad telemetry outage (local Mar 5-6)")
ax1.set_ylabel("count")
ax1.set_title("Daily ad completions vs DAU, local dates "
              "(raw timestamps shifted -8h); no day trips the <60% trailing-7d flag")
ax1.legend(loc="upper left")

ax2.plot(a["date"], a["completed_per_100_dau"], lw=1.3,
         color="tab:green", label="completed per 100 DAU")
ax2.axvspan(pd.Timestamp("2026-03-05"), pd.Timestamp("2026-03-07"),
            color="red", alpha=0.15)
ax2.set_ylabel("completed / 100 DAU")
ax2.legend(loc="upper left")
fig.tight_layout()
fig.savefig(OUT / "fig1d_ad_series.png")
plt.close(fig)

for p in sorted(OUT.glob("*.png")):
    print(f"{p.relative_to(ROOT)}  {p.stat().st_size // 1024} KB")
