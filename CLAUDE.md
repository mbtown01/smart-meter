# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A local dashboard for analyzing Smart Meter Texas (SMT) 15-minute interval
usage data: a monthly bill/effective-rate summary, usage trend over time,
day-over-day and week-over-week comparisons (with a Houston temperature
overlay), and cost estimates driven by the user's actual TOU rate plan.
Pure Python 3 stdlib + a static HTML/Chart.js frontend, with one deliberate
exception: `smart_meter/smt_client.py` (the Smart Meter Texas auto-pull path)
depends on the `smart-meter-texas` PyPI package (see `requirements.txt`) --
its auth/session/SSL-cert-chain handling isn't worth reimplementing in
stdlib. The CSV-based `build_dashboard.py` path needs no pip installs at
all. No web framework, no build step, no package.json for the app itself.
The *build* step needs network access when it has to fetch new weather data
(see `smart_meter/weather.py` below) or pull from SMT; the generated
`dashboard.html` itself has no network calls and works fully offline once
produced.

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
  rate, free-period window + rate, ERCOT securitization rate, TDU rate
  schedule, base monthly charge, blended tax %). All cost math reads from
  here; nothing is hardcoded elsewhere. When the user's plan changes, this
  is the only file that should need editing.
  - `TDU_RATE_SCHEDULE` is a list of `(effective_date, fixed_monthly,
    rate_per_kwh)` tuples, sorted ascending — TDU rates change occasionally
    (per the user, "once or twice a year"), not every billing cycle, so
    each interval/window looks up whichever entry was in effect on its
    date rather than applying one global constant. The first entry's date
    must predate all usage data (a `2000-01-01` sentinel does this).
    Adding a rate change means appending a new tuple, not editing existing
    ones — old windows should keep resolving to the old rate.
- `smart_meter/cost.py` — pure functions computing per-interval cost from
  `config.py` values. `is_free_period()` handles TOU windows that wrap past
  midnight. `tdu_rate_for_date()` bisects `TDU_RATE_SCHEDULE` (via a
  pre-sorted module-level list) to find the rate in effect on a given
  `usage_date`. This is intentionally decoupled from SQLite/CSV so the cost
  model can be unit-reasoned about independently.
  `monthly_bill_estimate(variable_cost_sum, tdu_fixed_monthly)` takes the
  TDU fixed charge as a parameter (not a constant) since it's now
  date-dependent — callers look it up via `tdu_rate_for_date()` first.
- `smart_meter/db.py` — schema only (`intervals` table + indexes). One
  table, no migrations — schema changes mean editing `SCHEMA` and doing a
  fresh `build_dashboard.py` run (full reload handles it).
- `smart_meter/ingest.py` — two entry points into the same `intervals`
  table. `load_csv()` (CSV -> SQLite, `python3 build_dashboard.py` or
  `python3 -m smart_meter.ingest [path]`) always deletes and re-inserts
  *all* rows rather than upserting/deduping. This is deliberate: SMT's DST
  fall-back day emits a genuinely repeated clock hour (not a duplicate to
  dedupe), and spring-forward emits placeholder rows with empty
  `USAGE_KWH` (skipped, not zeroed) — a dedupe-by-key approach would drop
  or corrupt real data on those two days a year. `load_from_smt()`
  (`python3 -m smart_meter.ingest --from-smt [days_back]`, default 14 days)
  pulls live from Smart Meter Texas via `smt_client.py` instead of a CSV,
  scoped to a rolling window so it can be re-run daily to pick up SMT's
  estimated->actual revisions without re-fetching all history; it deletes
  and re-inserts only the affected `usage_date`s, preserving the same
  full-day-reload DST safety per date. Both paths write the same schema and
  are safe to interleave.
- `smart_meter/smt_client.py` — thin wrapper around the community
  `smart-meter-texas` package (pip dependency, see above) for Smart Meter
  Texas's unofficial API. Reuses that package's `Account`/`Client`/
  `ClientSSLContext` for auth, session/token handling, and its SSL
  cert-chain workaround, but does NOT use its `Meter.get_15min()` — that
  method only parses the "G" (solar Generation) record type from SMT's
  `/adhoc/intervalsynch` response and silently returns `None` for a
  consumption-only account. `smt_client._parse_energy_data()`
  re-implements the same decoding targeting "C" (Consumption) instead.
  ESIID is auto-discovered via `Account.fetch_meters()` each run rather
  than hardcoded, consistent with the single-ESIID assumption below.
  Credentials come only from `SMT_USERNAME`/`SMT_PASSWORD` env vars — see
  `.env.example` — never hardcode or commit them; `.env` and `.venv/` are
  gitignored.
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
  **billing window**, see below]), and does a single string-replace of
  `__DATA_JSON__` into `dashboard_template.html`. Uses placeholder-token
  replacement rather than f-strings/`.format()` specifically to avoid
  brace-escaping collisions with the embedded CSS/JS.
  - **Billing windows, not calendar months.** `build_billing_windows()`
    (the `monthly` key in the JSON is still named that for frontend
    simplicity, but it is *not* calendar-month grouping) buckets days
    using window-start dates from `_resolve_window_start(n)`, which checks
    `config.KNOWN_BILLING_WINDOW_STARTS` (a `"YYYY-MM" -> date` dict of
    confirmed boundaries straight from real bills) **first**, falling back
    to `_cycle_window_start(n)` only for months with no confirmed entry.
    A window runs from its start up to (not including) the next window's
    start, and is *named* for the calendar month its start date falls in.
    **The computed default is a repeating 91-day cycle** — window-start
    gaps of `(30, 29, 32)` days, in that order, summing to exactly 13
    weeks — reverse-engineered from 7 consecutive confirmed bill periods
    (2026-03 through 2026-09), which it reproduces exactly (an earlier
    "9th of the month, Friday-adjusted if it's a weekend" guess only got
    5 of those 7 right, missing March and September in opposite
    directions with no day-of-week explanation found). A 91-day period
    preserves weekday, which is why starts visibly rotate
    Tue → Thu → Fri → Tue → ... — the working theory is a meter-read
    route fixed by weekday on a 13-week rotation, not anything
    calendar-month-shaped, though this is unconfirmed before 2026-03 and
    could break if the route ever changes. **Known-vs-computed matters
    for exactly that reason**: known boundaries always win over the
    formula, even now that the formula matches every known point exactly
    — add a new entry to `KNOWN_BILLING_WINDOW_STARTS` every time the
    user shares another bill's period, both to improve accuracy and to
    eventually confirm or break the cycle theory. One bill that arrived
    bundling two meter-read periods into one "catch-up" invoice (double
    base charge, `$19.90`) still gave two clean confirmed starts from its
    two listed service periods — summing our independently-computed
    windows for those two periods matched that bundled bill's total
    ($676.42) to the penny, strong validation of both the cycle and the
    per-window rate methodology below working correctly together.
    `_billing_window_starts()` generates one extra window before the
    data's earliest date and one trailing boundary after the latest, so
    `bisect.bisect_right` against that list correctly assigns every day
    including the partial windows at each end of the dataset. This
    replaced a plain `e["d"][:7]` calendar-month grouping — if you see
    `calendar.monthrange` anywhere, it's stale, since window length is now
    computed as `(next_start - this_start).days`, not a fixed calendar
    month length.
  - **Both TDU and the daytime energy rate are billed as a single rate for
    the whole window, at whichever rate is in effect at the window's
    *close* — not a per-day blend.** Confirmed against real bills for
    each independently: a CenterPoint TDU rate change mid-window, and
    separately a daytime energy rate that turned out to differ across
    windows too (0.108 in May/June 2026, 0.09940078 in July, ~0.0991 in
    August — `config.ENERGY_RATE_SCHEDULE`, same shape and lookup
    convention as `TDU_RATE_SCHEDULE`). Both `tdu_cost` and
    `day_energy_cost` in `build_billing_windows()` are therefore a single
    `window_kwh * rate_at_window_end` multiply, **not** a sum of
    `intervals.tdu_cost` / `intervals.energy_cost` (which are still
    stored date-split per interval in the DB via `cost.interval_costs()`,
    and are fine as an approximation for the daily/weekly/trend charts —
    just not accurate enough for a billing-window total once a rate
    change lands inside a window). If a *third* thing turns out to drift
    like this (base charge? ERCOT rate?), assume the same "one rate for
    the whole window, at close" rule applies until proven otherwise,
    rather than assuming per-interval date-splitting is right by default.
    Also: real bills show one lump "TDU Delivery Charges" line (fixed +
    volumetric together), so `tduCost` in the JSON/chart bundles
    `tdu_fixed` into it too (`tdu_cost_display`) — `everythingElseCost`'s
    remainder calc accounts for this, so don't double-subtract the fixed
    charge if you touch that line.
  - Each window's bill is split into 4 categories for the frontend's
    stacked chart: `dayEnergyCost`, `nightEnergyCost` (window-level flat
    calc, see above), `tduCost` (see above), and `everythingElseCost` —
    computed as `bill - day - night - tdu`, i.e. a **remainder**, not
    summed directly from ERCOT+base+tax. This guarantees the 4 stacked
    segments always add up exactly to `billEstimate` even if the
    tax/ERCOT/base math changes later; don't replace it with a direct sum
    without preserving that invariant.
  - Also computes a **hypothetical no-free-nights bill** per window (same
    kWh, same TDU/base/tax, but the night kWh that was free gets charged
    back at `ENERGY_RATE_DAY - NIGHT_ENERGY_RATE`) so the dashboard can
    show the TOU plan's actual dollar benefit, not just the rate. If the
    free-period logic in `cost.py` changes, update this alongside it —
    it's a parallel calculation, not a call into `cost.py`.
  - Windows are marked `partial` when `daysPresent < daysInWindow` (window
    length varies, ~28-33 days depending on weekday adjustments at each
    end) — the frontend renders those bars at reduced opacity and flags
    them in tooltips/table rather than hiding them, since a partial
    window's bill/kWh would otherwise mislead by comparison to full ones.
    A very short partial window (e.g. 1 day of new CSV data past the last
    known boundary) can produce a wild-looking `effectiveRate` — expected,
    not a bug, since it's dividing by a tiny kWh denominator.
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
    usual one-axis-per-chart rule, at the user's explicit request): a
    **stacked** bar on the left axis (`MONTHLY_CATEGORIES` — Daytime
    energy / Nighttime energy / TDU / Everything else, `stack: 'bill'`,
    `scales.x/y.stacked: true`) and a dot/line trend of effective $/kWh on
    a right axis (`yAxisID: 'y1'`, always in $ — there's no unit toggle on
    this chart at all now, since a $-category breakdown has no sensible
    kWh equivalent). Nighttime energy will render as an invisible
    zero-height segment under the current plan (free nights); it's kept
    as its own category rather than folded into "everything else" so the
    stack mirrors the real bill's line items and stays meaningful if the
    free-period rate ever becomes nonzero. **Draw order matters and isn't
    array-index-based for mixed bar+line Chart.js configs**: the line
    dataset needs a lower `order` value than the bars (`order: 1` vs
    `order: 2` here) or its point markers render invisibly underneath the
    bars — learned the hard way, don't remove those `order` fields when
    touching this chart. The hypothetical no-free-nights comparison from
    `build_billing_windows()` isn't plotted on this chart (it was on a
    second chart that got folded away) but survives in the savings-note
    text and the table view. Bars for partial windows render at 45%
    opacity (`withAlpha()`) rather than being excluded.
  - **Temperature vs. usage, by time of day** is eight small-multiple
    scatter charts (`TOD_BUCKETS`, one per 3-hour window of the day, built
    fresh as 8 `<canvas>`+`Chart` instances per render rather than static
    markup — `tempScatterCharts` tracks them for `destroy()` on
    re-render), each plotting one point per (date, window): that window's
    average temperature (from `weather`, hourly so a 3h bucket always
    averages exactly 3 readings) against that window's *summed* kWh/cost
    (from `intervals`), computed entirely client-side in
    `buildTodBucketData()` — nothing server-side precomputes this. All
    eight panels share one x/y domain (computed once across all buckets'
    points) so slope is visually comparable panel-to-panel; each panel
    also gets its own dashed OLS trend line (`linregress()`, per-bucket)
    with slope + R² as a one-line note under its title. The point: usage
    during the free-night window should show a flatter slope than
    afternoon/evening windows if free-night usage is habit-driven rather
    than AC-driven — this chart is the direct test of that, which neither
    the whole-day trend chart nor the week-over-week temp overlay
    (time-aligned, not correlation-shaped) can show. This replaced an
    earlier single-scatter version (`daily[].avgTempF`, one point per
    *whole* day, split by weekday/weekend) that answered "does temp
    predict usage" but not "at what time of day" — the weekday/weekend
    split is gone now that time-of-day is the split. 8 series would blow
    past the categorical palette's ~6-hue ceiling if drawn as one
    multi-color chart, hence small multiples instead — and per-panel
    `scales.x/y.title` is dropped in favor of one shared caption
    (`#tempScatterAxisNote`) below the grid, a deliberate exception to the
    "every chart carries an explicit axis title" rule for the same reason
    the monthly chart gets a dual-axis exception:
    eight repeated titles would be pure noise. The trend line is excluded
    from tooltips via `tooltip.filter`, not by omitting a `label`
    callback — returning `undefined` from a Chart.js label callback still
    renders an (empty) tooltip row, it doesn't skip the entry. Dots are
    colored per-point by calendar month (`monthColor()`, a fixed-order
    per-panel `backgroundColor` function keyed on `ctx.raw.month`) to
    surface seasonal hysteresis — whether the same temperature drives
    different usage in, say, April vs. October. Month is a **cyclic**
    variable (December is adjacent to January, not its opposite), so this
    is deliberately a 12-step HSL hue wheel (`hslToHex()`, 30° apart,
    fixed S/L per light/dark mode) rather than either a 12-color
    categorical palette (would blow the ~6-hue pairwise-CVD ceiling) or a
    single-hue sequential ramp (would wrongly imply Jan and Dec are
    extremes rather than neighbors) — this is a distinct technique from
    the "never rainbow" rule, which is about misrepresenting linear
    magnitude, not phase/cyclic data. Consequence of that adjacency-by-
    design: neighboring months (e.g. Nov/Dec, Jan/Feb) read as similar
    hues, not maximally distinct — expected, not a bug, but means don't
    "fix" it by re-spacing hues for max pairwise separation, that would
    break the cyclic property. One shared legend (`renderMonthLegend()`,
    `#tempScatterMonthLegend`, 12 fixed swatches Jan→Dec) renders once
    above the grid rather than per-panel.
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

- **TDU delivery (`TDU_RATE_SCHEDULE`) is now the real published CenterPoint
  rate-change history** (13 entries, 2024-09 through 2026-09), given
  directly by the user — not an estimate or inference. It's CenterPoint,
  not Oncor (an earlier guess from the ESIID prefix was wrong; don't
  reintroduce "Oncor" into comments/docs). Append new entries as
  CenterPoint publishes further changes; don't edit old ones.
- Taxes are still a **blended percentage estimate**, but now cross-checked
  against two independent real bills: 3.1477% (July) and 3.1634%
  (August) — close enough that `TAX_RATE_PCT` (3.1477%) doesn't need
  changing. Still not itemized sales-tax/gross-receipts/PUC splits.
- `KNOWN_BILLING_WINDOW_STARTS` currently covers 2026-03 through 2026-09,
  confirmed from 5 real bills' periods (one of which bundled two periods
  into one catch-up invoice, still yielding two confirmed starts). The
  91-day-cycle default (see above) reproduces all of these exactly, so
  it's a solid bet for 2026-03 onward even in months without an explicit
  override; before 2026-03 it's unconfirmed either way — treat
  billing-window numbers for 2025 with a bit more skepticism.
- `ENERGY_RATE_SCHEDULE` (new) replaced the old single `ENERGY_RATE_DAY`
  constant after a full regression against 5 real bills found the same
  drift-over-time pattern TDU has: 0.108/kWh confirmed for May, June, and
  a March/April bill; 0.09940078 for July (exact); ~0.0991 for August
  (small residual, see below). Only 3 confirmed segments so far — the
  first entry (0.108) is extended backward as a guess covering all of
  2025, which no bill has confirmed or refuted.
- **Regression results after both schedule fixes, across all 5 bills the
  user has shared:** July exact ($0.01 off), June near-exact ($0.05 off,
  both day-energy and TDU matched their bill lines exactly), May within
  $0.39 (day-energy essentially exact; a small ~$0.31 TDU residual — that
  bill itemizes TDU into 5-6 separate TDSP line items like "Transmission
  Cost Recovery Factor" that our single blended rate approximates rather
  than reproduces line-by-line), August within $1.18 (day-energy now
  exact; ~$1.07 TDU residual, still unexplained — the CenterPoint table
  values are the best information available, so this may just be that
  table's own precision limit). The March+April catch-up bill matched to
  the penny on total ($676.42) when summing our two independently
  computed windows for it, which is strong end-to-end validation of the
  whole model (cycle + both rate schedules) rather than one lucky number.

## Planned future direction

The automatic SMT pull (`ingest.load_from_smt` / `smt_client.py`) now
exists alongside the original CSV-drop workflow, as anticipated —
`cost.py`, `db.py`, and the dashboard generation were untouched by it, per
plan. Not yet built: wiring `load_from_smt` into a scheduled run (the
Azure design settled on a Container Apps Job with a cron trigger, pulling
to a DB persisted in Blob Storage and publishing `dashboard.html` to Blob
static website hosting rather than an always-on server) and confirming the
"C" record type's estimated/actual flag decoding against a real SMT
response (currently mirrors the library's unverified "G"-type assumption —
see `smt_client.py`).
