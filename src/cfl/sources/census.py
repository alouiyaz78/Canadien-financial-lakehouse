"""US Census Bureau International Trade API — effective US tariff rate on a trading partner.

Docs: https://www.census.gov/data/developers/data-sets/international-trade.html
Endpoint: /data/timeseries/intltrade/imports/hs  (no key needed for low volumes)

Variables used (monthly, US dollars):
    GEN_VAL_MO   general imports value
    CAL_DUT_MO   calculated import duties
Effective tariff rate (%) = CAL_DUT_MO / GEN_VAL_MO * 100.

``source_id`` is the Census country code: 1220 Canada, 2010 Mexico, 5700 China.
Response: a JSON array whose first row is the header.
"""

from __future__ import annotations

import json

import pandas as pd
import requests

from cfl.config import SeriesSpec
from cfl.sources.base import TIMEOUT_SECONDS, RawPayload

BASE_URL = "https://api.census.gov/data/timeseries/intltrade/imports/hs"
START = "2013-01"


def fetch(spec: SeriesSpec, session: requests.Session) -> RawPayload:
    params = {"get": "CTY_NAME,GEN_VAL_MO,CAL_DUT_MO", "CTY_CODE": spec.source_id, "time": f"from {START}"}
    response = session.get(BASE_URL, params=params, timeout=TIMEOUT_SECONDS * 2)
    response.raise_for_status()
    return RawPayload(content=response.content, url=response.url, extension="json")


def fetch_metadata(source_id: str, session: requests.Session) -> dict:
    params = {"get": "CTY_NAME", "CTY_CODE": source_id, "time": "2024-01"}
    response = session.get(BASE_URL, params=params, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    rows = response.json()
    return {"label": f"US imports from {rows[1][0]} (Census country {source_id})"}


def parse(payload: bytes, spec: SeriesSpec) -> pd.DataFrame:
    rows = json.loads(payload)
    raw = pd.DataFrame(rows[1:], columns=rows[0])
    value = pd.to_numeric(raw["GEN_VAL_MO"], errors="coerce")
    duty = pd.to_numeric(raw["CAL_DUT_MO"], errors="coerce")
    return pd.DataFrame(
        {"date": pd.to_datetime(raw["time"] + "-01"), "value": (duty / value * 100).where(value > 0)}
    ).sort_values("date", ignore_index=True)
