#!/usr/bin/env python3
"""Generate Deliverable-2 figures from the query CSVs.

Run after scripts/run_deliverable2.py:
    python3 scripts/charts_deliverable2.py
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
IN = ROOT / "outputs" / "deliverable2"
OUT = IN / "figs"
OUT.mkdir(parents=True, exist_ok=True)

plt.rcParams.update({"figure.dpi": 130, "axes.grid": True,
                     "grid.alpha": 0.3, "font.size": 9})

GREEN, RED, BLUE, ORANGE = "#2ca02c", "#d62728", "#4c78a8", "#ff7f0e"

# ---------------------------------------------------------------- 2a waterfall
dec = pd.read_csv(IN / "2a_decomposition.csv")
tot = dec[dec.tier == "TOTAL"].iloc[0]
p1, p2 = tot.arpdau_p1, tot.arpdau_p2
mix, within = tot.mix_effect, tot.within_effect

fig, ax = plt.subplots(figsize=(8, 4.2))
labels = ["P1 first 30d\n(2026-01-01..30)", "mix effect\n(tier shares moved)",
          "within effect\n(each tier monetised\nbetter)", "P2 last 30d\n(2026-04-01..30)"]
# start / float-down / float-up / end
ax.bar(0, p1, color=BLUE)
ax.bar(1, abs(mix), bottom=p1 + mix, color=RED)
ax.bar(2, within, bottom=p1 + mix, color=GREEN)
ax.bar(3, p2, color=BLUE)

notes = [f"${p1:.4f}", f"{mix:+.4f}", f"{within:+.4f}", f"${p2:.4f}  ({100*(p2/p1-1):+.1f}%)"]
tops = [p1, p1, p1 + mix + within, p2]
for i, (txt, top) in enumerate(zip(notes, tops)):
    ax.text(i, top + 0.006, txt, ha="center", fontsize=9, fontweight="bold")
# connectors
for i, y in enumerate([p1, p1 + mix, p1 + mix + within]):
    ax.hlines(y, i + 0.4, i + 0.6, color="gray", lw=0.8, ls="--")

ax.set_xticks(range(4))
ax.set_xticklabels(labels, fontsize=8)
ax.set_ylabel("blended ARPDAU ($)")
ax.set_title("ARPDAU decline decomposes exactly: mix shift -0.081, "
             "within-tier gain +0.022, net -0.058 (-16.5%)")
fig.tight_layout()
fig.savefig(OUT / "fig2a_waterfall.png")
plt.close(fig)

# ------------------------------------------------------- 2b share vs ARPDAU
w = pd.read_csv(IN / "2a_weekly_mix.csv")
weeks, tiers = sorted(w.week_start.unique()), [1, 2, 3, 4]
share = (w.pivot_table(index="week_start", columns="tier", values="share_pct")
          .reindex(weeks)[tiers])
blended = w.groupby("week_start").apply(
    lambda g: g.gross.sum() / g.active_dd.sum()).reindex(weeks)

fig, ax = plt.subplots(figsize=(9, 4.2))
x = range(len(weeks))
bottom = [0.0] * len(weeks)
colors = {1: "#4c78a8", 2: "#72b7b2", 3: "#f58518", 4: "#e45756"}
for t in tiers:
    vals = share[t].tolist()
    ax.bar(x, vals, bottom=bottom, color=colors[t], label=f"tier {t}",
           edgecolor="white", lw=0.5)
    bottom = [b + v for b, v in zip(bottom, vals)]
ax.set_ylabel("share of active device-days (%)")
ax.set_ylim(0, 100)
ax.set_xticks(list(x))
ax.set_xticklabels([pd.Timestamp(ws).strftime("%m-%d") for ws in weeks],
                   rotation=45, ha="right", fontsize=8)
ax.axvline(4.5, color="black", lw=1.0, ls=":")
_chip = dict(facecolor="black", alpha=0.45, edgecolor="none", pad=1.5)
ax.text(1.5, 5, "P1 first 30d", ha="center", fontsize=8, fontweight="bold",
        color="white", bbox=_chip)
ax.text(6.5, 5, "P2 last 30d", ha="center", fontsize=8, fontweight="bold",
        color="white", bbox=_chip)

ax2 = ax.twinx()
ax2.plot(list(x), blended.values, color="black", lw=1.8, marker="o", ms=4,
         label="blended ARPDAU")
for i, v in enumerate(blended.values):
    ax2.annotate(f"${v:.3f}", (i, v), textcoords="offset points",
                 xytext=(0, 7), ha="center", fontsize=7)
ax2.set_ylabel("blended ARPDAU ($)")
ax2.set_ylim(0, 0.55)
ax2.grid(False)

h1, l1 = ax.get_legend_handles_labels()
h2, l2 = ax2.get_legend_handles_labels()
ax.legend(h1 + h2, l1 + l2, loc="upper left", fontsize=8, ncol=5)
ax.set_title("Tier-4 share of actives: 17.6% -> 45.9% while blended ARPDAU falls "
             "-16.5% (weekly device-day shares)")
fig.tight_layout()
fig.savefig(OUT / "fig2b_share_vs_arpdau.png")
plt.close(fig)

# ------------------------------------------------------------ 2c install ramp
im = pd.read_csv(IN / "2a_installs_month_tier.csv")
months = sorted(im.install_month.unique())
piv = (im.pivot_table(index="install_month", columns="tier", values="share_of_month_pct")
          .reindex(months))

fig, ax = plt.subplots(figsize=(9, 3.8))
bottom = [0.0] * len(months)
for t in tiers:
    vals = piv[t].tolist()
    ax.bar(range(len(months)), vals, bottom=bottom, color=colors[t],
           label=f"tier {t}", edgecolor="white", lw=0.5)
    bottom = [b + v for b, v in zip(bottom, vals)]
ax.set_xticks(range(len(months)))
ax.set_xticklabels(months, rotation=45, ha="right", fontsize=8)
ax.set_ylabel("share of month's installs (%)")
ax.set_ylim(0, 100)
ax.legend(loc="upper left", fontsize=8, ncol=4)
ax.set_title("Install mix by month: tier 4 goes 18% -> 63% of installs "
             "(UA ramp is the engine of the mix shift)")
fig.tight_layout()
fig.savefig(OUT / "fig2c_install_mix.png")
plt.close(fig)

# -------------------------------------------------------- 2d constant mix KPI
d = pd.read_csv(IN / "2a_daily_mix.csv")
d["date"] = pd.to_datetime(d["day_id"], format="%Y%m%d")
d["rate"] = d["gross"] / d["dd"]
p1shares = (dec[dec.tier != "TOTAL"].assign(tier=lambda x: x.tier.astype(int))
            .set_index("tier")["share_p1_pct"] / 100.0)

# rolling means are computed inside each period window so the line never
# bridges the Feb-Mar data gap (no telemetry rows exist between the windows)
segments = []
for pid, g in d.groupby("pid"):
    g = g.sort_values("date")
    piv = g.pivot_table(index="date", columns="tier", values="rate")
    blended = (g.groupby("date")[["gross", "dd"]].sum()
               .assign(a=lambda x: x.gross / x.dd)["a"])
    const = sum(p1shares[t] * piv[t] for t in p1shares.index)
    segments.append(pd.DataFrame(
        {"blended": blended.rolling(7).mean(),
         "const": const.rolling(7).mean()}))

fig, ax = plt.subplots(figsize=(9, 4.2))
for seg in segments:
    ax.plot(seg.index, seg["blended"], color=RED, lw=1.8)
    ax.plot(seg.index, seg["const"], color=GREEN, lw=1.8)
ax.plot([], [], color=RED, lw=1.8, label="blended ARPDAU (observed, 7-day mean)")
ax.plot([], [], color=GREEN, lw=1.8,
        label="ARPDAU at constant Jan tier mix (7-day mean)")
for a, b, lab in [("2026-01-01", "2026-01-30", "P1"), ("2026-04-01", "2026-04-30", "P2")]:
    ax.axvspan(pd.Timestamp(a), pd.Timestamp(b), color="gray", alpha=0.08)
    ax.text(pd.Timestamp(a) + pd.Timedelta(days=4), 0.03, lab,
            fontsize=9, fontweight="bold")
ax.set_ylabel("ARPDAU ($)")
ax.set_ylim(0, 0.62)
ax.legend(loc="upper right", fontsize=8)
ax.set_title("Fix the KPI, not the game: at January's tier mix, April ARPDAU "
             "would match or beat January")
fig.autofmt_xdate(rotation=0)
fig.tight_layout()
fig.savefig(OUT / "fig2d_constant_mix.png")
plt.close(fig)

for p in sorted(OUT.glob("fig2*.png")):
    print(f"{p.relative_to(ROOT)}  {p.stat().st_size // 1024} KB")
