"""FRED (Federal Reserve Bank of St. Louis) client — US drivers of Canadian rates.

Uses the public CSV download, which needs no API key:
    https://fred.stlouisfed.org/graph/fredgraph.csv?id=FEDFUNDS

The header is either ``observation_date,<ID>`` (current) or ``DATE,<ID>`` (older);
missing values are written as ".".
"""

from __future__ import annotations

import io

import pandas as pd
import requests

from cfl.config import SeriesSpec
from cfl.sources.base import TIMEOUT_SECONDS, RawPayload

BASE_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"


def fetch(spec: SeriesSpec, session: requests.Session) -> RawPayload:
    url = f"{BASE_URL}?id={spec.source_id}"
    response = session.get(url, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    return RawPayload(content=response.content, url=url, extension="csv")


def parse(payload: bytes, spec: SeriesSpec) -> pd.DataFrame:
    raw = pd.read_csv(io.BytesIO(payload), dtype=str)
    date_col = raw.columns[0]
    value_col = spec.source_id if spec.source_id in raw.columns else raw.columns[1]
    return pd.DataFrame(
        {
            "date": pd.to_datetime(raw[date_col]),
            "value": pd.to_numeric(raw[value_col], errors="coerce"),
        }
    )
