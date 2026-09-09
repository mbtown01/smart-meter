"""TOU cost calculations, driven entirely by config.py."""

import config


def _time_to_minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


_FREE_START_MIN = _time_to_minutes(config.FREE_PERIOD_START)
_FREE_END_MIN = _time_to_minutes(config.FREE_PERIOD_END)


def is_free_period(start_time: str) -> bool:
    """Whether an interval starting at start_time ('HH:MM') falls in the free window.

    Handles windows that wrap past midnight (e.g. 23:00-06:00).
    """
    t = _time_to_minutes(start_time)
    if _FREE_START_MIN > _FREE_END_MIN:
        return t >= _FREE_START_MIN or t < _FREE_END_MIN
    return _FREE_START_MIN <= t < _FREE_END_MIN


def interval_costs(kwh: float, start_time: str):
    """Return (energy_cost, ercot_cost, tdu_cost, variable_cost) for one interval."""
    free = is_free_period(start_time)
    energy_cost = 0.0 if free else kwh * config.ENERGY_RATE_DAY
    ercot_cost = kwh * config.ERCOT_SECURITIZATION_RATE
    tdu_cost = kwh * config.TDU_RATE_PER_KWH
    variable_cost = energy_cost + ercot_cost + tdu_cost
    return energy_cost, ercot_cost, tdu_cost, variable_cost


def monthly_bill_estimate(variable_cost_sum: float) -> float:
    """Apply the flat base charge and blended tax rate to a period's variable cost."""
    subtotal = variable_cost_sum + config.BASE_MONTHLY_CHARGE
    return subtotal * (1 + config.TAX_RATE_PCT)
