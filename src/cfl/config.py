"""Load and validate the series registry (config/sources.yaml) and project paths."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY = PROJECT_ROOT / "config" / "sources.yaml"

Source = Literal["valet", "statcan", "fred", "census"]
Frequency = Literal["D", "W", "M", "Q"]


class SeriesSpec(BaseModel):
    """One time series to ingest, as declared in config/sources.yaml."""

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    source: Source
    source_id: str
    frequency: Frequency
    domain: str
    unit: str
    monthly_agg: Literal["mean", "last"]
    release_lag_months: int = Field(ge=0, le=6)
    quarter_stamp: Literal["start", "end"] = "end"
    stale_after_days: int | None = Field(default=None, ge=1)
    verified: bool = False
    description: str = ""

    def max_age_days(self) -> int:
        """Age of the latest observation beyond which the series is considered late.

        Defaults derive from the frequency and the publication lag: a monthly value dated the 1st
        covers the month (~31 days), is published ``release_lag_months`` later, on any day of that
        month (~31 days), plus one week of tolerance.
        """
        if self.stale_after_days is not None:
            return self.stale_after_days
        if self.frequency == "D":
            return 7
        if self.frequency == "W":
            return 14
        if self.frequency == "M":
            return 31 * (self.release_lag_months + 2) + 7
        return 92 * 2 + 31 * self.release_lag_months + 7  # quarterly

    @field_validator("source_id", mode="before")
    @classmethod
    def _as_str(cls, value: object) -> str:
        return str(value)


class Registry(BaseModel):
    series: list[SeriesSpec]

    @field_validator("series")
    @classmethod
    def _unique_names(cls, series: list[SeriesSpec]) -> list[SeriesSpec]:
        names = [s.name for s in series]
        duplicates = {n for n in names if names.count(n) > 1}
        if duplicates:
            raise ValueError(f"Duplicate series names in registry: {sorted(duplicates)}")
        return series

    def by_name(self) -> dict[str, SeriesSpec]:
        return {s.name: s for s in self.series}

    def select(self, names: list[str] | None = None, source: str | None = None) -> list[SeriesSpec]:
        selected = self.series
        if names:
            unknown = set(names) - {s.name for s in selected}
            if unknown:
                raise KeyError(f"Unknown series: {sorted(unknown)}")
            selected = [s for s in selected if s.name in names]
        if source:
            selected = [s for s in selected if s.source == source]
        return selected


@lru_cache(maxsize=4)
def load_registry(path: Path | str = DEFAULT_REGISTRY) -> Registry:
    with open(path, encoding="utf-8") as f:
        return Registry.model_validate(yaml.safe_load(f))


def data_dir() -> Path:
    """Root of the lakehouse storage. Override with the CFL_DATA_DIR environment variable."""
    return Path(os.environ.get("CFL_DATA_DIR", PROJECT_ROOT / "data"))
