# Smart Meter Dashboard

Local dashboard for Smart Meter Texas 15-minute interval exports: usage
trend over time, day-over-day and week-over-week comparisons (with a
Houston temperature overlay), a billing-month bill/effective-rate summary,
and cost estimates based on your actual TOU rate plan.

"Billing months" here means your actual billing cycle, not the calendar
month. The best current guess is a repeating 91-day cycle (window-start
gaps of 30, 29, 32 days, in that order, which sums to exactly 13 weeks) -
reverse-engineered from your real bills, which it reproduces exactly.
Known cycle boundaries confirmed from your actual bills always override
that computed guess (see `KNOWN_BILLING_WINDOW_STARTS` in `config.py`) -
add an entry there whenever you get a new bill, both for accuracy and to
help confirm (or eventually disprove) the cycle theory.

## Usage

1. Drop a fresh CSV export into `data/export.csv` (same SMT format: `ESIID,
   USAGE_DATE, REVISION_DATE, USAGE_START_TIME, USAGE_END_TIME, USAGE_KWH,
   ESTIMATED_ACTUAL, CONSUMPTION_SURPLUSGENERATION`).
2. Run:

   ```
   python3 build_dashboard.py
   ```

   This needs network access the first time (or whenever the usage data's
   date range grows) to fetch Houston hourly temperature history from
   Open-Meteo; it's cached in `meter_data.db` afterward, so normal re-runs
   against the same CSV don't hit the network.

3. Open `dashboard.html` in a browser. No server required - once built,
   it's fully self-contained (data + Chart.js are embedded/vendored).

Re-running `build_dashboard.py` fully reloads the SQLite DB (`meter_data.db`)
from the CSV and regenerates `dashboard.html`, so it's always safe to re-run.

## Rate plan

Edit `config.py` if your plan changes. Both TDU delivery and the daytime
energy rate turn out to drift over time, so both are schedules -
`TDU_RATE_SCHEDULE` (`effective_date, fixed_monthly, rate_per_kwh`) and
`ENERGY_RATE_SCHEDULE` (`effective_date, rate_per_kwh`). Append a new
entry to either when your rate changes rather than editing the old one,
so historical billing months keep using the rate that was actually in
effect then. Other values (free-period window, taxes) were backed out
from actual bills - see the comments in that file for how.

## Layout

- `data/export.csv` - raw CSV export (yours, not checked in)
- `config.py` - rate plan config + Houston lat/lon for the weather fetch
- `smart_meter/ingest.py` - CSV -> SQLite loader
- `smart_meter/cost.py` - TOU cost calculations
- `smart_meter/weather.py` - Houston hourly temperature fetch + local cache
- `smart_meter/dashboard.py` + `dashboard_template.html` - dashboard generator
- `meter_data.db` - local SQLite store (regenerated each run, not checked in)
- `dashboard.html` - the generated dashboard (open this)
- `vendor/chart.umd.min.js` - vendored Chart.js, for offline use
