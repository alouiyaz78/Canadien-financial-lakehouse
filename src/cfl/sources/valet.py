"""Bank of Canada Valet API client.

Docs: https://www.bankofcanada.ca/valet/docs
Observations endpoint: /valet/observations/{series_id}/json  (full history when no dates given)

Response shape::

    {"seriesDetail": {...},
     "observations": [{"d": "2026-10-28", "CBC20210": {"v": "2.50"}}, ...]}

Quarterly series may use dates like "2025Q3"; both formats are handled.
"""

from __future__ import annotations

import json
import re

import pandas as pd
import requests

from cfl.config import SeriesSpec
from cfl.sources.base import TIMEOUT_SECONDS, RawPayload

BASE_URL = "https://www.bankofcanada.ca/valet"
_QUARTER = re.compile(r"^(\d{4})-?Q([1-4])$")


def fetch(spec: SeriesSpec, session: requests.Session) -> RawPayload:
    url = f"{BASE_URL}/observations/{spec.source_id}/json"
    response = session.get(url, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    return RawPayload(content=response.content, url=url, extension="json")


def fetch_metadata(source_id: str, session: requests.Session) -> dict:
    response = session.get(f"{BASE_URL}/series/{source_id}/json", timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json().get("seriesDetails", {})


def _parse_date(raw: str) -> pd.Timestamp:
    match = _QUARTER.match(raw)
    if match:
        year, quarter = int(match.group(1)), int(match.group(2))
        return pd.Timestamp(year=year, month=3 * (quarter - 1) + 1, day=1)
    return pd.Timestamp(raw)


def parse(payload: bytes, spec: SeriesSpec) -> pd.DataFrame:
    body = json.loads(payload)
    rows = []
    for obs in body.get("observations", []):
        cell = obs.get(spec.source_id) or {}
        rows.append({"date": _parse_date(obs["d"]), "value": cell.get("v")})
    frame = pd.DataFrame(rows, columns=["date", "value"])
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    return frame
