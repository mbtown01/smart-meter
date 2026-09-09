# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A local dashboard for analyzing Smart Meter Texas (SMT) 15-minute interval
usage data: a monthly bill/effective-rate summary, usage trend over time,
day-over-day and week-over-week comparisons (with a Houston temperature
overlay), and cost estimates driven by the user's actual TOU rate plan.
Pure Python 3 stdlib (no pip dependencies) + a static HTML/Chart.js frontend.
No web framework, no build step, no package.json for the app itself. The
*build* step needs network access when it has to fetch new weather data
(see `smart_meter/weather.py` below); the generated `dashboard.html` itself
has no network calls and works fully offline once produced.

## Commands

```
python3 build_dashboard.py [path/to/export.csv]   # reload CSV -> SQLite, regenerate dashboard.html
```

This is the only command. It always does a full reload (drop + re-insert)
of `meter_data.db` from the CSV, then rewrites `dashboard.html` from
`smart_meter/dashboard_template.html`. Both steps are idempotent — safe to
re-run any time, including with a stale/duplicate CSV.

There is no test suite, linter, or formatter configured. `meter_data.db` is
gitignored and fully derived from `data/export.csv` plus one cached weather
fetch; never hand-edit it.

```
python3 -m smart_meter.weather   # standalone: fetch/refresh the weather cache only
```

To verify a change to the dashboard renders correctly, there's no dev
server — `dashboard.html` is meant to be opened directly (`file://` works;
data and Chart.js are embedded/vendored, no network calls). For headless
verification, serve the directory (`python3 -m http.server`) and drive it
with Playwright — see `references/interaction.md`-style checks in past
sessions; `chromium-cli` is not installed in this environment, but
`npx playwright install chromium` works and a `node_modules/playwright`
install (in a scratch dir, not the repo) is enough for a screenshot check.

## Architecture

**Pipeline is one-directional and stateless per run**: CSV -> SQLite ->
in-memory aggregates -> JSON blob embedded directly into a generated static
HTML file. There is no server and no API; `dashboard.html` is a finished
artifact, not a template rendered per-request.

- `config.py` — the single source of truth for the rate plan (TOU energy
  rate, free-period window, ERCOT securitization rate, TDU $/kWh, base
  monthly charge, blended tax %). All cost math reads from here; nothing
  is hardcoded elsewhere. When the user's plan changes, this is the only
  file that should need editing.
- `smart_meter/cost.py` — pure functions computing per-interval cost from
  `config.py` values. `is_free_period()` handles TOU windows that wrap past
  midnight. This is intentionally decoupled from SQLite/CSV so the cost
  model can be unit-reasoned about independently.
- `smart_meter/db.py` — schema only (`intervals` table + indexes). One
  table, no migrations — schema changes mean editing `SCHEMA` and doing a
  fresh `build_dashboard.py` run (full reload handles it).
- `smart_meter/ingest.py` — CSV -> SQLite. Always deletes and re-inserts all
  rows rather than upserting/deduping. This is deliberate: SMT's DST
  fall-back day emits a genuinely repeated clock hour (not a duplicate to
  dedupe), and spring-forward emits placeholder rows with empty
  `USAGE_KWH` (skipped, not zeroed) — a dedupe-by-key approach would drop
  or corrupt real data on those two days a year. If ingest ever moves to
  incremental/upsert (e.g. once a live data-pull library replaces manual
  CSV drops), preserve this DST handling.
- `smart_meter/weather.py` — fetches Houston hourly temperature from
  Open-Meteo's free archive API (no key) in one HTTP call per date range,
  caches into `weather_hourly`. `ensure_weather()` only calls out when the
  cached `MIN(date)..MAX(date)` doesn't already cover the requested range,
  so a rebuild against an unchanged CSV stays fully offline. On fetch
  failure it logs and leaves existing cached data in place rather than
  failing the whole build.
- `smart_meter/dashboard.py` — queries SQLite, shapes JSON structures
  (`daily`, `intervals` keyed by date, `weeks` keyed by Monday date,
  `weather` keyed by date [hourly, minutes-since-midnight x-values so it
  overlays directly on the intervals axis], `monthly` [one row per
  calendar month]), and does a single string-replace of `__DATA_JSON__`
  into `dashboard_template.html`. Uses placeholder-token replacement
  rather than f-strings/`.format()` specifically to avoid brace-escaping
  collisions with the embedded CSS/JS.
  - `build_monthly()` also computes a **hypothetical no-free-nights bill**
    per month (same kWh, same TDU/base/tax, but the night kWh that was
    free gets charged back at `ENERGY_RATE_DAY`) so the dashboard can show
    the TOU plan's actual dollar benefit per month, not just the rate. If
    the free-period logic in `cost.py` changes, update this alongside it
    — it's a parallel calculation, not a call into `cost.py`.
  - Months are marked `partial` when `daysPresent < daysInMonth` (via
    `calendar.monthrange`) — the frontend renders those bars at reduced
    opacity and flags them in tooltips/table rather than hiding them,
    since a partial month's bill/kWh would otherwise mislead by comparison
    to full months.
- `smart_meter/dashboard_template.html` — the entire frontend: inline CSS
  (light/dark via `prefers-color-scheme`, palette follows the dataviz
  skill's categorical slots as CSS custom properties), inline JS (no
  bundler). Chart.js is loaded from `vendor/chart.umd.min.js` (vendored
  for offline use, not CDN). All chart views share one `unit` toggle
  (`kwh` vs `cost`) and redraw via `Chart.destroy()` + re-`new Chart()`
  rather than in-place dataset updates — simplest correct approach given
  chart count and data size are both small.
  - Trend and day-over-day use chip-based multi-select (color = selection
    order via `slotColor(i)`, not date order).
  - Week-over-week is fixed to exactly two weeks — "this week" (containing
    a single date-picker anchor, default: most recent full Mon-Sun week)
    vs "last week" (always anchor week minus 7 days). Both the usage chart
    and the Houston-temperature chart plot on the *same* synthetic 7-day
    x-axis (`buildWeekSeries()`: `x = weekday_index * 1440 + minutes`, 0 to
    10080), so "this week" and "last week" overlay directly and the two
    charts line up with each other for eyeballing weather-vs-usage
    correlation. Tooltip title (`weekAxisTooltipTitle`) decodes that x back
    to "Wed 14:30" — day *and* time, not just one or the other. Plus a
    3-tile stat row (usage delta, cost delta, biggest-change weekday) with
    delta coloring via the status palette (green=decrease, red=increase
    — "down" is hardcoded as the good direction for both kWh and cost).
  - Monthly summary is one dual-axis chart (deliberate exception to the
    usual one-axis-per-chart rule, at the user's explicit request): bars
    on the left axis (bill estimate, toggling to total kWh under the
    `kwh` unit toggle — the only place unit-toggle changes what's plotted
    rather than just the axis format) and a dot/line trend of effective
    $/kWh on a right axis (`yAxisID: 'y1'`, always in $, not unit-toggled
    — there's no kWh equivalent of a rate). The hypothetical
    no-free-nights comparison from `build_monthly()` isn't plotted here
    (it was on a second chart that got folded away) but survives in the
    savings-note text and the table view. Bars for partial months render
    at 45% opacity (`withAlpha()`) rather than being excluded.
  - Every chart's y-axis carries an explicit `scales.y.title` (and `y1`
    for the monthly chart) naming the measurement and unit — `kWh` /
    `Cost ($)` via `unitAxisLabel()` for the toggleable charts,
    `Temperature (°F)` for the weather chart, etc. Keep this in sync when
    adding a chart or an axis.
- `vendor/chart.umd.min.js` — pinned Chart.js UMD build, committed so the
  dashboard works fully offline.

## Data format assumptions (SMT CSV export)

Columns: `ESIID, USAGE_DATE, REVISION_DATE, USAGE_START_TIME,
USAGE_END_TIME, USAGE_KWH, ESTIMATED_ACTUAL,
CONSUMPTION_SURPLUSGENERATION`. Single ESIID, consumption-only (no solar
export) is assumed throughout — `ingest.py` does not currently branch on
`CONSUMPTION_SURPLUSGENERATION` or handle multiple ESIIDs. Dates are
`MM/DD/YYYY`; times are `HH:MM` 24-hour, converted to minutes-since-midnight
for the day-over-day chart's x-axis.

## Rate plan numbers currently in config.py

Backed out from one real Oncor/REP bill (see comments in `config.py` for
the arithmetic): TDU delivery and taxes are **blended per-kWh /
percentage estimates**, not itemized fixed+variable splits — accurate
enough for trend/comparison but will drift if usage patterns change
significantly from the bill they were derived from.

## Planned future direction

The CSV-drop workflow is a placeholder for a Python library that will pull
SMT data automatically. When that lands, only `ingest.py`'s entry point
changes (from reading a file to calling the library) — `cost.py`, `db.py`,
and the dashboard generation are meant to stay untouched.
