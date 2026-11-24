#!/usr/bin/env python3
"""Run every Deliverable-2 SQL query and save the results as CSV + a summary
markdown.  Run from the repo root:

    python3 scripts/load_data.py          # if telemetry.db is missing
    python3 scripts/run_deliverable2.py
"""
import csv
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "telemetry.db"
SQL_FILE = ROOT / "sql" / "deliverable2.sql"
OUT_DIR = ROOT / "outputs" / "deliverable2"

# headline sections copied into summary.md
SUMMARY_SECTIONS = {
    "2a_headline",
    "2a_by_tier",
    "2a_decomposition",
    "2a_counterfactual",
    "2a_installs_by_tier",
    "2a_installs_month_tier",
    "2a_dd_age",
    "2a_channel",
    "2a_ltv30_proxy",
    "2a_window_sensitivity",
    "2a_tier_platform",
    "2a_channel_tier_arpdau",
    "2a_sale_density",
    "2a_ad_engagement",
    "checks_d2",
}


def split_sections(sql_text: str) -> dict[str, str]:
    """Split the .sql file on '-- @name' markers."""
    parts = re.split(r"^-- @(\S+)$", sql_text, flags=re.M)
    sections: dict[str, str] = {}
    for i in range(1, len(parts), 2):
        sections[parts[i]] = parts[i + 1].strip()
    return sections


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

    (OUT_DIR / "summary.md").write_text("\n".join(summary_rows) + "\n")
    print(f"\nsummary -> {(OUT_DIR / 'summary.md').relative_to(ROOT)}")
    conn.close()


if __name__ == "__main__":
    main()
