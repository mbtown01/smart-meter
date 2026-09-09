"""Reload the CSV export into SQLite and regenerate dashboard.html.

Usage: python3 build_dashboard.py [path/to/export.csv]
"""

import sys

import config
from smart_meter import dashboard, db, ingest, weather


def main():
    csv_path = sys.argv[1] if len(sys.argv) > 1 else config.CSV_PATH
    n = ingest.load_csv(csv_path)
    print(f"Loaded {n} intervals into {config.DB_PATH}")

    conn = db.connect()
    min_date, max_date = conn.execute(
        "SELECT MIN(usage_date), MAX(usage_date) FROM intervals"
    ).fetchone()
    if min_date is not None:
        weather.ensure_weather(conn, min_date, max_date)
    conn.close()

    out = dashboard.render()
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
