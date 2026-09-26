"""Fetch 15-minute CONSUMPTION interval data from Smart Meter Texas.

Reuses the `smart-meter-texas` PyPI package's Account/Client/ClientSSLContext
for authentication, session/token handling, and the SSL cert-chain workaround
SMT's site requires -- that plumbing is non-trivial and already solved there.

What this module does NOT reuse is the package's own `Meter.get_15min()`:
that method only extracts the "G" (solar Generation) record type from SMT's
`/adhoc/intervalsynch` response, and returns None for a consumption-only
account (this project's assumption -- see CLAUDE.md). `_parse_energy_data`
below re-implements the same parsing but targets "C" (Consumption) instead,
following the exact same comma-split / 4-slots-per-hour decoding the upstream
code uses for "G", since both record types come from the same endpoint and
almost certainly share the same encoding -- unverified against a live
response until this has actually been run once against a real account.

Credentials are read from SMT_USERNAME / SMT_PASSWORD environment variables
only -- never pass them as arguments that could land in shell history or
logs, and never hardcode them here.
"""

import asyncio
import datetime
import logging
import os

import aiohttp
from smart_meter_texas import Account, Client, ClientSSLContext
from smart_meter_texas.const import INTERVAL_SYNCH

_LOGGER = logging.getLogger(__name__)


def _parse_energy_data(energy_data: list) -> list:
    """Decode the "C" (Consumption) entry's comma-separated RD string into
    [(start_time 'HH:MM', kwh, estimated_actual_flag), ...] for one day.

    Mirrors smart_meter_texas.Meter.get_15min()'s decoding of the "G" entry:
    each reading is "value-flag", ordered as 4 slots/hour (00, 15, 30, 45)
    starting at hour 0. The estimated/actual flag's exact values are assumed
    to line up with the SMT CSV export's ESTIMATED_ACTUAL column but that's
    unconfirmed -- inspect a raw response the first time this runs for real.
    """
    rows = []
    for entry in energy_data:
        if entry.get("RT") != "C":
            continue

        hour = -1
        minute_check = 0
        for reading in entry.get("RD", "").split(","):
            if reading == "":
                continue

            if minute_check % 4 == 0:
                hour += 1
                minute = "00"
            elif minute_check % 4 == 1:
                minute = "15"
            elif minute_check % 4 == 2:
                minute = "30"
            else:
                minute = "45"
            minute_check += 1

            parts = reading.split("-")
            kwh = float(parts[0])
            flag = parts[1] if len(parts) > 1 else ""
            rows.append((f"{hour:02d}:{minute}", kwh, flag))
        return rows  # only one "C" entry expected per day
    return rows


async def _fetch_day(client: Client, esiid: str, date_str: str) -> list:
    """date_str: 'MM/DD/YYYY'. Returns rows from _parse_energy_data, or []
    if SMT has no data for that date yet (common for the most recent day)."""
    json_response = await client.request(
        INTERVAL_SYNCH,
        json={
            "startDate": date_str,
            "endDate": date_str,
            "reportFormat": "JSON",
            "ESIID": [esiid],
            "versionDate": None,
            "readDate": None,
            "versionNum": None,
            "dataType": None,
        },
    )
    data = json_response.get("data") or {}
    energy_data = data.get("energyData")
    if energy_data is None:
        raise RuntimeError(f"Unexpected SMT response for {date_str}: {json_response}")

    return _parse_energy_data(energy_data)


async def _fetch_range_async(username: str, password: str, dates: list) -> tuple:
    client_ssl_ctx = ClientSSLContext()
    ssl_context = await client_ssl_ctx.get_ssl_context()

    async with aiohttp.ClientSession() as websession:
        account = Account(username, password)
        client = Client(websession, account, ssl_context)
        await client.authenticate()

        meters = await account.fetch_meters(client)
        if not meters:
            raise RuntimeError("SMT account has no associated meters")
        if len(meters) > 1:
            _LOGGER.warning(
                "SMT account has %d meters; using the first (ESIID %s) -- "
                "this project assumes a single ESIID",
                len(meters),
                meters[0].esiid,
            )
        esiid = meters[0].esiid

        results = {}
        for date_str in dates:
            try:
                results[date_str] = await _fetch_day(client, esiid, date_str)
            except Exception as e:
                _LOGGER.warning("SMT fetch failed for %s (%s); skipping that date", date_str, e)

        return esiid, results


def fetch_days(dates: list) -> tuple:
    """Synchronous entry point. dates: list of 'MM/DD/YYYY' strings.

    Returns (esiid, {date_str: [(start_time, kwh, estimated_actual), ...]}).
    A date is omitted from the result dict if SMT's fetch failed for it
    (e.g. TDSP hasn't posted that day's data yet) -- callers should leave
    existing DB rows for a missing date untouched rather than deleting them.
    """
    username = os.environ["SMT_USERNAME"]
    password = os.environ["SMT_PASSWORD"]
    return asyncio.run(_fetch_range_async(username, password, dates))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).strftime("%m/%d/%Y")
    esiid, data = fetch_days([yesterday])
    print(f"ESIID: {esiid}")
    rows = data.get(yesterday, [])
    print(f"{yesterday}: {len(rows)} intervals")
    for row in rows[:8]:
        print(" ", row)
