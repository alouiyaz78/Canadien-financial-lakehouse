"""Fixtures that mimic the real API payloads, so tests never touch the network."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from cfl.config import SeriesSpec


def valet_payload(series_id: str, points: list[tuple[str, str | None]]) -> bytes:
    observations = [{"d": d, series_id: {"v": v}} if v is not None else {"d": d} for d, v in points]
    return json.dumps({"seriesDetail": {series_id: {"label": series_id}}, "observations": observations}).encode()


def statcan_payload(vector: int, points: list[tuple[str, float | None]]) -> bytes:
    data_points = [{"refPer": d, "value": v, "decimals": 1} for d, v in points]
    return json.dumps([{"status": "SUCCESS", "object": {"vectorId": vector, "vectorDataPoint": data_points}}]).encode()


def fred_payload(series_id: str, points: list[tuple[str, str]]) -> bytes:
    lines = [f"observation_date,{series_id}", *[f"{d},{v}" for d, v in points]]
    return ("\n".join(lines) + "\n").encode()


def spec(**overrides) -> SeriesSpec:
    base = dict(
        name="test_series",
        source="valet",
        source_id="TEST",
        frequency="M",
        domain="test",
        unit="%",
        monthly_agg="last",
        release_lag_months=0,
    )
    return SeriesSpec(**{**base, **overrides})


@pytest.fixture
def tmp_lake(tmp_path, monkeypatch):
    monkeypatch.setenv("CFL_DATA_DIR", str(tmp_path))
    return tmp_path


def monthly_dates(start: str, periods: int) -> list[str]:
    return [d.strftime("%Y-%m-%d") for d in pd.date_range(start, periods=periods, freq="MS")]


@pytest.fixture(autouse=True)
def no_request_delay(monkeypatch):
    """Tests never sleep between (fake) API calls."""
    monkeypatch.setenv("CFL_REQUEST_DELAY", "0")
