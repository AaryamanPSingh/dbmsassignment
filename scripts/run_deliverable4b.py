#!/usr/bin/env python3
"""Deliverable 4b (optional) — 90-day revenue of a new install.

Runs sql/deliverable4b.sql, then fits a two-part model with NumPy only:
  1. P(payer in first 90 days)          logistic, L2, Newton/IRLS
  2. E[revenue | payer]                 ridge on log1p(revenue)
and scores installs by P(payer) * E[revenue | payer] so the ranking is an
expected 90-day value, which is what a UA bid should follow.

Only installs from 2026-01-01..2026-01-30 can be labelled: earlier installs
have no observed first week, later installs have a truncated 90-day outcome.

    python3 scripts/load_data.py
    python3 scripts/run_deliverable4b.py
"""

import csv
import math
import re
import sqlite3
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "telemetry.db"
SQL_FILE = ROOT / "sql" / "deliverable4b.sql"
OUT_DIR = ROOT / "outputs" / "deliverable4"

NUMERIC = [
    "active_days_7", "recorded_days_7", "sessions_7", "playtime_7",
    "level_last_7", "revenue_7", "purchases_7",
    "ads_completed_7", "ad_days_7",
    "cs_premium_7", "cs_social_7", "cs_grind_7", "cs_value_7",
    "days_to_first_purchase",
]
LOG1P = {
    "revenue_7", "purchases_7", "playtime_7", "ads_completed_7",
    "cs_premium_7", "cs_social_7", "cs_grind_7", "cs_value_7",
}
CATEGORICAL = ["platform", "country_tier", "acquisition_channel"]

LAMBDAS = [0.1, 1.0, 10.0, 100.0]
EPS = 1e-12
TOP_FRACS = (0.05, 0.10, 0.20, 0.30, 0.50)


# --------------------------------------------------------------------------- #
# SQL execution
# --------------------------------------------------------------------------- #
def split_sections(sql_text: str) -> dict[str, str]:
    parts = re.split(r"^-- @(\S+)$", sql_text, flags=re.M)
    return {parts[i]: parts[i + 1].strip() for i in range(1, len(parts), 2)}


def write_rows(path: Path, cols: list[str], rows: list[list]) -> None:
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        w.writerows(rows)


def verify_checks(rows: list[sqlite3.Row]) -> None:
    """Fail loudly on any reconciliation check that does not hold."""
    bad = []
    for r in rows:
        observed, expected = str(r["observed"]), str(r["expected"])
        if expected == "equal":
            parts = [p.strip() for p in observed.split("/")]
            ok = len(parts) == 2 and parts[0] == parts[1]
        elif expected == "true":
            parts = [p.strip() for p in observed.split("<")]
            ok = len(parts) == 4 and all(a < b for a, b in zip(parts, parts[1:]))
        elif expected == "0":
            ok = observed == "0"
        else:
            ok = observed.split(" = ")[-1].strip() == expected
        if not ok:
            bad.append(f"{r['check_item']}: observed {observed!r}, expected {expected!r}")
    if bad:
        raise RuntimeError("4b checks failed:\n  " + "\n  ".join(bad))


def run_sql() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sections = split_sections(SQL_FILE.read_text())
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    checks = []
    for name, sql in sections.items():
        if name == "setup" or name.endswith("_build"):
            conn.executescript(sql)
            continue
        cur = conn.execute(sql)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        write_rows(OUT_DIR / f"{name}.csv", cols, [list(r) for r in rows])
        print(f"{name:26s} {len(rows):7d} rows -> outputs/deliverable4/{name}.csv")
        if name == "checks_d4b":
            checks = rows
    conn.close()
    if not checks:
        raise RuntimeError("checks_d4b did not run")
    verify_checks(checks)
    print(f"checks_d4b: {len(checks)}/{len(checks)} passed")


# --------------------------------------------------------------------------- #
# Data preparation
# --------------------------------------------------------------------------- #
def read_cohort() -> list[dict]:
    with (OUT_DIR / "4b_cohort.csv").open() as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        for k in NUMERIC:
            r[k] = float(r[k])
        for k in ("payer_90", "first_week_payer", "purchases_7"):
            r[k] = int(r[k])
        r["revenue_90"] = float(r["revenue_90"])
        r["revenue_7"] = float(r["revenue_7"])
        r["install_day"] = int(r["install_day"])
    return rows


def transform_numeric(rows: list[dict], key: str) -> np.ndarray:
    if key in LOG1P:
        return np.array([math.log1p(r[key]) for r in rows])
    return np.array([r[key] for r in rows])


def build_design(rows: list[dict], categories=None, scaler=None):
    """Return (X, columns, categories, scaler); fit on `rows` when scaler None."""
    raw = {k: transform_numeric(rows, k) for k in NUMERIC}
    if scaler is None:
        mean = {k: float(v.mean()) for k, v in raw.items()}
        std = {k: float(v.std()) or 1.0 for k, v in raw.items()}
        scaler = (mean, std)
    mean, std = scaler

    if categories is None:
        categories = {}
        for c in CATEGORICAL:
            categories[c] = sorted({str(r[c]) for r in rows})

    cols: list[str] = []
    blocks: list[np.ndarray] = []
    for k in NUMERIC:
        cols.append(f"log1p({k})" if k in LOG1P else k)
        blocks.append(((raw[k] - mean[k]) / std[k])[:, None])

    for c in CATEGORICAL:
        ref = categories[c][0]
        for level in categories[c][1:]:
            cols.append(f"{c}={level} (ref {ref})")
            blocks.append(np.array([1.0 if str(r[c]) == level else 0.0 for r in rows])[:, None])

    X = np.hstack(blocks)
    cols.append("intercept")
    X = np.hstack([X, np.ones((len(rows), 1))])
    return X, cols, categories, scaler


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
def sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(z, -35, 35)))


def fit_logistic(X: np.ndarray, y: np.ndarray, lam: float, max_iter: int = 100) -> np.ndarray:
    n, p = X.shape
    beta = np.zeros(p)
    penalty = np.ones(p)
    penalty[-1] = 0.0
    for _ in range(max_iter):
        mu = sigmoid(X @ beta)
        w = np.clip(mu * (1.0 - mu), 1e-9, None)
        grad = X.T @ (mu - y) + lam * penalty * beta
        H = X.T @ (X * w[:, None])
        H[np.diag_indices(p)] += lam * penalty + 1e-8
        step = np.linalg.solve(H, grad)
        beta_new = beta - step
        if not np.all(np.isfinite(beta_new)):
            beta_new = beta - 0.1 * step
        beta = beta_new
        if np.max(np.abs(step)) < 1e-9:
            break
    return beta


def fit_ridge(X: np.ndarray, y: np.ndarray, lam: float) -> np.ndarray:
    n, p = X.shape
    penalty = np.ones(p)
    penalty[-1] = 0.0
    A = X.T @ X + lam * np.diag(penalty) + 1e-10 * np.eye(p)
    return np.linalg.solve(A, X.T @ y)


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #
def roc_auc(y: np.ndarray, score: np.ndarray) -> float:
    order = np.argsort(score, kind="mergesort")
    ranks = np.empty(len(score), dtype=float)
    ranks[order] = np.arange(1, len(score) + 1)
    uniq, inv, counts = np.unique(score, return_inverse=True, return_counts=True)
    if np.any(counts > 1):
        sums = np.zeros(len(uniq))
        np.add.at(sums, inv, ranks)
        ranks = (sums / counts)[inv]
    n_pos = int(y.sum())
    n_neg = len(y) - n_pos
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    return float((ranks[y == 1].sum() - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg))


def average_precision(y: np.ndarray, score: np.ndarray) -> float:
    order = np.argsort(-score, kind="mergesort")
    y_sorted = y[order]
    tps = np.cumsum(y_sorted)
    precision = tps / np.arange(1, len(y_sorted) + 1)
    pos_idx = np.where(y_sorted == 1)[0]
    if len(pos_idx) == 0:
        return float("nan")
    return float(precision[pos_idx].mean())


def log_loss(y: np.ndarray, p: np.ndarray) -> float:
    p = np.clip(p, EPS, 1 - EPS)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def brier(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean((p - y) ** 2))


def rankdata(v: np.ndarray) -> np.ndarray:
    """Average ranks, so Spearman handles the many zero-revenue ties."""
    order = np.argsort(v, kind="mergesort")
    sorted_v = v[order]
    ranks = np.empty(len(v), dtype=float)
    i = 0
    while i < len(v):
        j = i
        while j + 1 < len(v) and sorted_v[j + 1] == sorted_v[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return ranks


def spearman(a: np.ndarray, b: np.ndarray) -> float:
    ra, rb = rankdata(a), rankdata(b)
    ra = ra - ra.mean()
    rb = rb - rb.mean()
    denom = math.sqrt(float(ra @ ra) * float(rb @ rb))
    return float(ra @ rb / denom) if denom > 0 else float("nan")


def top_revenue_metrics(y: np.ndarray, score: np.ndarray) -> dict:
    order = np.argsort(-score, kind="mergesort")
    total = float(y.sum())
    base = float(y.mean())
    n = len(y)
    out = {"spearman": spearman(score, y), "mean_rev_90": base}
    for frac in TOP_FRACS:
        k = max(1, int(round(n * frac)))
        idx = order[:k]
        mean_top = float(y[idx].mean())
        out[f"top{int(frac * 100)}_mean_rev"] = mean_top
        out[f"top{int(frac * 100)}_lift"] = mean_top / base if base > 0 else float("nan")
        out[f"top{int(frac * 100)}_capture_pct"] = (
            100.0 * float(y[idx].sum()) / total if total > 0 else float("nan")
        )
    return out


def bootstrap_ci(y: np.ndarray, score: np.ndarray, payer: np.ndarray,
                 n_boot: int = 1000, seed: int = 20261124) -> dict:
    rng = np.random.default_rng(seed)
    n = len(y)
    aucs, aps, sps, lifts = [], [], [], []
    for _ in range(n_boot):
        idx = rng.integers(0, n, n)
        yy, pp, ss = y[idx], payer[idx], score[idx]
        if pp.sum() == 0 or pp.sum() == n:
            continue
        aucs.append(roc_auc(pp, score[idx]))
        aps.append(average_precision(pp, score[idx]))
        sps.append(spearman(ss, yy))
        k = max(1, int(round(n * 0.10)))
        top = np.argsort(-ss, kind="mergesort")[:k]
        mean_top = float(yy[top].mean())
        lifts.append(mean_top / float(yy.mean()) if yy.mean() > 0 else float("nan"))
    def ci(v):
        v = np.array([x for x in v if np.isfinite(x)])
        return (round(float(np.percentile(v, 2.5)), 4),
                round(float(np.percentile(v, 97.5)), 4))
    a_low, a_high = ci(aucs)
    p_low, p_high = ci(aps)
    s_low, s_high = ci(sps)
    l_low, l_high = ci(lifts)
    return {
        "auc_ci_low": a_low, "auc_ci_high": a_high,
        "pr_auc_ci_low": p_low, "pr_auc_ci_high": p_high,
        "spearman_ci_low": s_low, "spearman_ci_high": s_high,
        "top10_lift_ci_low": l_low, "top10_lift_ci_high": l_high,
        "bootstrap_iters": len(aucs),
    }


def decile_table(kind: str, y: np.ndarray, predicted: np.ndarray) -> list[dict]:
    order = np.argsort(predicted, kind="mergesort")
    out = []
    for i, idx in enumerate(np.array_split(order, 10), 1):
        if len(idx) == 0:
            continue
        out.append({
            "kind": kind,
            "decile": i,
            "n": int(len(idx)),
            "predicted_mean": round(float(predicted[idx].mean()), 4),
            "observed_mean": round(float(y[idx].mean()), 4),
            "gap": round(float(predicted[idx].mean()) - float(y[idx].mean()), 4),
            "score_min": round(float(predicted[idx].min()), 4),
            "score_max": round(float(predicted[idx].max()), 4),
        })
    return out


def segment_table(test: list[dict], p_pay: np.ndarray, score: np.ndarray,
                  y_rev: np.ndarray, payer: np.ndarray) -> list[dict]:
    keys = ["acquisition_channel", "country_tier", "platform", "first_week_payer"]
    out = []
    for key in keys:
        values = sorted({str(r[key]) for r in test})
        for v in values:
            idx = np.array([i for i, r in enumerate(test) if str(r[key]) == v])
            yy, pp, ss = y_rev[idx], payer[idx], score[idx]
            tm = top_revenue_metrics(yy, ss)
            auc_v = roc_auc(pp, p_pay[idx])
            ap_v = average_precision(pp, p_pay[idx])
            out.append({
                "segment": key,
                "value": v,
                "n": int(len(idx)),
                "payers": int(pp.sum()),
                "payer_rate_pct": round(100.0 * float(pp.mean()), 2),
                "revenue_auc": round(auc_v, 4) if np.isfinite(auc_v) else "",
                "revenue_pr_auc": round(ap_v, 4) if np.isfinite(ap_v) else "",
                "spearman": round(tm["spearman"], 4),
                "mean_rev_90": round(float(yy.mean()), 2),
                "top10_mean_rev": round(tm["top10_mean_rev"], 2),
                "top10_lift": round(tm["top10_lift"], 2),
                "reliable": "yes" if pp.sum() >= 30 else "no (<30 payers)",
            })
    j2125 = [i for i, r in enumerate(test) if "2026-01-21" <= r["install_date"] <= "2026-01-25"]
    j2630 = [i for i, r in enumerate(test) if "2026-01-26" <= r["install_date"] <= "2026-01-30"]
    for label, idx in (("Jan21-25", j2125), ("Jan26-30", j2630)):
        idx = np.array(idx)
        yy, pp, ss = y_rev[idx], payer[idx], score[idx]
        tm = top_revenue_metrics(yy, ss)
        auc_v = roc_auc(pp, p_pay[idx])
        ap_v = average_precision(pp, p_pay[idx])
        out.append({
            "segment": "install_window",
            "value": label,
            "n": int(len(idx)),
            "payers": int(pp.sum()),
            "payer_rate_pct": round(100.0 * float(pp.mean()), 2),
            "revenue_auc": round(auc_v, 4) if np.isfinite(auc_v) else "",
            "revenue_pr_auc": round(ap_v, 4) if np.isfinite(ap_v) else "",
            "spearman": round(tm["spearman"], 4),
            "mean_rev_90": round(float(yy.mean()), 2),
            "top10_mean_rev": round(tm["top10_mean_rev"], 2),
            "top10_lift": round(tm["top10_lift"], 2),
            "reliable": "yes" if pp.sum() >= 30 else "no (<30 payers)",
        })
    return out


def revenue_distribution(y: np.ndarray) -> list[dict]:
    edges = [0.0, 5.0, 10.0, 25.0, 50.0, 100.0, 250.0]
    labels = ["0", "$0-5", "$5-10", "$10-25", "$25-50", "$50-100", "$100-250", "$250+"]
    total_rev = float(y.sum())
    out = []
    for i, label in enumerate(labels):
        if i == 0:
            mask = y == 0
        elif i < len(edges):
            lo, hi = edges[i - 1], edges[i]
            mask = (y > lo) & (y <= hi)
        else:
            mask = y > edges[-1]
        n = int(mask.sum())
        rev = float(y[mask].sum())
        out.append({
            "bucket": label,
            "installs": n,
            "share_installs_pct": round(100.0 * n / len(y), 2),
            "revenue_usd": round(rev, 2),
            "share_revenue_pct": round(100.0 * rev / total_rev, 2) if total_rev else 0.0,
        })
    return out


def percentile(values: np.ndarray, p: float) -> float:
    return float(np.percentile(values, p)) if len(values) else float("nan")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> None:
    run_sql()
    rows = read_cohort()
    train = [r for r in rows if r["split"] == "train"]
    valid = [r for r in rows if r["split"] == "validation"]
    test = [r for r in rows if r["split"] == "test"]
    print(f"\ncohort: {len(rows):,} labelable installs | train {len(train):,} | "
          f"validation {len(valid):,} | test {len(test):,}")

    def arrays(rs):
        return (np.array([r["revenue_90"] for r in rs], dtype=float),
                np.array([r["payer_90"] for r in rs], dtype=float),
                np.array([r["first_week_payer"] for r in rs], dtype=float))

    y_rev_tr, y_pay_tr, _ = arrays(train)
    y_rev_va, y_pay_va, _ = arrays(valid)
    y_rev_te, y_pay_te, _ = arrays(test)

    # ---- stage 1: P(payer in 90 days), lambda by validation log loss --------
    X_tr, cols, categories, scaler = build_design(train)
    X_va, _, _, _ = build_design(valid, categories, scaler)
    X_te, _, _, _ = build_design(test, categories, scaler)

    pay_selection = []
    for lam in LAMBDAS:
        beta = fit_logistic(X_tr, y_pay_tr, lam)
        p_va = sigmoid(X_va @ beta)
        pay_selection.append({
            "lambda": lam,
            "log_loss": round(log_loss(y_pay_va, p_va), 4),
            "roc_auc": round(roc_auc(y_pay_va, p_va), 4),
            "pr_auc": round(average_precision(y_pay_va, p_va), 4),
            "brier": round(brier(y_pay_va, p_va), 4),
        })
    write_rows(OUT_DIR / "4b_payer_lambda_selection.csv",
               list(pay_selection[0].keys()), [list(s.values()) for s in pay_selection])
    lam_pay = min(pay_selection, key=lambda r: (r["log_loss"], -r["roc_auc"]))["lambda"]

    # ---- stage 2: E[revenue | payer], ridge on log1p, lambda by val RMSE ----
    fit_rows = train + valid
    X_fit, cols, categories, scaler = build_design(fit_rows)
    y_pay_fit, y_rev_fit = arrays(fit_rows)[1], arrays(fit_rows)[0]
    payer_mask = y_pay_fit == 1
    X_pay = X_fit[payer_mask]
    z_pay = np.log1p(y_rev_fit[payer_mask])

    va_payer = y_pay_va == 1
    X_va_pay = X_va[va_payer]
    z_va_pay = np.log1p(y_rev_va[va_payer])

    amt_selection = []
    for lam in LAMBDAS:
        beta = fit_ridge(X_pay, z_pay, lam)
        pred = X_va_pay @ beta
        amt_selection.append({
            "lambda": lam,
            "val_rmse_log1p": round(float(np.sqrt(np.mean((pred - z_va_pay) ** 2))), 4),
            "val_spearman_payers": round(spearman(pred, y_rev_va[va_payer]), 4),
        })
    write_rows(OUT_DIR / "4b_amount_lambda_selection.csv",
               list(amt_selection[0].keys()), [list(s.values()) for s in amt_selection])
    lam_amt = min(amt_selection, key=lambda r: r["val_rmse_log1p"])["lambda"]

    # ---- final fits on train + validation -----------------------------------
    beta_pay = fit_logistic(X_fit, y_pay_fit, lam_pay)
    beta_amt = fit_ridge(X_pay, z_pay, lam_amt)
    # Duan smearing: E[exp(log1p(rev))] = exp(mu) * mean(exp(residual)).
    resid = z_pay - X_pay @ beta_amt
    smear = float(np.mean(np.exp(resid)))
    print(f"selected lambda payer={lam_pay}, amount={lam_amt} (smearing {smear:.4f})")

    def score_rows(X):
        p = sigmoid(X @ beta_pay)
        expected = np.clip(np.exp(X @ beta_amt) * smear - 1.0, 0.0, None)
        return p, expected, p * expected

    p_tr, e_tr, s_tr = score_rows(X_fit)
    p_va, e_va, s_va = score_rows(X_va)
    p_te, e_te, s_te = score_rows(X_te)

    # ---- headline metrics ---------------------------------------------------
    metric_rows = []
    for name, yv, yp, pp, ss in [
        ("train (in-sample)", y_rev_fit, y_pay_fit, p_tr, s_tr),
        ("validation (out-of-time)", y_rev_va, y_pay_va, p_va, s_va),
        ("test (out-of-time, untouched)", y_rev_te, y_pay_te, p_te, s_te),
    ]:
        tm = top_revenue_metrics(yv, ss)
        row = {
            "sample": name,
            "n": int(len(yv)),
            "payers": int(yp.sum()),
            "payer_rate_pct": round(100.0 * float(yp.mean()), 2),
            "payer_roc_auc": round(roc_auc(yp, pp), 4),
            "payer_pr_auc": round(average_precision(yp, pp), 4),
            "payer_brier": round(brier(yp, pp), 4),
            "payer_log_loss": round(log_loss(yp, pp), 4),
            "spearman": round(tm["spearman"], 4),
            "mean_rev_90": round(tm["mean_rev_90"], 2),
            "top10_mean_rev": round(tm["top10_mean_rev"], 2),
            "top10_lift": round(tm["top10_lift"], 2),
            "top10_capture_pct": round(tm["top10_capture_pct"], 2),
        }
        if name.startswith(("validation", "test")):
            row.update(bootstrap_ci(yv, ss, yp))
        metric_rows.append(row)
    for row in metric_rows:
        for k in ("auc_ci_low", "auc_ci_high", "pr_auc_ci_low", "pr_auc_ci_high",
                  "spearman_ci_low", "spearman_ci_high",
                  "top10_lift_ci_low", "top10_lift_ci_high", "bootstrap_iters"):
            row.setdefault(k, "")
    write_rows(OUT_DIR / "4b_metrics.csv", list(metric_rows[0].keys()),
               [list(m.values()) for m in metric_rows])
    print("\nmetrics:")
    for m in metric_rows:
        print(f"  {m['sample']:34s} payer AUC {m['payer_roc_auc']:.4f}  "
              f"Spearman {m['spearman']:.4f}  top10 lift {m['top10_lift']:.2f}×  "
              f"n={m['n']:,}")

    # ---- baselines: does the model beat what UA can already see? -----------
    spend7 = np.array([r["revenue_7"] for r in test], dtype=float)
    flag7 = np.array([r["first_week_payer"] for r in test], dtype=float)
    baseline_specs = [
        ("no skill (train mean revenue)", np.full(len(test), float(y_rev_fit.mean()))),
        ("first-week spend only", spend7),
        ("first-week payer flag only", flag7),
        ("90-day payer probability only", p_te),
        ("two-part expected value (full)", s_te),
    ]
    baseline_rows = []
    for name, score in baseline_specs:
        tm = top_revenue_metrics(y_rev_te, score)
        baseline_rows.append({
            "model": name,
            "spearman": round(tm["spearman"], 4) if np.isfinite(tm["spearman"]) else "",
            "mean_rev_90": round(tm["mean_rev_90"], 2),
            "top10_mean_rev": round(tm["top10_mean_rev"], 2),
            "top10_lift": round(tm["top10_lift"], 2),
            "top10_capture_pct": round(tm["top10_capture_pct"], 2),
            "top20_capture_pct": round(tm["top20_capture_pct"], 2),
        })
    write_rows(OUT_DIR / "4b_baselines.csv", list(baseline_rows[0].keys()),
               [list(b.values()) for b in baseline_rows])

    # ---- amount model quality on payers ------------------------------------
    def amount_metrics(name, X, y_rev, mask, beta):
        pred_log = X[mask] @ beta
        pred = np.clip(np.exp(pred_log) * smear - 1.0, 0.0, None)
        actual = y_rev[mask]
        return {
            "sample": name,
            "n_payers": int(mask.sum()),
            "mae_usd": round(float(np.mean(np.abs(pred - actual))), 2),
            "rmse_usd": round(float(np.sqrt(np.mean((pred - actual) ** 2))), 2),
            "median_ae_usd": round(float(np.median(np.abs(pred - actual))), 2),
            "rmse_log1p": round(float(np.sqrt(np.mean((pred_log - np.log1p(actual)) ** 2))), 4),
            "spearman_within_payers": round(spearman(pred_log, actual), 4),
        }

    amount_rows = [
        amount_metrics("train (in-sample)", X_fit, y_rev_fit, payer_mask, beta_amt),
        amount_metrics("validation (out-of-time)", X_va, y_rev_va, va_payer, beta_amt),
        amount_metrics("test (out-of-time, untouched)", X_te, y_rev_te, y_pay_te == 1, beta_amt),
    ]
    write_rows(OUT_DIR / "4b_amount_metrics.csv", list(amount_rows[0].keys()),
               [list(a.values()) for a in amount_rows])

    # ---- calibration --------------------------------------------------------
    cal = (decile_table("payer_probability", y_pay_te, p_te)
           + decile_table("expected_revenue", y_rev_te, s_te))
    write_rows(OUT_DIR / "4b_calibration.csv", list(cal[0].keys()),
               [list(c.values()) for c in cal])
    payer_cal = [c for c in cal if c["kind"] == "payer_probability"]
    ece = sum(c["n"] / len(y_pay_te) * abs(c["predicted_mean"] - c["observed_mean"])
              for c in payer_cal)
    print(f"payer-probability ECE: {100 * ece:.2f} pp")

    # ---- expected-value lift table -----------------------------------------
    lift_rows = []
    order = np.argsort(-s_te, kind="mergesort")
    total_rev = float(y_rev_te.sum())
    for frac in TOP_FRACS:
        k = max(1, int(round(len(test) * frac)))
        idx = order[:k]
        mean_top = float(y_rev_te[idx].mean())
        lift_rows.append({
            "top_pct": int(frac * 100),
            "targeted": k,
            "score_cutoff_usd": round(float(s_te[idx].min()), 4),
            "mean_rev_90_usd": round(mean_top, 2),
            "revenue_lift_vs_random": round(mean_top / float(y_rev_te.mean()), 2),
            "share_of_total_revenue_pct": round(100.0 * float(y_rev_te[idx].sum()) / total_rev, 2),
            "payer_precision_pct": round(100.0 * float(y_pay_te[idx].mean()), 2),
        })
    write_rows(OUT_DIR / "4b_lift.csv", list(lift_rows[0].keys()),
               [list(r.values()) for r in lift_rows])

    # ---- segments -----------------------------------------------------------
    seg = segment_table(test, p_te, s_te, y_rev_te, y_pay_te)
    write_rows(OUT_DIR / "4b_segment_metrics.csv", list(seg[0].keys()),
               [list(s.values()) for s in seg])

    # ---- revenue distribution ----------------------------------------------
    dist = revenue_distribution(y_rev_te)
    write_rows(OUT_DIR / "4b_revenue_distribution.csv", list(dist[0].keys()),
               [list(d.values()) for d in dist])

    # ---- split summary ------------------------------------------------------
    split_rows = []
    for name, rs in (("train", train), ("validation", valid), ("test", test)):
        yv = np.array([r["revenue_90"] for r in rs], dtype=float)
        r7 = np.array([r["revenue_7"] for r in rs], dtype=float)
        split_rows.append({
            "split": name,
            "install_from": min(r["install_date"] for r in rs),
            "install_to": max(r["install_date"] for r in rs),
            "n": len(rs),
            "payers": int((yv > 0).sum()),
            "payer_rate_pct": round(100.0 * float((yv > 0).mean()), 2),
            "mean_rev_90": round(float(yv.mean()), 2),
            "median_rev_90": round(float(np.median(yv)), 2),
            "p90_rev_90": round(percentile(yv, 90), 2),
            "mean_rev_7": round(float(r7.mean()), 2),
            "share_90d_rev_in_week1_pct": round(100.0 * float(r7.sum()) / float(yv.sum()), 2),
        })
    write_rows(OUT_DIR / "4b_split_summary.csv", list(split_rows[0].keys()),
               [list(s.values()) for s in split_rows])

    # ---- lift curve for the chart ------------------------------------------
    curve = []
    sorted_idx = np.argsort(-s_te, kind="mergesort")
    sorted_spend = np.argsort(-spend7, kind="mergesort")
    cum_rev = np.cumsum(y_rev_te[sorted_idx]) / total_rev
    cum_spend = np.cumsum(y_rev_te[sorted_spend]) / total_rev
    for pct in range(0, 101):
        k = int(round(len(test) * pct / 100.0)) - 1
        curve.append({
            "pct_targeted": pct,
            "model_capture_pct": round(100.0 * float(cum_rev[k]), 2) if k >= 0 else 0.0,
            "week1_spend_capture_pct": round(100.0 * float(cum_spend[k]), 2) if k >= 0 else 0.0,
            "random_capture_pct": pct,
        })
    write_rows(OUT_DIR / "4b_lift_curve.csv", list(curve[0].keys()),
               [list(c.values()) for c in curve])

    # ---- test predictions ---------------------------------------------------
    with (OUT_DIR / "4b_test_predictions.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["device_id", "install_date", "acquisition_channel", "country_tier",
                    "first_week_payer", "revenue_7", "revenue_90", "payer_90",
                    "p_payer_90", "expected_rev_90", "score"])
        for r, p, e, s in zip(test, p_te, e_te, s_te):
            w.writerow([r["device_id"], r["install_date"], r["acquisition_channel"],
                        r["country_tier"], r["first_week_payer"], r["revenue_7"],
                        r["revenue_90"], r["payer_90"], round(float(p), 6),
                        round(float(e), 4), round(float(s), 4)])

    # ---- coefficients -------------------------------------------------------
    coef = []
    for stage, beta in (("payer_probability", beta_pay), ("revenue_if_payer", beta_amt)):
        for name, b in zip(cols, beta):
            coef.append({
                "stage": stage,
                "feature": name,
                "coef_standardised": round(float(b), 4),
                "exp_coef": round(float(math.exp(min(b, 30))), 3),
                "direction": ("higher" if b > 0 else "lower"),
            })
    write_rows(OUT_DIR / "4b_coefficients.csv", list(coef[0].keys()),
               [list(c.values()) for c in coef])

    # ---- summary markdown ---------------------------------------------------
    def table(rows_, cols_):
        out = ["| " + " | ".join(cols_) + " |", "|" + "---|" * len(cols_)]
        for r in rows_:
            out.append("| " + " | ".join(str(r[c]) for c in cols_) + " |")
        return "\n".join(out)

    lines = [
        "# Deliverable 4b — 90-day value of a new install",
        "",
        "Generated by `scripts/run_deliverable4b.py` from `sql/deliverable4b.sql`.",
        "",
        "## Labelable cohort",
        f"- Labelable installs (2026-01-01..2026-01-30): **{len(rows):,}**",
        f"- Train {len(train):,} / validation {len(valid):,} / test {len(test):,}",
        f"- Selected lambda: payer {lam_pay}, amount {lam_amt}",
        "",
        "## Split and 90-day outcome",
        table(split_rows, ["split", "install_from", "install_to", "n", "payers",
                           "payer_rate_pct", "mean_rev_90", "median_rev_90",
                           "p90_rev_90", "share_90d_rev_in_week1_pct"]),
        "",
        "## Metrics",
        table(metric_rows, ["sample", "n", "payers", "payer_rate_pct",
                            "payer_roc_auc", "payer_pr_auc", "spearman",
                            "top10_lift", "top10_capture_pct"]),
        "",
        f"Test payer-probability ECE: **{100 * ece:.2f} pp**.",
        "",
        "## Baselines (test)",
        table(baseline_rows, ["model", "spearman", "mean_rev_90", "top10_mean_rev",
                              "top10_lift", "top10_capture_pct", "top20_capture_pct"]),
        "",
        "## Amount model (payers only)",
        table(amount_rows, ["sample", "n_payers", "mae_usd", "rmse_usd",
                            "median_ae_usd", "rmse_log1p", "spearman_within_payers"]),
        "",
        "## Expected-value lift (test)",
        table(lift_rows, ["top_pct", "targeted", "score_cutoff_usd",
                          "mean_rev_90_usd", "revenue_lift_vs_random",
                          "share_of_total_revenue_pct", "payer_precision_pct"]),
        "",
        "## Segments (test)",
        table(seg, ["segment", "value", "n", "payers", "payer_rate_pct",
                    "revenue_auc", "spearman", "top10_lift", "reliable"]),
        "",
        "## Revenue distribution (test)",
        table(dist, ["bucket", "installs", "share_installs_pct",
                     "revenue_usd", "share_revenue_pct"]),
    ]
    (OUT_DIR / "4b_summary.md").write_text("\n".join(lines) + "\n")
    print(f"\nsummary -> outputs/deliverable4/4b_summary.md")


if __name__ == "__main__":
    main()
