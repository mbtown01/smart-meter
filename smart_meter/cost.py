"""TOU cost calculations, driven entirely by config.py."""

import bisect

import config


def _time_to_minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


_FREE_START_MIN = _time_to_minutes(config.FREE_PERIOD_START)
_FREE_END_MIN = _time_to_minutes(config.FREE_PERIOD_END)

# config.TDU_RATE_SCHEDULE sorted ascending by effective_date, for bisecting.
_TDU_SCHEDULE = sorted(config.TDU_RATE_SCHEDULE, key=lambda row: row[0])
_TDU_SCHEDULE_DATES = [row[0] for row in _TDU_SCHEDULE]

# config.ENERGY_RATE_SCHEDULE sorted ascending by effective_date, for bisecting.
_ENERGY_SCHEDULE = sorted(config.ENERGY_RATE_SCHEDULE, key=lambda row: row[0])
_ENERGY_SCHEDULE_DATES = [row[0] for row in _ENERGY_SCHEDULE]


def is_free_period(start_time: str) -> bool:
    """Whether an interval starting at start_time ('HH:MM') falls in the free window.

    Handles windows that wrap past midnight (e.g. 23:00-06:00).
    """
    t = _time_to_minutes(start_time)
    if _FREE_START_MIN > _FREE_END_MIN:
        return t >= _FREE_START_MIN or t < _FREE_END_MIN
    return _FREE_START_MIN <= t < _FREE_END_MIN


def tdu_rate_for_date(usage_date: str):
    """Return (fixed_monthly, rate_per_kwh) in effect on usage_date (ISO 'YYYY-MM-DD')."""
    i = bisect.bisect_right(_TDU_SCHEDULE_DATES, usage_date) - 1
    i = max(i, 0)
    _, fixed_monthly, rate_per_kwh = _TDU_SCHEDULE[i]
    return fixed_monthly, rate_per_kwh


def energy_rate_for_date(usage_date: str) -> float:
    """Return the daytime energy $/kWh in effect on usage_date (ISO 'YYYY-MM-DD')."""
    i = bisect.bisect_right(_ENERGY_SCHEDULE_DATES, usage_date) - 1
    i = max(i, 0)
    _, rate_per_kwh = _ENERGY_SCHEDULE[i]
    return rate_per_kwh


def interval_costs(kwh: float, start_time: str, usage_date: str):
    """Return (energy_cost, ercot_cost, tdu_cost, variable_cost) for one interval."""
    free = is_free_period(start_time)
    energy_rate = config.NIGHT_ENERGY_RATE if free else energy_rate_for_date(usage_date)
    energy_cost = kwh * energy_rate
    ercot_cost = kwh * config.ERCOT_SECURITIZATION_RATE
    _, tdu_rate = tdu_rate_for_date(usage_date)
    tdu_cost = kwh * tdu_rate
    variable_cost = energy_cost + ercot_cost + tdu_cost
    return energy_cost, ercot_cost, tdu_cost, variable_cost


def monthly_bill_estimate(variable_cost_sum: float, tdu_fixed_monthly: float) -> float:
    """Apply the flat REP base charge, flat TDU charge, and blended tax rate
    to a period's variable (usage-driven) cost."""
    subtotal = variable_cost_sum + config.BASE_MONTHLY_CHARGE + tdu_fixed_monthly
    return subtotal * (1 + config.TAX_RATE_PCT)
