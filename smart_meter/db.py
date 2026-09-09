"""SQLite schema and connection helper."""

import sqlite3

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS intervals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    esiid TEXT NOT NULL,
    usage_date TEXT NOT NULL,   -- ISO 'YYYY-MM-DD'
    start_time TEXT NOT NULL,   -- 'HH:MM'
    end_time TEXT NOT NULL,     -- 'HH:MM'
    start_ts TEXT NOT NULL,     -- ISO 'YYYY-MM-DD HH:MM' for ordering
    kwh REAL NOT NULL,
    estimated_actual TEXT,
    is_free INTEGER NOT NULL,
    energy_cost REAL NOT NULL,
    ercot_cost REAL NOT NULL,
    tdu_cost REAL NOT NULL,
    variable_cost REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_intervals_date ON intervals(usage_date);
CREATE INDEX IF NOT EXISTS idx_intervals_start_ts ON intervals(start_ts);

CREATE TABLE IF NOT EXISTS weather_hourly (
    date TEXT NOT NULL,     -- ISO 'YYYY-MM-DD'
    hour INTEGER NOT NULL,  -- 0-23, local (America/Chicago)
    temp_f REAL NOT NULL,
    PRIMARY KEY (date, hour)
);
"""


def connect(db_path: str = config.DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    return conn
