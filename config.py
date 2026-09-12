"""Rate plan configuration.

Numbers below are backed out from an actual CenterPoint/REP bill (invoice
66306063). Edit these values directly if your plan changes.
"""

# REP energy plan: "Bright Nights" style TOU plan
FREE_PERIOD_START = "23:00"   # free energy starts at 11pm
FREE_PERIOD_END = "06:00"     # free energy ends at 6am
NIGHT_ENERGY_RATE = 0.0        # $/kWh, applies inside the free window (currently free)

# Daytime energy rate, as a schedule of (effective_date, rate_per_kwh) --
# this REP rate turns out to drift over time just like TDU does, confirmed
# across 3 different real bills. Same convention as TDU_RATE_SCHEDULE: a
# billing window is billed at a single rate, whichever is in effect at the
# window's close (see cost.energy_rate_for_date). Sorted ascending by
# effective_date.
#
# The first entry (0.108) is the earliest ACTUALLY CONFIRMED rate (from the
# May/June/combined-March-April bills) extended backward as a best guess
# for 2025 data, which no bill has confirmed one way or the other -- treat
# billing-window dollar amounts before 2026-03 with more skepticism than
# ones from 2026-06 onward. The 2026-08-07 entry's rate (0.0991) is itself
# an approximation, read off the August bill's own rounded display of its
# rate rather than backed out to full precision.
ENERGY_RATE_SCHEDULE = [
    ("2000-01-01", 0.108),
    ("2026-07-09", 0.09940078),
    ("2026-08-07", 0.0991),
]

# Applies to ALL kWh (day + night) -- statewide ERCOT securitization charge
ERCOT_SECURITIZATION_RATE = 0.00067  # $/kWh

# REP flat monthly charge
BASE_MONTHLY_CHARGE = 9.95  # $/month

# TDU (CenterPoint) delivery charge, as a schedule of (effective_date,
# fixed_monthly, rate_per_kwh) -- published rate-change history from
# CenterPoint, not an estimate. TDU rates change several times a year (this
# table has 13 changes across ~2 years); each interval's TDU cost uses
# whichever entry was in effect on its usage_date (see
# cost.tdu_rate_for_date). Sorted ascending by effective_date. Append new
# rows here as CenterPoint publishes further changes -- don't edit old rows,
# since past billing windows need to keep resolving to the rate that was
# actually in effect.
TDU_RATE_SCHEDULE = [
    ("2024-09-01", 4.39, 0.05351),
    ("2024-12-31", 4.39, 0.053509),
    ("2025-03-01", 4.39, 0.04338),
    ("2025-04-28", 4.90, 0.042392),
    ("2025-07-21", 4.90, 0.044608),
    ("2025-09-01", 4.90, 0.058104),
    ("2025-09-17", 4.90, 0.059027),
    ("2025-12-07", 4.90, 0.060009),
    ("2026-03-01", 4.90, 0.049993),
    ("2026-05-18", 4.90, 0.049715),
    ("2026-06-01", 4.90, 0.051461),
    ("2026-08-15", 4.90, 0.049811),
    ("2026-09-02", 4.90, 0.06413),
]

# Blended city sales tax + gross receipts reimbursement + PUC assessment,
# backed out as a single % of the pre-tax subtotal ($16.64 / $528.67, and
# independently checked against a second bill at $20.34 / $642.93 -- 3.15%
# and 3.16%, consistent).
TAX_RATE_PCT = 0.031477

# Confirmed billing-window start dates, straight from actual bills (each
# bill states its period as "start - up to end", end exclusive; a bill that
# bundles two meter-read periods into one "catch-up" invoice, as happened
# once, still gives two separate confirmed starts). These override the
# *computed* default -- a repeating 91-day cycle of 30/29/32-day gaps
# (see _CYCLE_ANCHOR/_CYCLE_STEPS in dashboard.py), fit exactly to these 7
# points -- for whichever months they cover. The cycle currently reproduces
# every one of these 7 starts exactly (that's how it was derived), so right
# now these entries are redundant with the computed default; keep them
# anyway; known facts should always win over a guess, even a guess that
# currently agrees with them, in case the route/cycle ever changes and a
# bill stops matching it. Keyed by "YYYY-MM" of the window's label (the
# calendar month its start falls in). Add more as you see more bills.
KNOWN_BILLING_WINDOW_STARTS = {
    "2026-03": "2026-03-10",
    "2026-04": "2026-04-09",
    "2026-05": "2026-05-08",
    "2026-06": "2026-06-09",
    "2026-07": "2026-07-09",
    "2026-08": "2026-08-07",
    "2026-09": "2026-09-08",
}

DB_PATH = "meter_data.db"
CSV_PATH = "data/export.csv"
DASHBOARD_PATH = "dashboard.html"

# Houston, TX -- for the temperature-correlation chart. Historical hourly
# data comes from Open-Meteo's free archive API (no key required) and is
# cached in weather_hourly so a build only hits the network when the usage
# data's date range grows beyond what's already cached.
WEATHER_LATITUDE = 29.7604
WEATHER_LONGITUDE = -95.3698
WEATHER_TIMEZONE = "America/Chicago"
