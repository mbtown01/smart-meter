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

## SMT auto-pull (local testing)

Instead of dropping a CSV, you can pull recent usage directly from Smart
Meter Texas. This is genuinely two separate steps -- pulling data and
regenerating the HTML are different scripts, not one command:

1. **One-time setup:**

   ```
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   cp .env.example .env        # then edit .env with your real SMT login
   ```

   `.env` is gitignored -- it holds `SMT_USERNAME`/`SMT_PASSWORD` and should
   never be committed. `.env.example` is the safe-to-commit template; keep
   real values out of it.

2. **Step 1 -- pull from SMT into the DB:**

   ```
   set -a; source .env; set +a
   python3 -m smart_meter.ingest --from-smt 14
   ```

   Pulls the last 14 days (adjust the number) and (re)inserts just those
   dates into `meter_data.db` -- older history is left alone. Re-running
   this is safe; it's how you pick up SMT's estimated -> actual revisions.

3. **Step 2 -- regenerate the HTML from whatever's in the DB:**

   ```
   python3 update_dashboard.py
   ```

   No SMT credentials needed for this step -- it only reads the local DB
   and (if needed) extends the cached weather range. Deliberately does NOT
   reload the CSV, so it won't undo step 1.

4. Open `dashboard.html` in a browser.

**Debugging in VS Code:** `.vscode/launch.json` has four ready-to-run
configs (Run and Debug panel, or F5): "1. SMT Ingest", "2. Update
Dashboard", "Build Dashboard from CSV" (the original full-reload path),
and "SMT Client dry-run" (fetches and prints one day's intervals without
touching the DB -- useful for inspecting a raw response). The SMT-talking
configs load credentials from `.env` automatically via `envFile`; set
breakpoints in `smart_meter/ingest.py` or `smart_meter/smt_client.py` and
step through either half of the pipeline independently.

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
- `.env` - your SMT login (gitignored); `.env.example` is the checked-in template
- `requirements.txt` - the one pip dependency (`smart-meter-texas`), needed
  only for the SMT auto-pull path -- the CSV path stays pure stdlib
- `smart_meter/ingest.py` - CSV -> SQLite loader, plus `--from-smt` (SMT -> SQLite)
- `smart_meter/smt_client.py` - talks to Smart Meter Texas's unofficial API
- `smart_meter/cost.py` - TOU cost calculations
- `smart_meter/weather.py` - Houston hourly temperature fetch + local cache
- `smart_meter/dashboard.py` + `dashboard_template.html` - dashboard generator
- `build_dashboard.py` - CSV -> DB (full reload) -> HTML, one command
- `update_dashboard.py` - DB -> HTML only, no ingest (pairs with `--from-smt`)
- `meter_data.db` - local SQLite store (regenerated each run, not checked in)
- `dashboard.html` - the generated dashboard (open this)
- `vendor/chart.umd.min.js` - vendored Chart.js, for offline use
- `.vscode/launch.json` - debug configs for stepping through SMT ingest and
  dashboard regen separately
