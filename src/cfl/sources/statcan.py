"""Statistics Canada Web Data Service (WDS) client.

Docs: https://www.statcan.gc.ca/en/developers/wds/user-guide
Series are addressed by vector number (e.g. v2062815 = unemployment rate, Canada, SA).

Data endpoint (POST): /getDataFromVectorsAndLatestNPeriods
    body  [{"vectorId": 2062815, "latestN": 600}]
    reply [{"status": "SUCCESS",
            "object": {"vectorId": 2062815,
                       "vectorDataPoint": [{"refPer": "2026-09-01", "value": 7.1, ...}]}}]
"""

from __future__ import annotations

import json

import pandas as pd
import requests

from cfl.config import SeriesSpec
from cfl.sources.base import TIMEOUT_SECONDS, RawPayload

BASE_URL = "https://www150.statcan.gc.ca/t1/wds/rest"
LATEST_N = 720  # 60 years of monthly data — more than enough for full history


def _vector_id(source_id: str) -> int:
    return int(source_id.lower().removeprefix("v"))


def fetch(spec: SeriesSpec, session: requests.Session) -> RawPayload:
    url = f"{BASE_URL}/getDataFromVectorsAndLatestNPeriods"
    body = [{"vectorId": _vector_id(spec.source_id), "latestN": LATEST_N}]
    response = session.post(url, json=body, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    _raise_for_wds_status(response.json(), spec.source_id)
    return RawPayload(content=response.content, url=url, extension="json")


def fetch_metadata(source_id: str, session: requests.Session) -> dict:
    url = f"{BASE_URL}/getSeriesInfoFromVector"
    response = session.post(url, json=[{"vectorId": _vector_id(source_id)}], timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    body = response.json()
    _raise_for_wds_status(body, source_id)
    return body[0]["object"]


def _raise_for_wds_status(body: list, source_id: str) -> None:
    if not body or body[0].get("status") != "SUCCESS":
        raise RuntimeError(f"StatCan WDS returned a failure for vector {source_id}: {str(body)[:300]}")


def parse(payload: bytes, spec: SeriesSpec) -> pd.DataFrame:
    body = json.loads(payload)
    _raise_for_wds_status(body, spec.source_id)
    points = body[0]["object"].get("vectorDataPoint", [])
    frame = pd.DataFrame(
        [{"date": pd.Timestamp(p["refPer"]), "value": p.get("value")} for p in points],
        columns=["date", "value"],
    )
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    return frame
