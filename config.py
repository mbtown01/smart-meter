"""Rate plan configuration.

Numbers below are backed out from an actual Oncor/REP bill (invoice 66306063).
Edit these values directly if your plan changes.
"""

# REP energy plan: "Bright Nights" style TOU plan
FREE_PERIOD_START = "23:00"   # free energy starts at 11pm
FREE_PERIOD_END = "06:00"     # free energy ends at 6am
ENERGY_RATE_DAY = 0.09940078  # $/kWh, applies outside the free window

# Applies to ALL kWh (day + night) -- statewide ERCOT securitization charge
ERCOT_SECURITIZATION_RATE = 0.00067  # $/kWh

# REP flat monthly charge
BASE_MONTHLY_CHARGE = 9.95  # $/month

# TDU (Oncor) delivery charge, backed out as a blended $/kWh from a bill that
# only reports a lump sum ($223.81 / 4254 kWh). Not split into Oncor's actual
# fixed + variable tariff -- good enough for trend/cost analysis.
TDU_RATE_PER_KWH = 0.052612  # $/kWh

# Blended city sales tax + gross receipts reimbursement + PUC assessment,
# backed out as a single % of the pre-tax subtotal ($16.64 / $528.67).
TAX_RATE_PCT = 0.031477

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
