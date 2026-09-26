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


def _add_minutes(hhmm: str, minutes: int) -> str:
    h, m = map(int, hhmm.split(":"))
    total = (h * 60 + m + minutes) % (24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


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


def load_from_smt(dates: list, db_path: str = config.DB_PATH) -> int:
    """Pull 15-minute consumption data from Smart Meter Texas for `dates`
    (a list of 'MM/DD/YYYY' strings) and (re)insert those days' rows.

    Only the affected usage_date rows are deleted and replaced, not the
    whole table -- so calling this daily with an overlapping window (e.g.
    the last ~14 days, to pick up SMT's estimated->actual revisions) is
    idempotent and never disturbs older history. A date SMT couldn't
    provide data for (see smt_client.fetch_days) is simply absent from the
    result and its existing rows, if any, are left untouched -- same
    fail-soft philosophy as weather.ensure_weather().
    """
    from smart_meter import smt_client

    esiid, by_date = smt_client.fetch_days(dates)

    conn = db.connect(db_path)
    rows_to_insert = []

    for date_str, readings in by_date.items():
        usage_date = _parse_date(date_str)
        conn.execute("DELETE FROM intervals WHERE usage_date = ?", (usage_date,))

        for start_time, kwh, estimated_actual in readings:
            end_time = _add_minutes(start_time, 15)
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
    if len(sys.argv) > 1 and sys.argv[1] == "--from-smt":
        days_back = int(sys.argv[2]) if len(sys.argv) > 2 else 14
        dates = [
            (datetime.date.today() - datetime.timedelta(days=d)).strftime("%m/%d/%Y")
            for d in range(1, days_back + 1)
        ]
        n = load_from_smt(dates)
        print(f"Loaded {n} intervals into {config.DB_PATH} (from SMT, last {days_back} days)")
    else:
        csv_path = sys.argv[1] if len(sys.argv) > 1 else config.CSV_PATH
        n = load_csv(csv_path)
        print(f"Loaded {n} intervals into {config.DB_PATH}")
