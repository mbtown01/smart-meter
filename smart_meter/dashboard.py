"""Generate a self-contained local HTML dashboard from the SQLite store."""

import bisect
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
               SUM(CASE WHEN is_free THEN energy_cost ELSE 0 END) AS night_energy_cost,
               SUM(CASE WHEN NOT is_free THEN energy_cost ELSE 0 END) AS day_energy_cost,
               SUM(ercot_cost) AS ercot_cost,
               SUM(tdu_cost) AS tdu_cost,
               SUM(variable_cost) AS cost
        FROM intervals
        GROUP BY usage_date
        ORDER BY usage_date
        """
    ).fetchall()
    daily = []
    for (
        usage_date,
        kwh,
        night_kwh,
        day_kwh,
        night_energy_cost,
        day_energy_cost,
        ercot_cost,
        tdu_cost,
        variable_cost,
    ) in rows:
        d = datetime.date.fromisoformat(usage_date)
        daily.append(
            {
                "d": usage_date,
                "wd": d.weekday(),
                "kwh": round(kwh, 3),
                "nightKwh": round(night_kwh, 3),
                "dayKwh": round(day_kwh, 3),
                "nightEnergyCost": round(night_energy_cost, 4),
                "dayEnergyCost": round(day_energy_cost, 4),
                "ercotCost": round(ercot_cost, 4),
                "tduCost": round(tdu_cost, 4),
                "cost": round(variable_cost, 4),
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


# Billing windows repeat on a 91-day cycle (30, 29, 32 day gaps, in that
# order, summing to exactly 13 weeks) -- reverse-engineered from 7
# consecutive confirmed real bill periods (2026-03 through 2026-09), which
# it reproduces exactly. A 91-day period preserves weekday, which is why
# window starts visibly rotate Tue -> Thu -> Fri -> Tue -> ...; the working
# theory is a meter-read route fixed by weekday on a 13-week rotation,
# rather than anything calendar-month-shaped. This replaced an earlier
# "9th of the month, or the Friday before if it lands on a weekend" guess
# that got 5 of those 7 points right -- this one gets all 7, but is still
# unconfirmed before 2026-03 and could break if the route/cycle changes,
# hence config.KNOWN_BILLING_WINDOW_STARTS overriding it wherever a real
# bill has confirmed the actual boundary.
_CYCLE_ANCHOR = datetime.date(2026, 3, 10)  # a confirmed billing-window start
_CYCLE_STEPS = (30, 29, 32)
_CYCLE_LEN = sum(_CYCLE_STEPS)  # 91 = exactly 13 weeks
_CYCLE_CUM = (0, _CYCLE_STEPS[0], _CYCLE_STEPS[0] + _CYCLE_STEPS[1])


def _cycle_window_start(n: int) -> datetime.date:
    """The n-th billing-window start relative to _CYCLE_ANCHOR (n=0 is the
    anchor itself), stepping through the repeating cycle forward for
    positive n and backward for negative n."""
    full_cycles, phase = divmod(n, 3)
    return _CYCLE_ANCHOR + datetime.timedelta(days=full_cycles * _CYCLE_LEN + _CYCLE_CUM[phase])


def _resolve_window_start(n: int) -> datetime.date:
    """The n-th cycle-computed window start, overridden by
    config.KNOWN_BILLING_WINDOW_STARTS if that start's calendar month has a
    confirmed entry."""
    d = _cycle_window_start(n)
    known = config.KNOWN_BILLING_WINDOW_STARTS.get(f"{d.year:04d}-{d.month:02d}")
    return datetime.date.fromisoformat(known) if known else d


def _billing_window_starts(min_date: datetime.date, max_date: datetime.date) -> list:
    """Billing-window start dates covering [min_date, max_date], plus one
    trailing start past max_date so every window's end is known."""
    avg_step = _CYCLE_LEN / 3
    n = int((min_date - _CYCLE_ANCHOR).days / avg_step) - 4  # comfortable margin
    while _resolve_window_start(n) > min_date:
        n -= 1

    starts = [_resolve_window_start(n)]
    while starts[-1] <= max_date:
        n += 1
        starts.append(_resolve_window_start(n))
    return starts


def build_billing_windows(daily: list) -> list:
    """Bill/rate summary per billing window -- 12 windows/year, each starting
    the 9th of the month (or the Friday before, if the 9th falls on a
    weekend) and running up to the moment before the next window starts.
    Named by the calendar month its start date falls in. TDU (fixed and
    volumetric both) is billed at a single rate for the whole window --
    whichever was in effect at the window's close -- confirmed against two
    real bills, one of which had a rate change mid-window. Also computes a
    hypothetical "no free-nights" bill for the same window (same kWh, same
    TDU/tax/base -- only the energy charge for night kWh is added back at
    the day rate) so the gap shows the TOU plan's actual dollar benefit,
    and splits the bill into day/night energy, TDU, and an "everything
    else" remainder (ERCOT + base charge + tax) for the stacked chart."""
    if not daily:
        return []

    dates = [datetime.date.fromisoformat(e["d"]) for e in daily]
    starts = _billing_window_starts(min(dates), max(dates))

    by_window = {}
    for e, d in zip(daily, dates):
        idx = max(bisect.bisect_right(starts, d) - 1, 0)
        window_start = starts[idx]
        window_end = starts[idx + 1] if idx + 1 < len(starts) else None
        w = by_window.setdefault(
            window_start,
            {
                "end": window_end,
                "kwh": 0.0,
                "dayKwh": 0.0,
                "nightKwh": 0.0,
                "ercotCost": 0.0,
                "days": 0,
            },
        )
        w["kwh"] += e["kwh"]
        w["dayKwh"] += e["dayKwh"]
        w["nightKwh"] += e["nightKwh"]
        w["ercotCost"] += e["ercotCost"]
        w["days"] += 1

    windows = []
    for window_start in sorted(by_window):
        w = by_window[window_start]
        window_end = w["end"]
        days_in_window = (window_end - window_start).days if window_end else w["days"]

        # Both TDU and the daytime energy rate are billed as a single rate for
        # the WHOLE window, not date-split per interval -- confirmed against
        # real bills for each: a mid-window CenterPoint TDU rate change, and
        # separately an energy rate that turned out to differ across windows
        # (0.108 in May/June, 0.09940078 in July, ~0.0991 in August). Both use
        # whichever rate was in effect at the window's *end* (i.e. when the
        # bill actually gets cut), not a blend of the rates that applied on
        # each individual day. The TDU fixed monthly charge follows the same rule.
        window_last_day = (window_end - datetime.timedelta(days=1)) if window_end else window_start
        tdu_fixed, tdu_rate = cost.tdu_rate_for_date(window_last_day.isoformat())
        tdu_cost = w["kwh"] * tdu_rate
        # Real bills show one lump "TDU Delivery Charges" line (fixed + volumetric
        # combined) rather than breaking them out -- match that for the stacked
        # chart/table category, even though the fixed charge is tracked separately
        # below for the tax/subtotal math (monthly_bill_estimate adds it there).
        tdu_cost_display = tdu_cost + tdu_fixed

        day_rate = cost.energy_rate_for_date(window_last_day.isoformat())
        day_energy_cost = w["dayKwh"] * day_rate
        night_energy_cost = w["nightKwh"] * config.NIGHT_ENERGY_RATE

        variable_cost = day_energy_cost + night_energy_cost + w["ercotCost"] + tdu_cost
        bill = cost.monthly_bill_estimate(variable_cost, tdu_fixed)
        effective_rate = bill / w["kwh"] if w["kwh"] else 0

        hypothetical_variable_cost = variable_cost + w["nightKwh"] * (
            day_rate - config.NIGHT_ENERGY_RATE
        )
        hypothetical_bill = cost.monthly_bill_estimate(hypothetical_variable_cost, tdu_fixed)
        hypothetical_rate = hypothetical_bill / w["kwh"] if w["kwh"] else 0

        # Remainder rather than a direct sum, so the stacked chart's segments
        # always add up exactly to the bill total (ERCOT + base charge + tax).
        everything_else_cost = bill - day_energy_cost - night_energy_cost - tdu_cost_display

        windows.append(
            {
                "ym": window_start.isoformat()[:7],
                "start": window_start.isoformat(),
                "end": (window_end - datetime.timedelta(days=1)).isoformat() if window_end else None,
                "kwh": round(w["kwh"], 1),
                "dayEnergyCost": round(day_energy_cost, 2),
                "nightEnergyCost": round(night_energy_cost, 2),
                "tduCost": round(tdu_cost_display, 2),
                "everythingElseCost": round(everything_else_cost, 2),
                "billEstimate": round(bill, 2),
                "effectiveRate": round(effective_rate, 4),
                "hypotheticalBillEstimate": round(hypothetical_bill, 2),
                "hypotheticalEffectiveRate": round(hypothetical_rate, 4),
                "savingsEstimate": round(hypothetical_bill - bill, 2),
                "daysPresent": w["days"],
                "daysInWindow": days_in_window,
                "partial": w["days"] < days_in_window,
            }
        )
    return windows


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
    monthly = build_billing_windows(daily)
    conn.close()

    today = datetime.date.today().isoformat()
    current_tdu_fixed, current_tdu_rate = cost.tdu_rate_for_date(today)
    current_energy_rate = cost.energy_rate_for_date(today)

    data = {
        "generatedAt": datetime.datetime.now().isoformat(timespec="seconds"),
        "daily": daily,
        "intervals": intervals,
        "weeks": weeks,
        "weather": weather,
        "monthly": monthly,
        "stats": stats(daily),
        "config": {
            "energyRateDay": current_energy_rate,
            "freeStart": config.FREE_PERIOD_START,
            "freeEnd": config.FREE_PERIOD_END,
            "baseMonthlyCharge": config.BASE_MONTHLY_CHARGE,
            "tduFixedMonthly": current_tdu_fixed,
            "tduRate": current_tdu_rate,
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
