"""Load a Smart Meter Texas CSV export into the local SQLite DB.

Full reload each run (drop + re-insert) -- the CSV is small enough that this
is simpler and safer than incremental upserts, and sidesteps DST fall-back
weirdness (the repeated 1am hour on the "fall back" day isn't a true
duplicate, so a naive dedup key would drop real usage).
"""

import csv
import datetime
import sys

import config
from smart_meter import cost, db


def _parse_date(mmddyyyy: str) -> str:
    return datetime.datetime.strptime(mmddyyyy, "%m/%d/%Y").strftime("%Y-%m-%d")


def load_csv(csv_path: str = config.CSV_PATH, db_path: str = config.DB_PATH) -> int:
    conn = db.connect(db_path)
    conn.execute("DELETE FROM intervals")

    rows_to_insert = []
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["USAGE_KWH"] == "":
                # DST spring-forward gap (e.g. 2am-3am on the "spring forward"
                # day doesn't exist) -- SMT emits placeholder rows with no
                # reading. Skip rather than treating as 0 usage.
                continue

            esiid = row["ESIID"].lstrip("'")
            usage_date = _parse_date(row["USAGE_DATE"])
            start_time = row["USAGE_START_TIME"]
            end_time = row["USAGE_END_TIME"]
            kwh = float(row["USAGE_KWH"])
            estimated_actual = row["ESTIMATED_ACTUAL"]

            free = cost.is_free_period(start_time)
            energy_cost, ercot_cost, tdu_cost, variable_cost = cost.interval_costs(
                kwh, start_time, usage_date
            )

            rows_to_insert.append(
                (
                    esiid,
                    usage_date,
                    start_time,
                    end_time,
                    f"{usage_date} {start_time}",
                    kwh,
                    estimated_actual,
                    int(free),
                    energy_cost,
                    ercot_cost,
                    tdu_cost,
                    variable_cost,
                )
            )

    conn.executemany(
        """
        INSERT INTO intervals (
            esiid, usage_date, start_time, end_time, start_ts, kwh,
            estimated_actual, is_free, energy_cost, ercot_cost, tdu_cost, variable_cost
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows_to_insert,
    )
    conn.commit()
    count = conn.execute("SELECT COUNT(*) FROM intervals").fetchone()[0]
    conn.close()
    return count


if __name__ == "__main__":
    csv_path = sys.argv[1] if len(sys.argv) > 1 else config.CSV_PATH
    n = load_csv(csv_path)
    print(f"Loaded {n} intervals into {config.DB_PATH}")
