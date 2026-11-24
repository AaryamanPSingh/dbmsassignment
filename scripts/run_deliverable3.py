#!/usr/bin/env python3
"""Run every Deliverable-3 SQL query, then compute the confidence intervals
and significance tests, writing CSVs + a summary markdown.

    python3 scripts/load_data.py            # if telemetry.db is missing
    python3 scripts/run_deliverable3.py
"""
import csv
import re
import sqlite3
from pathlib import Path

import numpy as np
from scipy import stats

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "telemetry.db"
SQL_FILE = ROOT / "sql" / "deliverable3.sql"
OUT_DIR = ROOT / "outputs" / "deliverable3"

SUMMARY_SECTIONS = {
    "3a_channel_period",
    "3a_channel_tier",
    "3a_channel_install_month",
    "3b_naive_vs_std",
    "3c_ltv30_channel",
    "3c_ltv30_channel_tier",
    "3c_ltv30_tier_std",
    "3d_retention_channel_pooled",
    "3d_retention_channel_month",
    "3e_playtime_channel",
    "3e_playtime_channel_tier",
    "3e_playtime_device",
    "checks_d3",
}

CHANNELS = ["organic", "paid_social", "paid_video"]
PAIRS = [("organic", "paid_social"), ("organic", "paid_video"),
         ("paid_social", "paid_video")]
BOOT_ITERS = 10_000
BOOT_SEED = 20261124


def split_sections(sql_text: str) -> dict[str, str]:
    parts = re.split(r"^-- @(\S+)$", sql_text, flags=re.M)
    sections: dict[str, str] = {}
    for i in range(1, len(parts), 2):
        sections[parts[i]] = parts[i + 1].strip()
    return sections


def read_csv(name: str) -> list[dict]:
    with (OUT_DIR / name).open() as fh:
        return list(csv.DictReader(fh))


def bootstrap_means(values: np.ndarray, groups: np.ndarray) -> dict[str, np.ndarray]:
    """Bootstrap the mean of `values` within each group label (fixed seed)."""
    rng = np.random.default_rng(BOOT_SEED)
    out: dict[str, np.ndarray] = {}
    for g in np.unique(groups):
        arr = values[groups == g]
        n = len(arr)
        means = np.empty(BOOT_ITERS)
        for i in range(BOOT_ITERS):
            means[i] = arr[rng.integers(0, n, n)].mean()
        out[str(g)] = means
    return out


def prop_test(x1: int, n1: int, x2: int, n2: int) -> tuple[float, float, float, float]:
    """Two-proportion z-test. Returns (delta, ci_low, ci_high, p)."""
    p1, p2 = x1 / n1, x2 / n2
    delta = p1 - p2
    se_unpooled = np.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    lo, hi = delta - 1.96 * se_unpooled, delta + 1.96 * se_unpooled
    p_pool = (x1 + x2) / (n1 + n2)
    se_pool = np.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2))
    z = delta / se_pool
    p = 2 * stats.norm.sf(abs(z))
    return delta, lo, hi, p


def signif_row(metric: str, a: str, b: str, mean_a: float, mean_b: float,
               delta: float, lo: float, hi: float, p: float,
               method: str, n_a: int, n_b: int) -> dict:
    rel = 100.0 * delta / mean_b if mean_b else float("nan")
    rel_lo = 100.0 * lo / mean_b if mean_b else float("nan")
    rel_hi = 100.0 * hi / mean_b if mean_b else float("nan")
    return {
        "metric": metric, "a": a, "b": b,
        "mean_a": round(mean_a, 4), "mean_b": round(mean_b, 4),
        "delta": round(delta, 4), "ci_low": round(lo, 4), "ci_high": round(hi, 4),
        "rel_pct_vs_b": round(rel, 2),
        "rel_ci_low_pct": round(rel_lo, 2), "rel_ci_high_pct": round(rel_hi, 2),
        "p_value": f"{p:.4g}",
        "significant_05": "yes" if p < 0.05 else "no",
        "method": method, "n_a": n_a, "n_b": n_b,
    }


def run_significance() -> None:
    rows_s: list[dict] = []
    rows_m: list[dict] = []

    # ---- revenue per install (bootstrap, skewed distribution) ----
    inst = read_csv("3c_ltv30_install_rows.csv")
    rev = {c: np.array([float(r["rev30"]) for r in inst if r["channel"] == c])
           for c in CHANNELS}
    grp = np.array([r["channel"] for r in inst])
    rev_all = np.array([float(r["rev30"]) for r in inst])
    boot_rev = bootstrap_means(rev_all, grp)
    for c in CHANNELS:
        lo, hi = np.percentile(boot_rev[c], [2.5, 97.5])
        rows_m.append({"metric": "revenue_per_install_30d", "channel": c,
                       "mean": round(rev[c].mean(), 4),
                       "ci_low": round(lo, 4), "ci_high": round(hi, 4),
                       "n": len(rev[c]), "method": f"bootstrap {BOOT_ITERS}"})
    for a, b in PAIRS:
        d = boot_rev[a] - boot_rev[b]
        lo, hi = np.percentile(d, [2.5, 97.5])
        p = 2 * min((d <= 0).mean(), (d >= 0).mean())
        rows_s.append(signif_row("revenue_per_install_30d", a, b,
                                 rev[a].mean(), rev[b].mean(),
                                 rev[a].mean() - rev[b].mean(), lo, hi, p,
                                 f"bootstrap {BOOT_ITERS} of mean diff",
                                 len(rev[a]), len(rev[b])))

    # ---- 30-day payer rate (two-proportion z) ----
    paid = {c: sum(int(r["paid30"]) for r in inst if r["channel"] == c)
            for c in CHANNELS}
    for c in CHANNELS:
        n, x = len(rev[c]), paid[c]
        rows_m.append({"metric": "payer_rate_30d", "channel": c,
                       "mean": round(100 * x / n, 2),
                       "ci_low": round(100 * (x / n - 1.96 * np.sqrt((x/n)*(1-x/n)/n)), 2),
                       "ci_high": round(100 * (x / n + 1.96 * np.sqrt((x/n)*(1-x/n)/n)), 2),
                       "n": n, "method": "normal approx on proportion"})
    for a, b in PAIRS:
        delta, lo, hi, p = prop_test(paid[a], len(rev[a]), paid[b], len(rev[b]))
        rows_s.append(signif_row("payer_rate_30d", a, b,
                                 100 * paid[a] / len(rev[a]),
                                 100 * paid[b] / len(rev[b]),
                                 100 * delta, 100 * lo, 100 * hi, p,
                                 "two-proportion z-test (pp scale)",
                                 len(rev[a]), len(rev[b])))

    # ---- D7 retention (two-proportion z on pooled matured cohorts) ----
    ret = read_csv("3d_retention_channel_pooled.csv")
    by_c = {r["channel"]: r for r in ret}
    d7 = {c: (int(by_c[c]["d7_retained"]), int(by_c[c]["d7_matured"]))
          for c in CHANNELS}
    for c in CHANNELS:
        x, n = d7[c]
        se = np.sqrt((x / n) * (1 - x / n) / n)
        rows_m.append({"metric": "d7_retention", "channel": c,
                       "mean": round(100 * x / n, 2),
                       "ci_low": round(100 * (x / n - 1.96 * se), 2),
                       "ci_high": round(100 * (x / n + 1.96 * se), 2),
                       "n": n, "method": "normal approx on proportion"})
    for a, b in PAIRS:
        delta, lo, hi, p = prop_test(d7[a][0], d7[a][1], d7[b][0], d7[b][1])
        rows_s.append(signif_row("d7_retention", a, b,
                                 100 * d7[a][0] / d7[a][1],
                                 100 * d7[b][0] / d7[b][1],
                                 100 * delta, 100 * lo, 100 * hi, p,
                                 "two-proportion z-test (pp scale)",
                                 d7[a][1], d7[b][1]))

    # ---- playtime minutes per recorded day (bootstrap at DEVICE level) ----
    dev = read_csv("3e_playtime_device_rows.csv")
    mins = np.array([float(r["avg_minutes_per_day"]) for r in dev])
    dgrp = np.array([r["channel"] for r in dev])
    boot_min = bootstrap_means(mins, dgrp)
    dev_by = {c: mins[dgrp == c] for c in CHANNELS}
    for c in CHANNELS:
        lo, hi = np.percentile(boot_min[c], [2.5, 97.5])
        rows_m.append({"metric": "minutes_per_recorded_day", "channel": c,
                       "mean": round(dev_by[c].mean(), 3),
                       "ci_low": round(lo, 3), "ci_high": round(hi, 3),
                       "n": len(dev_by[c]), "method": f"device bootstrap {BOOT_ITERS}"})
    for a, b in PAIRS:
        d = boot_min[a] - boot_min[b]
        lo, hi = np.percentile(d, [2.5, 97.5])
        p = 2 * min((d <= 0).mean(), (d >= 0).mean())
        rows_s.append(signif_row("minutes_per_recorded_day", a, b,
                                 dev_by[a].mean(), dev_by[b].mean(),
                                 dev_by[a].mean() - dev_by[b].mean(), lo, hi, p,
                                 f"device bootstrap {BOOT_ITERS} of mean diff",
                                 len(dev_by[a]), len(dev_by[b])))

    # ---- tier-standardised revenue/install (stratified bootstrap) ----
    # Resample installs within each channel x tier cell; standardise every
    # replicate to the ORIGINAL pooled tier mix (weights fixed). This gives
    # the CI on the mix-adjusted gap — the number that decides whether the
    # naive revenue gap survives adjustment.
    tiers = sorted({int(r["tier"]) for r in inst})
    n_by = {(c, t): sum(1 for r in inst
                        if r["channel"] == c and int(r["tier"]) == t)
            for c in CHANNELS for t in tiers}
    pooled_n = len(inst)
    w = {t: sum(n_by[(c, t)] for c in CHANNELS) / pooled_n for t in tiers}
    cells = {(c, t): np.array([float(r["rev30"]) for r in inst
                               if r["channel"] == c and int(r["tier"]) == t])
             for c in CHANNELS for t in tiers}

    rng = np.random.default_rng(BOOT_SEED + 1)
    std_rev = {c: np.empty(BOOT_ITERS) for c in CHANNELS}
    std_pay = {c: np.empty(BOOT_ITERS) for c in CHANNELS}
    cells_paid = {(c, t): np.array([int(r["paid30"]) for r in inst
                                    if r["channel"] == c and int(r["tier"]) == t])
                  for c in CHANNELS for t in tiers}
    for i in range(BOOT_ITERS):
        for c in CHANNELS:
            rev_m = pay_m = 0.0
            for t in tiers:
                idx = rng.integers(0, n_by[(c, t)], n_by[(c, t)])
                rev_m += w[t] * cells[(c, t)][idx].mean()
                pay_m += w[t] * cells_paid[(c, t)][idx].mean()
            std_rev[c][i], std_pay[c][i] = rev_m, 100 * pay_m
    for metric, draws, point_fn in [
            ("revenue_per_install_30d_tier_std", std_rev,
             lambda c: sum(w[t] * cells[(c, t)].mean() for t in tiers)),
            ("payer_rate_30d_tier_std", std_pay,
             lambda c: 100 * sum(w[t] * cells_paid[(c, t)].mean()
                                 for t in tiers))]:
        for c in CHANNELS:
            lo, hi = np.percentile(draws[c], [2.5, 97.5])
            rows_m.append({"metric": metric, "channel": c,
                           "mean": round(point_fn(c), 4),
                           "ci_low": round(lo, 4), "ci_high": round(hi, 4),
                           "n": sum(n_by[(c, t)] for t in tiers),
                           "method": f"stratified bootstrap {BOOT_ITERS} "
                                     f"(pooled tier mix fixed)"})
        for a, b in PAIRS:
            d = draws[a] - draws[b]
            lo, hi = np.percentile(d, [2.5, 97.5])
            p = 2 * min((d <= 0).mean(), (d >= 0).mean())
            rows_s.append(signif_row(
                metric, a, b, point_fn(a), point_fn(b),
                point_fn(a) - point_fn(b), lo, hi, p,
                f"stratified bootstrap {BOOT_ITERS} of std mean diff",
                sum(n_by[(a, t)] for t in tiers),
                sum(n_by[(b, t)] for t in tiers)))

    for name, rows in [("3g_significance.csv", rows_s),
                       ("3g_channel_means.csv", rows_m)]:
        with (OUT_DIR / name).open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print(f"{name:32s} {len(rows):6d} rows -> {(OUT_DIR / name).relative_to(ROOT)}")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sections = split_sections(SQL_FILE.read_text())
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    summary_rows: list[str] = []
    for name, sql in sections.items():
        if name == "setup":
            conn.executescript(sql)
            continue
        cur = conn.execute(sql)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        out = OUT_DIR / f"{name}.csv"
        with out.open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(cols)
            w.writerows(rows)
        print(f"{name:32s} {len(rows):6d} rows -> {out.relative_to(ROOT)}")

        if name in SUMMARY_SECTIONS:
            summary_rows.append(f"\n### {name}\n")
            summary_rows.append("| " + " | ".join(cols) + " |")
            summary_rows.append("|" + "---|" * len(cols))
            for r in rows[:40]:
                summary_rows.append("| " + " | ".join(
                    "" if v is None else str(v) for v in r) + " |")

    conn.close()

    run_significance()
    summary_rows.append("\n### 3g_significance\n")
    with (OUT_DIR / "3g_significance.csv").open() as fh:
        for line in fh:
            summary_rows.append("| " + line.strip().replace(",", " | ") + " |")

    (OUT_DIR / "summary.md").write_text("\n".join(summary_rows) + "\n")
    print(f"\nsummary -> {(OUT_DIR / 'summary.md').relative_to(ROOT)}")


if __name__ == "__main__":
    main()
