"""Regenerate dashboard.html from whatever's currently in meter_data.db,
without touching ingest.

Use this after `smart_meter.ingest`'s CSV or `--from-smt` path has already
updated the DB -- unlike build_dashboard.py, this does NOT reload the CSV
first, so it's safe to run right after an SMT pull without discarding it.

Usage: python3 update_dashboard.py
"""

from smart_meter import dashboard, db, weather


def main():
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
