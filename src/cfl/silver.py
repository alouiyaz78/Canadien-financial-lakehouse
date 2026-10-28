"""Silver layer: parse the latest Bronze snapshot of every series into one tidy table.

Output::

    data/silver/observations/          Delta table, long format: name, source, source_id, frequency, date, value
    data/silver/quality_report.csv     one row per series: coverage, gaps, dropped values

Rules applied: numeric casting, rows without a value dropped (and counted),
duplicate dates removed (keeping the last), sorted by date.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from cfl.bronze import latest_snapshot
from cfl.config import SeriesSpec, data_dir
from cfl.sources import client_for
from cfl.storage import read_table, write_table

log = logging.getLogger(__name__)

SILVER_COLUMNS = ["name", "source", "source_id", "frequency", "date", "value"]


def silver_dir() -> Path:
    return data_dir() / "silver"


def clean_series(raw: pd.DataFrame, spec: SeriesSpec) -> tuple[pd.DataFrame, dict]:
    """Apply Silver rules to one parsed series and return it with its quality metrics."""
    n_raw = len(raw)
    missing = int(raw["value"].isna().sum())
    frame = raw.dropna(subset=["value"])
    duplicates = int(frame["date"].duplicated().sum())
    frame = frame.drop_duplicates(subset="date", keep="last").sort_values("date")

    gaps = frame["date"].diff().dt.days
    quality = {
        "name": spec.name,
        "source": spec.source,
        "source_id": spec.source_id,
        "frequency": spec.frequency,
        "n_raw": n_raw,
        "n_clean": len(frame),
        "n_missing_dropped": missing,
        "n_duplicates_dropped": duplicates,
        "first_date": frame["date"].min(),
        "last_date": frame["date"].max(),
        "max_gap_days": float(gaps.max()) if len(frame) > 1 else None,
        "last_value": float(frame["value"].iloc[-1]) if len(frame) else None,
    }
    frame = frame.assign(name=spec.name, source=spec.source, source_id=spec.source_id, frequency=spec.frequency)[
        SILVER_COLUMNS
    ]
    return frame, quality


def build_silver(specs: list[SeriesSpec]) -> tuple[pd.DataFrame, pd.DataFrame]:
    frames, reports = [], []
    for spec in specs:
        snapshot = latest_snapshot(spec)
        if snapshot is None:
            log.warning("no Bronze snapshot for %s — run `cfl ingest` first", spec.name)
            continue
        raw = client_for(spec.source).parse(snapshot.read_bytes(), spec)
        frame, quality = clean_series(raw, spec)
        quality["bronze_snapshot"] = snapshot.name
        frames.append(frame)
        reports.append(quality)

    if not frames:
        raise RuntimeError("Silver is empty: no Bronze snapshots found.")

    observations = pd.concat(frames, ignore_index=True)
    report = pd.DataFrame(reports)

    out = silver_dir()
    out.mkdir(parents=True, exist_ok=True)
    version = write_table(observations, out / "observations")
    report.to_csv(out / "quality_report.csv", index=False)
    log.info("Silver: %d series, %d observations (Delta version %d)", report.shape[0], observations.shape[0], version)
    return observations, report


def read_silver(version: int | None = None) -> pd.DataFrame:
    return read_table(silver_dir() / "observations", version)
