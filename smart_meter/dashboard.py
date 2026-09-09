"""Generate a self-contained local HTML dashboard from the SQLite store."""

import calendar
import datetime
import json
import sqlite3

import config
from smart_meter import cost


def _week_start(d: datetime.date) -> datetime.date:
    return d - datetime.timedelta(days=d.weekday())  # Monday=0


def build_daily(conn: sqlite3.Connection) -> list:
    rows = conn.execute(
        """
        SELECT usage_date,
               SUM(kwh) AS kwh,
               SUM(CASE WHEN is_free THEN kwh ELSE 0 END) AS night_kwh,
               SUM(CASE WHEN NOT is_free THEN kwh ELSE 0 END) AS day_kwh,
               SUM(variable_cost) AS cost
        FROM intervals
        GROUP BY usage_date
        ORDER BY usage_date
        """
    ).fetchall()
    daily = []
    for usage_date, kwh, night_kwh, day_kwh, cost in rows:
        d = datetime.date.fromisoformat(usage_date)
        daily.append(
            {
                "d": usage_date,
                "wd": d.weekday(),
                "kwh": round(kwh, 3),
                "nightKwh": round(night_kwh, 3),
                "dayKwh": round(day_kwh, 3),
                "cost": round(cost, 4),
            }
        )
    return daily


def build_intervals(conn: sqlite3.Connection) -> dict:
    rows = conn.execute(
        "SELECT usage_date, start_time, kwh, variable_cost FROM intervals ORDER BY usage_date, start_time"
    ).fetchall()
    by_date = {}
    for usage_date, start_time, kwh, cost in rows:
        h, m = start_time.split(":")
        minutes = int(h) * 60 + int(m)
        by_date.setdefault(usage_date, []).append([minutes, round(kwh, 3), round(cost, 4)])
    return by_date


def build_weeks(daily: list) -> dict:
    weeks = {}
    for entry in daily:
        d = datetime.date.fromisoformat(entry["d"])
        ws = _week_start(d).isoformat()
        weeks.setdefault(ws, []).append(entry)
    return weeks


def build_weather(conn: sqlite3.Connection) -> dict:
    rows = conn.execute(
        "SELECT date, hour, temp_f FROM weather_hourly ORDER BY date, hour"
    ).fetchall()
    by_date = {}
    for date_str, hour, temp_f in rows:
        by_date.setdefault(date_str, []).append([hour * 60, round(temp_f, 1)])
    return by_date


def build_monthly(daily: list) -> list:
    """Monthly bill/rate summary, plus a hypothetical "no free-nights" bill for
    the same month (same kWh, same TDU/tax/base -- only the energy charge for
    night kWh is added back at the day rate) so the gap shows the TOU plan's
    actual dollar benefit."""
    by_month = {}
    for e in daily:
        ym = e["d"][:7]
        m = by_month.setdefault(ym, {"kwh": 0.0, "cost": 0.0, "nightKwh": 0.0, "days": 0})
        m["kwh"] += e["kwh"]
        m["cost"] += e["cost"]
        m["nightKwh"] += e["nightKwh"]
        m["days"] += 1

    months = []
    for ym in sorted(by_month):
        m = by_month[ym]
        year, mon = int(ym[:4]), int(ym[5:7])
        days_in_month = calendar.monthrange(year, mon)[1]

        bill = cost.monthly_bill_estimate(m["cost"])
        effective_rate = bill / m["kwh"] if m["kwh"] else 0

        hypothetical_variable_cost = m["cost"] + m["nightKwh"] * config.ENERGY_RATE_DAY
        hypothetical_bill = cost.monthly_bill_estimate(hypothetical_variable_cost)
        hypothetical_rate = hypothetical_bill / m["kwh"] if m["kwh"] else 0

        months.append(
            {
                "ym": ym,
                "kwh": round(m["kwh"], 1),
                "billEstimate": round(bill, 2),
                "effectiveRate": round(effective_rate, 4),
                "hypotheticalBillEstimate": round(hypothetical_bill, 2),
                "hypotheticalEffectiveRate": round(hypothetical_rate, 4),
                "savingsEstimate": round(hypothetical_bill - bill, 2),
                "daysPresent": m["days"],
                "daysInMonth": days_in_month,
                "partial": m["days"] < days_in_month,
            }
        )
    return months


def stats(daily: list) -> dict:
    if not daily:
        return {}
    last = daily[-30:]
    total_kwh = sum(e["kwh"] for e in last)
    total_cost = sum(e["cost"] for e in last)
    night_kwh = sum(e["nightKwh"] for e in last)
    n_days = len(last)
    return {
        "windowDays": n_days,
        "totalKwh": round(total_kwh, 1),
        "totalCost": round(total_cost, 2),
        "nightSharePct": round(100 * night_kwh / total_kwh, 1) if total_kwh else 0,
        "avgDailyKwh": round(total_kwh / n_days, 1) if n_days else 0,
    }


def render(db_path: str = config.DB_PATH, out_path: str = config.DASHBOARD_PATH) -> str:
    conn = sqlite3.connect(db_path)
    daily = build_daily(conn)
    intervals = build_intervals(conn)
    weeks = build_weeks(daily)
    weather = build_weather(conn)
    monthly = build_monthly(daily)
    conn.close()

    data = {
        "generatedAt": datetime.datetime.now().isoformat(timespec="seconds"),
        "daily": daily,
        "intervals": intervals,
        "weeks": weeks,
        "weather": weather,
        "monthly": monthly,
        "stats": stats(daily),
        "config": {
            "energyRateDay": config.ENERGY_RATE_DAY,
            "freeStart": config.FREE_PERIOD_START,
            "freeEnd": config.FREE_PERIOD_END,
            "baseMonthlyCharge": config.BASE_MONTHLY_CHARGE,
            "tdurate": config.TDU_RATE_PER_KWH,
            "taxRatePct": config.TAX_RATE_PCT,
        },
    }

    with open(TEMPLATE_PATH := __file__.replace("dashboard.py", "dashboard_template.html")) as f:
        template = f.read()

    html = template.replace("__DATA_JSON__", json.dumps(data, separators=(",", ":")))

    with open(out_path, "w") as f:
        f.write(html)

    return out_path


if __name__ == "__main__":
    path = render()
    print(f"Wrote {path}")
