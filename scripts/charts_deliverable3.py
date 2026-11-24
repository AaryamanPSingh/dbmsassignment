#!/usr/bin/env python3
"""Generate Deliverable-3 figures from the query CSVs.

Run after scripts/run_deliverable3.py:
    python3 scripts/charts_deliverable3.py
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
IN = ROOT / "outputs" / "deliverable3"
OUT = IN / "figs"
OUT.mkdir(parents=True, exist_ok=True)

plt.rcParams.update({"figure.dpi": 130, "axes.grid": True,
                     "grid.alpha": 0.3, "font.size": 9})

BLUE, RED, GREEN, ORANGE, GREY = "#4c78a8", "#d62728", "#2ca02c", "#ff7f0e", "#7f7f7f"
CHANNELS = ["organic", "paid_social", "paid_video"]
CH_COLOR = dict(zip(CHANNELS, [GREEN, BLUE, RED]))

# --------------------------------------------- 3a naive vs tier-standardised
ns = pd.read_csv(IN / "3b_naive_vs_std.csv")
periods = [(0, "Pooled"), (1, "P1 first 30d\n(Jan)"), (2, "P2 last 30d\n(Apr)")]

fig, ax = plt.subplots(figsize=(8, 4.4))
w = 0.13  # 6 bars per period group
for i, (pid, _) in enumerate(periods):
    sub = ns[ns.pid == pid].set_index("channel").reindex(CHANNELS)
    for k, c in enumerate(CHANNELS):
        raw, std = sub.arpdau_raw[c], sub.arpdau_tier_std[c]
        x_raw = i + (2 * k - 2.5) * w
        x_std = x_raw + w
        ax.bar(x_raw, raw, w, color=CH_COLOR[c], alpha=0.95)
        ax.bar(x_std, std, w, color=CH_COLOR[c], alpha=0.35,
               edgecolor=CH_COLOR[c], hatch="//")
        ax.text(x_raw, raw + 0.007, f"{raw:.3f}", ha="center", fontsize=6.5)
        ax.text(x_std, std + 0.007, f"{std:.3f}", ha="center", fontsize=6.5,
                color="dimgray")

ax.set_xticks(range(3))
ax.set_xticklabels([lbl for _, lbl in periods])
ax.set_ylim(0, 0.53)
ax.set_ylabel("ARPDAU ($ / active device-day)")
ax.set_title("The naive channel gap is composition: raw ARPDAU (solid) vs "
             "tier-standardised (hatched)\n"
             "paid_video: 0.224 raw pooled -> 0.319 standardised (gap flips sign)",
             fontsize=10)
ax.legend([plt.Rectangle((0, 0), 1, 1, fc=CH_COLOR[c]) for c in CHANNELS]
          + [plt.Rectangle((0, 0), 1, 1, fc="white", ec="gray", hatch="//")],
          CHANNELS + ["hatched = tier-standardised"], loc="upper center",
          fontsize=8, ncol=4, framealpha=0.9)
fig.tight_layout()
fig.savefig(OUT / "fig3a_naive_vs_adjusted.png")
plt.close(fig)

# --------------------------------------------------- 3b install-month confound
im = pd.read_csv(IN / "3a_channel_install_month.csv")
piv = (im.pivot_table(index="install_month", columns="channel",
                      values="installs", aggfunc="sum")
          .reindex(columns=CHANNELS).fillna(0))
piv = piv[piv.sum(axis=1) > 0]
share = piv.div(piv.sum(axis=1), axis=0) * 100

fig, ax = plt.subplots(figsize=(8, 3.8))
bottom = None
for c in CHANNELS:
    ax.bar(share.index, share[c], bottom=bottom, color=CH_COLOR[c], label=c)
    bottom = share[c] if bottom is None else bottom + share[c]
ax.axvspan(7.5, 11.5, color="grey", alpha=0.12)
ax.text(9.5, 46, "activity window\nmeasured here\n(2026-01..04)", ha="center",
        fontsize=8, color="dimgray",
        bbox=dict(fc="white", ec="none", alpha=0.75))
ax.set_ylabel("% of month's installs")
ax.set_title("Confound 2 — calendar mix: paid_video goes from ~15% of installs "
             "to 69% in April", fontsize=10)
ax.legend(fontsize=8, ncol=3, loc="lower left")
plt.setp(ax.get_xticklabels(), rotation=45, ha="right", fontsize=7)
fig.tight_layout()
fig.savefig(OUT / "fig3b_install_mix.png")
plt.close(fig)

# ------------------------------------------------------------ 3c forest plot
sig = pd.read_csv(IN / "3g_significance.csv")
metric_labels = {
    "revenue_per_install_30d": "30-day revenue per install ($)",
    "revenue_per_install_30d_tier_std": "Revenue/install, tier-standardised ($)",
    "payer_rate_30d": "30-day payer rate (pp)",
    "payer_rate_30d_tier_std": "Payer rate, tier-standardised (pp)",
    "d7_retention": "D7 retention (pp)",
    "minutes_per_recorded_day": "Playtime min / recorded day",
}
order = list(metric_labels)
sig["pair"] = sig.a + " − " + sig.b
pairs = ["organic − paid_social", "organic − paid_video",
         "paid_social − paid_video"]

fig, axes = plt.subplots(1, 6, figsize=(18.5, 4.4), sharex=False)
for ax, metric in zip(axes, order):
    sub = sig[sig.metric == metric].set_index("pair").reindex(pairs)
    y = range(len(sub))
    for yi, (pair, row) in zip(y, sub.iterrows()):
        col = GREEN if row.significant_05 == "yes" else GREY
        ax.errorbar(row.delta, yi, xerr=[[row.delta - row.ci_low],
                                         [row.ci_high - row.delta]],
                    fmt="o", color=col, capsize=3, ms=5)
        if row.significant_05 != "yes":
            ax.plot(row.delta, yi, "x", color=col, ms=6)
    ax.axvline(0, color="black", lw=0.9, ls="--")
    ax.set_yticks(list(y))
    ax.set_yticklabels(pairs if ax is axes[0] else ["", "", ""], fontsize=8)
    ax.set_title(metric_labels[metric], fontsize=9)
    ax.set_xlabel("difference (A − B)", fontsize=8)
    ax.tick_params(labelsize=8)
fig.suptitle("All pairwise channel differences with 95% CIs — grey ✗ = not "
             "significant at 5%", fontsize=10, y=1.0)
fig.tight_layout()
fig.savefig(OUT / "fig3c_forest.png", bbox_inches="tight")
plt.close(fig)

# --------------------------------------------------- 3d channel means + CIs
means = pd.read_csv(IN / "3g_channel_means.csv")
fig, axes = plt.subplots(1, 6, figsize=(16, 3.6))
for ax, metric in zip(axes, order):
    sub = means[means.metric == metric].set_index("channel").reindex(CHANNELS)
    xs = range(3)
    ax.bar(xs, sub["mean"],
           yerr=[sub["mean"] - sub.ci_low, sub.ci_high - sub["mean"]],
           color=[CH_COLOR[c] for c in CHANNELS], capsize=4, alpha=0.9)
    for x, (m, hi) in zip(xs, zip(sub["mean"], sub.ci_high)):
        ax.text(x, hi * 1.01, f"{m:g}", ha="center", va="bottom", fontsize=8,
                fontweight="bold")
    ax.set_xticks(list(xs))
    ax.set_xticklabels(CHANNELS, rotation=20, fontsize=8)
    ax.set_title(metric_labels[metric], fontsize=9)
fig.suptitle("Headline measures by channel (mean ± 95% CI)", fontsize=10, y=1.02)
fig.tight_layout()
fig.savefig(OUT / "fig3d_channel_means.png", bbox_inches="tight")
plt.close(fig)

print("figures written to", OUT.relative_to(ROOT))
for f in sorted(OUT.glob("*.png")):
    print("  ", f.name)
