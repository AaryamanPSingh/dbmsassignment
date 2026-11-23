#!/usr/bin/env python3
"""Quick data-quality profiling pass over telemetry.db (run from repo root)."""

import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "telemetry.db"

QUERIES = [
    ("player_day date range",
     "SELECT MIN(activity_date) mn, MAX(activity_date) mx, COUNT(*) n FROM player_day"),
    ("duplicate player_day keys",
     """SELECT COUNT(*) dup_keys FROM (SELECT device_id, activity_date, COUNT(*) c
        FROM player_day GROUP BY 1,2 HAVING c>1)"""),
    ("player_day rows that are exact dupes",
     """SELECT COUNT(*)-COUNT(DISTINCT device_id||activity_date||player_level||
        session_count||playtime_minutes||app_version) exact_dupes FROM player_day"""),
    ("player_day devices missing from profile",
     """SELECT COUNT(DISTINCT p.device_id) orphan_devices, COUNT(*) orphan_rows
        FROM player_day p LEFT JOIN player_profile r USING(device_id) WHERE r.device_id IS NULL"""),
    ("profile devices with zero activity",
     "SELECT COUNT(*) FROM player_profile r WHERE NOT EXISTS (SELECT 1 FROM player_day p WHERE p.device_id=r.device_id)"),
    ("purchase ts range / bad amounts",
     """SELECT MIN(event_ts) mn_ts, MAX(event_ts) mx_ts, COUNT(*) n,
        SUM(usd_amount<0) neg, SUM(usd_amount=0) zero,
        COUNT(*)-COUNT(DISTINCT purchase_id) dup_pid FROM purchase"""),
    ("purchases before install_date",
     "SELECT COUNT(*) FROM purchase p JOIN player_profile r USING(device_id) WHERE DATE(p.event_ts) < r.install_date"),
    ("purchases with unknown device",
     "SELECT COUNT(*) FROM purchase p LEFT JOIN player_profile r USING(device_id) WHERE r.device_id IS NULL"),
    ("first_purchase_date consistency",
     """SELECT SUM(r.first_purchase_date IS NOT NULL AND f.fp IS NULL) fp_set_no_tx,
               SUM(r.first_purchase_date IS NULL AND f.fp IS NOT NULL) tx_no_fp,
               SUM(r.first_purchase_date IS NOT NULL AND f.fp IS NOT NULL AND r.first_purchase_date <> f.fp) fp_differs
        FROM player_profile r LEFT JOIN (SELECT device_id, MIN(DATE(event_ts)) fp FROM purchase GROUP BY device_id) f USING(device_id)"""),
    ("purchase dates outside 2026 window",
     """SELECT SUM(DATE(event_ts) < '2026-01-01') before, SUM(DATE(event_ts) > '2026-04-30') after FROM purchase"""),
    ("player_day dates outside window",
     "SELECT SUM(activity_date < 20260101) before, SUM(activity_date > 20260430) after FROM player_day"),
    ("install dates outside window",
     "SELECT SUM(install_date < '2026-01-01') before, SUM(install_date > '2026-04-30') after, MIN(install_date), MAX(install_date) FROM player_profile"),
    ("install volume by month",
     "SELECT substr(install_date,1,7) m, COUNT(*) installs FROM player_profile GROUP BY m ORDER BY m"),
    ("platform values",
     "SELECT platform, COUNT(*) FROM player_profile GROUP BY platform"),
    ("country_tier values",
     "SELECT country_tier, COUNT(*) FROM player_profile GROUP BY country_tier ORDER BY country_tier"),
    ("acquisition_channel values",
     "SELECT acquisition_channel, COUNT(*) FROM player_profile GROUP BY acquisition_channel"),
    ("ad_view status counts",
     "SELECT status, COUNT(*) FROM ad_view GROUP BY status"),
    ("ad cap anomalies",
     "SELECT SUM(ad_daily_count > ad_daily_cap) over_cap, SUM(ad_daily_cap<=0) bad_cap, SUM(ad_daily_count<=0) bad_count FROM ad_view"),
    ("ad_view unknown device",
     "SELECT COUNT(*) FROM ad_view a LEFT JOIN player_profile r USING(device_id) WHERE r.device_id IS NULL"),
    ("currency_spend unknown device",
     "SELECT COUNT(*) FROM currency_spend c LEFT JOIN player_profile r USING(device_id) WHERE r.device_id IS NULL"),
    ("spend_type / currency_type values",
     "SELECT spend_type, currency_type, COUNT(*) FROM currency_spend GROUP BY 1,2"),
    ("daily install volume (first 10 + shape check)",
     "SELECT substr(install_date,1,7) m, COUNT(*) n, MIN(d) first_day, MAX(d) last_day FROM (SELECT install_date, install_date d FROM player_profile) GROUP BY m"),
]


def main() -> None:
    conn = sqlite3.connect(DB)
    for title, sql in QUERIES:
        print(f"\n=== {title} ===")
        try:
            cur = conn.execute(sql)
            cols = [d[0] for d in cur.description]
            print(" | ".join(cols))
            for row in cur:
                print(" | ".join("NULL" if v is None else str(v) for v in row))
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR: {exc}")
    conn.close()


if __name__ == "__main__":
    main()
