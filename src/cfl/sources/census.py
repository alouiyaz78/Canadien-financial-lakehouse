"""US Census Bureau International Trade API — effective US tariff rate on a trading partner.

Docs: https://www.census.gov/data/developers/data-sets/international-trade.html
Endpoint: /data/timeseries/intltrade/imports/hs

An API key is required (free): https://api.census.gov/data/key_signup.html
Set it in the environment before running the pipeline::

    export CENSUS_API_KEY=your_key

Variables used (monthly, US dollars):
    CON_VAL_MO   imports for consumption, total value
    CAL_DUT_MO   imports for consumption, calculated duty
Effective tariff rate (%) = CAL_DUT_MO / CON_VAL_MO * 100.

``source_id`` is the Census country code: 1220 Canada, 2010 Mexico, 5700 China.
Response: a JSON array whose first row is the header.
"""

from __future__ import annotations

import json
import os

import pandas as pd
import requests

from cfl.config import SeriesSpec
from cfl.sources.base import TIMEOUT_SECONDS, RawPayload

BASE_URL = "https://api.census.gov/data/timeseries/intltrade/imports/hs"
START = "2013-01"
KEY_ENV = "CENSUS_API_KEY"
KEY_HELP = (
    f"{KEY_ENV} is not set. Get a free key at https://api.census.gov/data/key_signup.html "
    f"then run: export {KEY_ENV}=<your key>"
)


def _api_key() -> str:
    key = os.environ.get(KEY_ENV, "").strip()
    if not key:
        raise RuntimeError(KEY_HELP)
    return key


def _get_json(session: requests.Session, params: dict) -> tuple[requests.Response, list]:
    response = session.get(BASE_URL, params={**params, "key": _api_key()}, timeout=TIMEOUT_SECONDS * 2)
    try:
        body = response.json()
    except ValueError:
        snippet = " ".join(response.text.split())[:300]
        raise RuntimeError(f"Census API returned HTTP {response.status_code}, not JSON: {snippet}") from None
    response.raise_for_status()
    return response, body


def fetch(spec: SeriesSpec, session: requests.Session) -> RawPayload:
    params = {"get": "CTY_NAME,CON_VAL_MO,CAL_DUT_MO", "CTY_CODE": spec.source_id, "time": f"from {START}"}
    response, _ = _get_json(session, params)
    # The key is not stored in Bronze: keep the URL without it.
    url = response.url.split("&key=")[0]
    return RawPayload(content=response.content, url=url, extension="json")


def fetch_metadata(source_id: str, session: requests.Session) -> dict:
    _, rows = _get_json(session, {"get": "CTY_NAME,CON_VAL_MO", "CTY_CODE": source_id, "time": "2024-01"})
    return {"label": f"US imports from {rows[1][0]} (Census country {source_id})"}


def parse(payload: bytes, spec: SeriesSpec) -> pd.DataFrame:
    rows = json.loads(payload)
    raw = pd.DataFrame(rows[1:], columns=rows[0])
    # If commodity detail is returned, keep only the all-commodities total row.
    if "I_COMMODITY" in raw.columns and raw["time"].duplicated().any():
        raw = raw[raw["I_COMMODITY"].isin(["-", "TOTAL"])]
    value = pd.to_numeric(raw["CON_VAL_MO"], errors="coerce")
    duty = pd.to_numeric(raw["CAL_DUT_MO"], errors="coerce")
    return pd.DataFrame(
        {"date": pd.to_datetime(raw["time"] + "-01"), "value": (duty / value * 100).where(value > 0)}
    ).sort_values("date", ignore_index=True)
