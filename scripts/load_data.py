#!/usr/bin/env python3
"""Load the five telemetry CSVs into a local SQLite database.

Run from the repo root:
    python3 scripts/load_data.py
"""

import csv
import re
import sqlite3
from pathlib import Path

# Some event_ts values have a single-digit hour ("2026-01-01 6:58:57"), which
# SQLite's DATE()/julianday() silently reject (return NULL). Zero-pad on load.
_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}) (\d):")


def norm_ts(value):
    if value is None or value == "":
        return None
    m = _TS_RE.match(value)
    return f"{m.group(1)} 0{m.group(2)}:{value[m.end():]}" if m else value

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "telemetry.db"

# table -> (csv filename, column list)
TABLES = {
    "player_profile": (
        "player_profile - player_profile.csv",
        ["device_id", "original_device_id", "install_date", "platform",
         "country", "country_tier", "acquisition_channel", "first_purchase_date"],
    ),
    "player_day": (
        "player_day - player_day.csv",
        ["device_id", "activity_date", "player_level", "session_count",
         "playtime_minutes", "app_version"],
    ),
    "purchase": (
        "purchase - purchase.csv",
        ["purchase_id", "device_id", "event_ts", "pack_name",
         "usd_amount", "currency_granted", "sale_flag"],
    ),
    "currency_spend": (
        "currency_spend - currency_spend.csv",
        ["device_id", "event_ts", "spend_type", "currency_type", "currency_value",
         "spend_category", "player_level", "premium_balance", "social_balance",
         "grind_balance"],
    ),
    "ad_view": (
        "ad_view - ad_view.csv",
        ["device_id", "event_ts", "status", "placement", "reward_type",
         "reward_amount", "ad_daily_count", "ad_daily_cap"],
    ),
}

DDL = {
    "player_profile": """
        CREATE TABLE player_profile (
            device_id INTEGER PRIMARY KEY,
            original_device_id INTEGER,
            install_date TEXT,
            platform TEXT,
            country TEXT,
            country_tier INTEGER,
            acquisition_channel TEXT,
            first_purchase_date TEXT
        )""",
    "player_day": """
        CREATE TABLE player_day (
            device_id INTEGER,
            activity_date INTEGER,   -- YYYYMMDD
            player_level INTEGER,
            session_count INTEGER,
            playtime_minutes REAL,
            app_version TEXT
        )""",
    "purchase": """
        CREATE TABLE purchase (
            purchase_id TEXT,
            device_id INTEGER,
            event_ts TEXT,
            pack_name TEXT,
            usd_amount REAL,
            currency_granted INTEGER,
            sale_flag INTEGER
        )""",
    "currency_spend": """
        CREATE TABLE currency_spend (
            device_id INTEGER,
            event_ts TEXT,
            spend_type TEXT,
            currency_type TEXT,
            currency_value INTEGER,
            spend_category TEXT,
            player_level INTEGER,
            premium_balance INTEGER,
            social_balance INTEGER,
            grind_balance INTEGER
        )""",
    "ad_view": """
        CREATE TABLE ad_view (
            device_id INTEGER,
            event_ts TEXT,
            status TEXT,
            placement TEXT,
            reward_type TEXT,
            reward_amount INTEGER,
            ad_daily_count INTEGER,
            ad_daily_cap INTEGER
        )""",
}

INDEXES = [
    "CREATE INDEX idx_player_day_device_date ON player_day(device_id, activity_date)",
    "CREATE INDEX idx_player_day_date ON player_day(activity_date)",
    "CREATE INDEX idx_purchase_device_ts ON purchase(device_id, event_ts)",
    "CREATE INDEX idx_purchase_ts ON purchase(event_ts)",
    "CREATE INDEX idx_spend_device_ts ON currency_spend(device_id, event_ts)",
    "CREATE INDEX idx_ad_device_ts ON ad_view(device_id, event_ts)",
    "CREATE INDEX idx_ad_ts ON ad_view(event_ts)",
    "CREATE INDEX idx_profile_tier ON player_profile(country_tier)",
    "CREATE INDEX idx_profile_channel ON player_profile(acquisition_channel)",
]


def load() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")

    for table, (filename, columns) in TABLES.items():
        path = ROOT / filename
        if not path.exists():
            raise FileNotFoundError(f"missing CSV: {path}")
        conn.execute(DDL[table])
        with path.open(newline="") as fh:
            reader = csv.DictReader(fh)
            unexpected = set(reader.fieldnames) - set(columns)
            if unexpected:
                print(f"  ! {table}: unexpected columns {sorted(unexpected)}")
            rows = []
            for row in reader:
                # empty string -> NULL for nullable fields
                rec = [None if row[c] in ("", None) else row[c] for c in columns]
                if "event_ts" in columns:
                    rec[columns.index("event_ts")] = norm_ts(rec[columns.index("event_ts")])
                rows.append(rec)
        placeholders = ",".join("?" * len(columns))
        conn.executemany(
            f"INSERT INTO {table} VALUES ({placeholders})", rows
        )
        conn.commit()
        n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"loaded {table:<16} {n:>9,} rows")

    for stmt in INDEXES:
        conn.execute(stmt)
    conn.commit()
    conn.close()
    print(f"\nwrote {DB_PATH}")


if __name__ == "__main__":
    load()
