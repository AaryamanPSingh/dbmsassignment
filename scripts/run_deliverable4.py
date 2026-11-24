#!/usr/bin/env python3
"""Deliverable 4a — 14-day churn model.

Runs the SQL in sql/deliverable4.sql, then fits an L2-regularised logistic
regression with NumPy/SciPy only (the project already depends on numpy/scipy;
no scikit-learn). Writes the dataset, metrics, calibration, lift/threshold
tables, segment diagnostics and coefficients to outputs/deliverable4/.

    python3 scripts/load_data.py
    python3 scripts/run_deliverable4.py
"""

import csv
import math
import re
import sqlite3
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "telemetry.db"
SQL_FILE = ROOT / "sql" / "deliverable4.sql"
OUT_DIR = ROOT / "outputs" / "deliverable4"

# Parsimonious feature set: no derived deltas (they are exact linear
# combinations of the level features), no has_level/ever-payer/purchases_14
# duplicates that flipped signs under collinearity. The 7-day and prior-7-day
# levels stay because the trend is the point; their coefficients are
# conditional associations, not causal effects.
NUMERIC = [
    "tenure_days", "level_last",
    "active_days_7", "active_days_prev7",
    "sessions_7", "sessions_prev7",
    "playtime_7", "playtime_prev7",
    "playtime_per_active_day", "sessions_per_active_day",
    "ads_per_active_day",
    "spend_lifetime", "spend_14", "days_since_purchase",
    "ads_completed_14", "ad_days_14",
]
LOG1P = {"spend_lifetime", "spend_14", "ads_completed_14"}
CATEGORICAL = ["platform", "country_tier", "acquisition_channel"]

LAMBDAS = [0.1, 1.0, 10.0, 100.0]
EPS = 1e-12


# --------------------------------------------------------------------------- #
# SQL execution
# --------------------------------------------------------------------------- #
def split_sections(sql_text: str) -> dict[str, str]:
    parts = re.split(r"^-- @(\S+)$", sql_text, flags=re.M)
    return {parts[i]: parts[i + 1].strip() for i in range(1, len(parts), 2)}


def write_rows(path: Path, cols: list[str], rows: list[sqlite3.Row]) -> None:
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        w.writerows(rows)


def run_sql() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sections = split_sections(SQL_FILE.read_text())
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    for name, sql in sections.items():
        if name == "setup":
            conn.executescript(sql)
            continue
        if name.endswith("_build"):
            conn.executescript(sql)
            continue
        cur = conn.execute(sql)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        write_rows(OUT_DIR / f"{name}.csv", cols, rows)
        print(f"{name:32s} {len(rows):7d} rows -> {(OUT_DIR / (name + '.csv')).relative_to(ROOT)}")
    conn.close()


# --------------------------------------------------------------------------- #
# Data preparation
# --------------------------------------------------------------------------- #
def read_dataset() -> list[dict]:
    with (OUT_DIR / "4a_model_dataset.csv").open() as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        for k in NUMERIC:
            r[k] = float(r[k])
        r["churn14"] = int(r["churn14"])
        r["tenure_bucket"] = (
            "0-6" if r["tenure_days"] < 7 else
            "7-13" if r["tenure_days"] < 14 else
            "14-29" if r["tenure_days"] < 30 else
            "30-59" if r["tenure_days"] < 60 else "60+"
        )
    return rows


def transform_numeric(rows: list[dict], key: str) -> np.ndarray:
    if key in LOG1P:
        return np.array([math.log1p(r[key]) for r in rows])
    return np.array([r[key] for r in rows])


def build_design(rows: list[dict], categories=None, scaler=None):
    """Return (X, columns, categories, scaler). Fit on `rows` when scaler None."""
    raw = {k: transform_numeric(rows, k) for k in NUMERIC}
    if scaler is None:
        mean = {k: float(v.mean()) for k, v in raw.items()}
        std = {k: float(v.std()) or 1.0 for k, v in raw.items()}
        scaler = (mean, std)
    mean, std = scaler

    if categories is None:
        categories = {}
        for c in CATEGORICAL:
            vals = sorted({str(r[c]) for r in rows})
            categories[c] = vals

    cols: list[str] = []
    blocks: list[np.ndarray] = []
    for k in NUMERIC:
        cols.append(f"log1p({k})" if k in LOG1P else k)
        z = (raw[k] - mean[k]) / std[k]
        blocks.append(z[:, None])

    for c in CATEGORICAL:
        ref = categories[c][0]
        for level in categories[c][1:]:
            cols.append(f"{c}={level} (ref {ref})")
            blocks.append(np.array([1.0 if str(r[c]) == level else 0.0 for r in rows])[:, None])

    X = np.hstack(blocks)
    cols.append("intercept")
    X = np.hstack([X, np.ones((len(rows), 1))])  # intercept last
    return X, cols, categories, scaler


# --------------------------------------------------------------------------- #
# Logistic regression (Newton / IRLS with L2 on non-intercept coefficients)
# --------------------------------------------------------------------------- #
def sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(z, -35, 35)))


def fit_logistic(X: np.ndarray, y: np.ndarray, lam: float, max_iter: int = 100) -> np.ndarray:
    n, p = X.shape
    beta = np.zeros(p)
    penalty = np.ones(p)
    penalty[-1] = 0.0  # intercept at the last position
    for _ in range(max_iter):
        mu = sigmoid(X @ beta)
        w = np.clip(mu * (1.0 - mu), 1e-9, None)
        grad = X.T @ (mu - y) + lam * penalty * beta
        H = X.T @ (X * w[:, None])
        H[np.diag_indices(p)] += lam * penalty + 1e-8
        step = np.linalg.solve(H, grad)
        # Damped Newton keeps the first iterations from overshooting.
        beta_new = beta - step
        if not np.all(np.isfinite(beta_new)):
            beta_new = beta - 0.1 * step
        beta = beta_new
        if np.max(np.abs(step)) < 1e-9:
            break
    return beta


def predict(X: np.ndarray, beta: np.ndarray) -> np.ndarray:
    return sigmoid(X @ beta)


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #
def roc_auc(y: np.ndarray, score: np.ndarray) -> float:
    order = np.argsort(score, kind="mergesort")
    ranks = np.empty(len(score), dtype=float)
    ranks[order] = np.arange(1, len(score) + 1)
    # average ranks for ties
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


def metrics(y: np.ndarray, p: np.ndarray) -> dict:
    base = float(y.mean())
    return {
        "n": int(len(y)),
        "churners": int(y.sum()),
        "churn_rate_pct": round(100 * base, 2),
        "roc_auc": round(roc_auc(y, p), 4),
        "pr_auc": round(average_precision(y, p), 4),
        "brier": round(brier(y, p), 4),
        "log_loss": round(log_loss(y, p), 4),
        "no_skill_brier": round(base * (1 - base), 4),
        "no_skill_log_loss": round(log_loss(y, np.full(len(y), base)), 4),
        "no_skill_pr_auc": round(base, 4),
    }


def bootstrap_ci(y: np.ndarray, p: np.ndarray, n_boot: int = 1000,
                 seed: int = 20261124) -> dict:
    rng = np.random.default_rng(seed)
    aucs, aps = [], []
    n = len(y)
    for _ in range(n_boot):
        idx = rng.integers(0, n, n)
        yy = y[idx]
        if yy.sum() == 0 or yy.sum() == n:
            continue
        aucs.append(roc_auc(yy, p[idx]))
        aps.append(average_precision(yy, p[idx]))
    return {
        "auc_ci_low": round(float(np.percentile(aucs, 2.5)), 4),
        "auc_ci_high": round(float(np.percentile(aucs, 97.5)), 4),
        "pr_auc_ci_low": round(float(np.percentile(aps, 2.5)), 4),
        "pr_auc_ci_high": round(float(np.percentile(aps, 97.5)), 4),
        "bootstrap_iters": len(aucs),
    }


def calibration_table(y: np.ndarray, p: np.ndarray, bins: int = 10) -> list[dict]:
    order = np.argsort(p, kind="mergesort")
    splits = np.array_split(order, bins)
    out = []
    for i, idx in enumerate(splits, 1):
        if len(idx) == 0:
            continue
        out.append({
            "decile": i,
            "n": int(len(idx)),
            "predicted_pct": round(100 * float(p[idx].mean()), 2),
            "observed_pct": round(100 * float(y[idx].mean()), 2),
            "gap_pp": round(100 * (float(p[idx].mean()) - float(y[idx].mean())), 2),
            "score_min": round(float(p[idx].min()), 4),
            "score_max": round(float(p[idx].max()), 4),
        })
    return out


def threshold_table(y: np.ndarray, p: np.ndarray, effect: float = 0.05,
                    offer_cost: float = 1.0) -> list[dict]:
    order = np.argsort(-p, kind="mergesort")
    out = []
    n = len(y)
    for k_pct in [5, 10, 20, 30, 50]:
        k = max(1, int(round(n * k_pct / 100)))
        idx = order[:k]
        tp = int(y[idx].sum())
        precision = tp / k
        recall = tp / int(y.sum())
        base = float(y.mean())
        out.append({
            "top_pct": k_pct,
            "targeted": k,
            "score_cutoff": round(float(p[idx].min()), 4),
            "churners_flagged": tp,
            "precision_pct": round(100 * precision, 2),
            "recall_pct": round(100 * recall, 2),
            "lift_vs_random": round(precision / base, 2),
            "wasted_no_churn_pct": round(100 * (1 - precision), 2),
            "expected_saves_per_100": round(100 * precision * effect, 2),
            "offers_per_expected_save": round(1 / (precision * effect), 1),
            "cost_per_save_usd": round(offer_cost / (precision * effect), 2),
        })
    return out


def break_even_grid() -> list[dict]:
    """p* = offer_cost / (effect * retained_player_value)."""
    out = []
    for cost in [0.25, 0.5, 1.0, 2.0, 5.0]:
        for effect in [0.02, 0.05, 0.10]:
            for value in [10, 25, 50, 100]:
                p_star = cost / (effect * value)
                out.append({
                    "offer_cost_usd": cost,
                    "offer_effect_pct": round(100 * effect, 1),
                    "retained_player_value_usd": value,
                    "break_even_churn_prob_pct": round(100 * p_star, 2),
                    "operable_at_15pct_base": "yes" if p_star <= 0.15 else "no",
                })
    return out


def segment_table(rows: list[dict], score: np.ndarray, split: str) -> list[dict]:
    out = []
    for key in ["tenure_bucket", "country_tier", "platform", "acquisition_channel"]:
        values = sorted({str(r[key]) for r in rows})
        for v in values:
            idx = np.array([i for i, r in enumerate(rows) if str(r[key]) == v])
            y = np.array([rows[i]["churn14"] for i in idx])
            out.append({
                "split": split,
                "segment": key,
                "value": v,
                "n": int(len(idx)),
                "churners": int(y.sum()),
                "churn_rate_pct": round(100 * float(y.mean()), 2),
                "roc_auc": round(roc_auc(y, score[idx]), 4),
                "pr_auc": round(average_precision(y, score[idx]), 4),
                "reliable": "yes" if y.sum() >= 30 else "no (<30 churners)",
            })
    return out


def curve_points(y: np.ndarray, p: np.ndarray, max_points: int = 200) -> tuple[list[dict], list[dict]]:
    order = np.argsort(-p, kind="mergesort")
    y_sorted = y[order]
    p_sorted = p[order]
    tps = np.cumsum(y_sorted)
    fps = np.cumsum(1 - y_sorted)
    P, N = int(y.sum()), int((1 - y).sum())
    roc = [{"fpr": 0.0, "tpr": 0.0}]
    pr = [{"recall": 0.0, "precision": 1.0}]
    step = max(1, len(y) // max_points)
    for i in range(0, len(y), step):
        roc.append({"fpr": fps[i] / N, "tpr": tps[i] / P})
        pr.append({"recall": tps[i] / P, "precision": tps[i] / (i + 1)})
    roc.append({"fpr": 1.0, "tpr": 1.0})
    pr.append({"recall": 1.0, "precision": float(y.mean())})
    return roc, pr


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> None:
    run_sql()
    rows = read_dataset()
    train = [r for r in rows if r["split"] == "train"]
    valid = [r for r in rows if r["split"] == "validation"]
    test = [r for r in rows if r["split"] == "test"]
    print(f"\ndataset: {len(rows):,} rows | train {len(train):,} | "
          f"validation {len(valid):,} | test {len(test):,}")

    # ---- hyperparameter selection on the validation snapshot -----------------
    X_tr, cols, categories, scaler_tr = build_design(train)
    y_tr = np.array([r["churn14"] for r in train], dtype=float)
    X_va, _, _, _ = build_design(valid, categories, scaler_tr)
    y_va = np.array([r["churn14"] for r in valid], dtype=float)

    selection = []
    for lam in LAMBDAS:
        beta = fit_logistic(X_tr, y_tr, lam)
        p_va = predict(X_va, beta)
        m = metrics(y_va, p_va)
        selection.append({"lambda": lam, **m})
    write_rows(OUT_DIR / "4a_lambda_selection.csv",
               list(selection[0].keys()), [list(s.values()) for s in selection])
    best = min(selection, key=lambda r: (r["log_loss"], -r["roc_auc"]))
    lam = best["lambda"]
    print(f"selected lambda={lam} (validation log loss {best['log_loss']:.4f})")

    # ---- final model: refit on train + validation, evaluate on untouched test -
    fit_rows = train + valid
    X_fit, cols, categories, scaler = build_design(fit_rows)
    y_fit = np.array([r["churn14"] for r in fit_rows], dtype=float)
    beta = fit_logistic(X_fit, y_fit, lam)

    X_test, _, _, _ = build_design(test, categories, scaler)
    y_test = np.array([r["churn14"] for r in test], dtype=float)
    p_test = predict(X_test, beta)

    X_va2, _, _, _ = build_design(valid, categories, scaler)
    p_valid = predict(X_va2, beta)
    y_valid = np.array([r["churn14"] for r in valid], dtype=float)

    metric_rows = []
    for name, y, p in [("train (in-sample)", y_fit, predict(X_fit, beta)),
                       ("validation (out-of-time)", y_valid, p_valid),
                       ("test (out-of-time, untouched)", y_test, p_test)]:
        row = {"sample": name, **metrics(y, p)}
        if name.startswith(("validation", "test")):
            row.update(bootstrap_ci(y, p))
        metric_rows.append(row)
    for row in metric_rows:
        for k in ["auc_ci_low", "auc_ci_high", "pr_auc_ci_low",
                  "pr_auc_ci_high", "bootstrap_iters"]:
            row.setdefault(k, "")
    write_rows(OUT_DIR / "4a_metrics.csv",
               list(metric_rows[0].keys()), [list(m.values()) for m in metric_rows])
    print("\nmetrics:")
    for m in metric_rows:
        print(f"  {m['sample']:34s} AUC {m['roc_auc']:.4f}  PR-AUC {m['pr_auc']:.4f}  "
              f"Brier {m['brier']:.4f}  logloss {m['log_loss']:.4f}  n={m['n']:,}")

    # ---- baseline comparison: does the rest of the feature set add ranking? --
    ten_fit = np.array([r["tenure_days"] for r in fit_rows], dtype=float)
    ten_mu, ten_sd = float(ten_fit.mean()), float(ten_fit.std()) or 1.0
    X_ten = np.column_stack([(ten_fit - ten_mu) / ten_sd, np.ones(len(ten_fit))])
    beta_ten = fit_logistic(X_ten, y_fit, lam)
    ten_test = np.array([r["tenure_days"] for r in test], dtype=float)
    X_ten_test = np.column_stack([(ten_test - ten_mu) / ten_sd,
                                  np.ones(len(ten_test))])
    p_ten = predict(X_ten_test, beta_ten)
    baseline_rows = [
        {"model": "no skill (train prevalence)",
         **metrics(y_test, np.full(len(y_test), float(y_fit.mean())))},
        {"model": "tenure only (1 feature)", **metrics(y_test, p_ten)},
        {"model": "full model (22 predictors)", **metrics(y_test, p_test)},
    ]
    write_rows(OUT_DIR / "4a_baseline.csv", list(baseline_rows[0].keys()),
               [list(b.values()) for b in baseline_rows])

    # ---- score export (test set) --------------------------------------------
    with (OUT_DIR / "4a_test_predictions.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["snapshot_date", "device_id", "churn14", "predicted_churn"])
        for r, score in zip(test, p_test):
            w.writerow([r["snapshot_date"], r["device_id"], r["churn14"], round(float(score), 6)])

    # ---- calibration ---------------------------------------------------------
    cal = calibration_table(y_test, p_test)
    write_rows(OUT_DIR / "4a_calibration.csv", list(cal[0].keys()), [list(c.values()) for c in cal])
    ece = sum(c["n"] / len(y_test) * abs(c["predicted_pct"] - c["observed_pct"]) for c in cal)
    print(f"test ECE: {ece:.2f} pp")

    # ---- lift / threshold cost analysis -------------------------------------
    thresh = threshold_table(y_test, p_test)
    write_rows(OUT_DIR / "4a_thresholds.csv",
               list(thresh[0].keys()), [list(t.values()) for t in thresh])
    be = break_even_grid()
    write_rows(OUT_DIR / "4a_break_even.csv", list(be[0].keys()), [list(b.values()) for b in be])

    # ---- curves --------------------------------------------------------------
    roc, pr = curve_points(y_test, p_test)
    write_rows(OUT_DIR / "4a_roc_curve.csv", ["fpr", "tpr"], [[r["fpr"], r["tpr"]] for r in roc])
    write_rows(OUT_DIR / "4a_pr_curve.csv", ["recall", "precision"],
               [[r["recall"], r["precision"]] for r in pr])

    # ---- segment diagnostics -------------------------------------------------
    seg = segment_table(test, p_test, "test")
    write_rows(OUT_DIR / "4a_segment_metrics.csv",
               list(seg[0].keys()), [list(s.values()) for s in seg])

    # ---- coefficients --------------------------------------------------------
    coef = []
    for name, b in zip(cols, beta):
        coef.append({
            "feature": name,
            "coef_standardised": round(float(b), 4),
            "odds_ratio": round(float(math.exp(b)), 3),
            "direction": "higher churn" if b > 0 else "lower churn",
        })
    write_rows(OUT_DIR / "4a_coefficients.csv",
               list(coef[0].keys()), [list(c.values()) for c in coef])

    # ---- summary markdown ----------------------------------------------------
    def table(rows_, cols_):
        out = ["| " + " | ".join(cols_) + " |", "|" + "---|" * len(cols_)]
        for r in rows_:
            out.append("| " + " | ".join(str(r[c]) for c in cols_) + " |")
        return "\n".join(out)

    top = sorted([c for c in coef if c["feature"] != "intercept"],
                 key=lambda c: abs(c["coef_standardised"]), reverse=True)[:12]
    lines = [
        "# Deliverable 4a — churn model outputs",
        "",
        "Generated by `scripts/run_deliverable4.py` from `sql/deliverable4.sql`.",
        "",
        "## Split",
        f"- Train: {len(train):,} player-snapshots (2026-01-14, 2026-02-11)",
        f"- Validation (lambda only): {len(valid):,} (2026-03-11)",
        f"- Test (untouched, out of time): {len(test):,} (2026-04-08)",
        f"- Selected L2 lambda: {lam}",
        "",
        "## Metrics",
        table(metric_rows, ["sample", "n", "churners", "churn_rate_pct", "roc_auc",
                            "auc_ci_low", "auc_ci_high", "pr_auc", "brier", "log_loss"]),
        "",
        f"Test expected calibration error: **{ece:.2f} pp**.",
        "",
        "## Does the full feature set add ranking power?",
        table(baseline_rows, ["model", "roc_auc", "pr_auc", "brier", "log_loss"]),
        "",
        "## Test-set lift",
        table(thresh, ["top_pct", "targeted", "score_cutoff", "precision_pct",
                       "recall_pct", "lift_vs_random", "wasted_no_churn_pct",
                       "expected_saves_per_100"]),
        "",
        "## Largest standardised coefficients",
        table(top, ["feature", "coef_standardised", "odds_ratio", "direction"]),
        "",
        "## Segment diagnostics (test)",
        table([s for s in seg if s["segment"] == "tenure_bucket"],
              ["value", "n", "churners", "churn_rate_pct", "roc_auc", "pr_auc", "reliable"]),
    ]
    (OUT_DIR / "summary.md").write_text("\n".join(lines) + "\n")
    print(f"\nsummary -> {(OUT_DIR / 'summary.md').relative_to(ROOT)}")


if __name__ == "__main__":
    main()
