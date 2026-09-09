"""Historical Houston hourly temperature, cached locally in SQLite.

Uses Open-Meteo's free archive API (no API key). Only fetches when the
requested date range isn't already fully cached, so normal rebuilds
(re-running build_dashboard.py against the same CSV) stay offline.
"""

import datetime
import json
import sqlite3
import urllib.parse
import urllib.request

import config

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"


def _cached_range(conn: sqlite3.Connection):
    row = conn.execute("SELECT MIN(date), MAX(date) FROM weather_hourly").fetchone()
    return row[0], row[1]


def _fetch(start_date: str, end_date: str) -> list:
    params = {
        "latitude": config.WEATHER_LATITUDE,
        "longitude": config.WEATHER_LONGITUDE,
        "start_date": start_date,
        "end_date": end_date,
        "hourly": "temperature_2m",
        "temperature_unit": "fahrenheit",
        "timezone": config.WEATHER_TIMEZONE,
    }
    url = ARCHIVE_URL + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=30) as resp:
        data = json.load(resp)

    rows = []
    for iso_time, temp_f in zip(data["hourly"]["time"], data["hourly"]["temperature_2m"]):
        if temp_f is None:
            continue
        date_str, hour_str = iso_time.split("T")
        rows.append((date_str, int(hour_str[:2]), temp_f))
    return rows


def ensure_weather(conn: sqlite3.Connection, start_date: str, end_date: str) -> None:
    """Fetch and cache Houston hourly temps for [start_date, end_date] if not already cached."""
    cached_min, cached_max = _cached_range(conn)

    if cached_min is not None and cached_min <= start_date and cached_max >= end_date:
        return  # fully covered already

    # Re-fetch the whole requested range in one call -- simplest correct
    # thing given it's a single HTTP request regardless of range size.
    try:
        rows = _fetch(start_date, end_date)
    except Exception as e:
        print(f"Weather fetch failed ({e}); leaving existing cached data in place.")
        return

    conn.executemany(
        "INSERT OR REPLACE INTO weather_hourly (date, hour, temp_f) VALUES (?, ?, ?)",
        rows,
    )
    conn.commit()


if __name__ == "__main__":
    from smart_meter import db

    conn = db.connect()
    today = datetime.date.today().isoformat()
    min_date, max_date = conn.execute(
        "SELECT MIN(usage_date), MAX(usage_date) FROM intervals"
    ).fetchone()
    if min_date is None:
        print("No usage data ingested yet -- run ingest first.")
    else:
        ensure_weather(conn, min_date, max_date)
        n = conn.execute("SELECT COUNT(*) FROM weather_hourly").fetchone()[0]
        print(f"weather_hourly has {n} rows")
