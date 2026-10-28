"""Gold layer: monthly, model-ready table for the two forecasting problems.

Problem A — core inflation forecasting
    targets ``y_cpi_trim_h{3,6,12}``, ``y_cpi_median_h{...}``, ``y_cpi_headline_yoy_h{...}``

Problem B — policy-rate direction
    targets ``y_policy_dir_{1,3}m`` in {-1 cut, 0 hold, +1 hike} and the matching change in points

Timing convention (the important part)
--------------------------------------
A row dated month ``t`` represents the information set at the *end* of month ``t``.

* Features use the **real-time** panel: every series is shifted by its
  ``release_lag_months`` (CPI for September is only published in October, so it
  enters the row of October). This prevents look-ahead leakage in backtests.
* Targets use the **reference** panel (values for the month they describe),
  shifted *forward* by the horizon.

Output::

    data/gold/model_table_monthly.parquet
    data/gold/model_table_monthly.csv      same content, for quick inspection / BI tools
    data/gold/column_dictionary.csv        every column, its role and meaning
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from cfl.config import Registry, data_dir

log = logging.getLogger(__name__)

HORIZONS_INFLATION = (3, 6, 12)
HORIZONS_POLICY = (1, 3)
POLICY_TOLERANCE = 0.01  # changes smaller than 1 bp count as "hold"
FFILL_LIMIT = {"D": 2, "W": 2, "M": 2, "Q": 3}


def gold_dir() -> Path:
    return data_dir() / "gold"


# --------------------------------------------------------------------------- panels
def to_monthly(observations: pd.DataFrame, registry: Registry) -> pd.DataFrame:
    """Reference panel: one column per series, one row per calendar month (PeriodIndex)."""
    specs = registry.by_name()
    columns = {}
    for name, frame in observations.groupby("name"):
        spec = specs.get(name)
        if spec is None:
            continue
        dates = pd.DatetimeIndex(frame["date"])
        if spec.frequency == "Q":
            # A quarterly value describes the quarter; it is stamped on the quarter's last month.
            periods = dates.to_period("Q").asfreq("M", how="end")
        else:
            periods = dates.to_period("M")
        values = pd.Series(frame["value"].to_numpy(), index=periods).sort_index()
        grouped = values.groupby(level=0)
        columns[name] = grouped.mean() if spec.monthly_agg == "mean" else grouped.last()

    panel = pd.DataFrame(columns).sort_index()
    # Never extend past the current month (quarterly stamps can point to a future quarter end).
    last_month = min(panel.index.max(), pd.Timestamp.now().to_period("M"))
    full_range = pd.period_range(panel.index.min(), last_month, freq="M")
    panel = panel.reindex(full_range)
    panel.index.name = "month"
    return _splice_usdcad(panel)


def _splice_usdcad(panel: pd.DataFrame) -> pd.DataFrame:
    """Extend the 2017+ USD/CAD series backwards with the legacy noon rate."""
    if {"usdcad", "usdcad_noon_legacy"} <= set(panel.columns):
        panel["usdcad"] = panel["usdcad"].combine_first(panel["usdcad_noon_legacy"])
        panel = panel.drop(columns="usdcad_noon_legacy")
    return panel


def to_real_time(reference: pd.DataFrame, registry: Registry) -> pd.DataFrame:
    """Shift each series by its publication lag, then carry the last known value forward."""
    specs = registry.by_name()
    out = {}
    for name in reference.columns:
        spec = specs[name]
        shifted = reference[name].shift(spec.release_lag_months)
        out[name] = shifted.ffill(limit=FFILL_LIMIT[spec.frequency])
    return pd.DataFrame(out, index=reference.index)


# --------------------------------------------------------------------------- features
def _yoy(series: pd.Series) -> pd.Series:
    return (series / series.shift(12) - 1.0) * 100.0


def _has(frame: pd.DataFrame, *names: str) -> bool:
    return all(n in frame.columns for n in names)


def derive_features(rt: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str]]:
    """Economically meaningful transformations, computed on the real-time panel only."""
    f = pd.DataFrame(index=rt.index)
    doc: dict[str, str] = {}

    def add(name: str, values: pd.Series, description: str) -> None:
        f[name] = values
        doc[name] = description

    if _has(rt, "bond_10y", "bond_2y"):
        add("term_spread_10y_2y", rt.bond_10y - rt.bond_2y, "10y minus 2y GoC yield (curve slope)")
    if _has(rt, "bond_10y", "tbill_3m"):
        add("term_spread_10y_3m", rt.bond_10y - rt.tbill_3m, "10y yield minus 3-month T-bill")
    if _has(rt, "tbill_6m", "policy_rate"):
        add("market_vs_policy_6m", rt.tbill_6m - rt.policy_rate, "6m T-bill minus policy rate (market-implied path)")
    if _has(rt, "policy_rate", "cpi_trim"):
        add("real_policy_rate", rt.policy_rate - rt.cpi_trim, "Policy rate minus latest CPI-trim")
    if _has(rt, "policy_rate", "us_fed_funds"):
        add("ca_us_policy_gap", rt.policy_rate - rt.us_fed_funds, "BoC policy rate minus Fed funds")
    if _has(rt, "bond_2y", "us_treasury_2y"):
        add("ca_us_2y_spread", rt.bond_2y - rt.us_treasury_2y, "Canada minus US 2-year yield")
    if _has(rt, "mortgage_5y", "bond_5y"):
        add("mortgage_spread_5y", rt.mortgage_5y - rt.bond_5y, "5y mortgage rate minus 5y GoC yield (bank margin)")

    if "policy_rate" in rt:
        for k in (1, 3, 6, 12):
            add(f"policy_rate_chg_{k}m", rt.policy_rate.diff(k), f"Change in policy rate over the last {k} months")

    if "cpi_all_items_index" in rt:
        headline = _yoy(rt.cpi_all_items_index)
        add("cpi_headline_yoy", headline, "Headline CPI inflation, y/y % (computed from the index)")
        if "cpi_trim" in rt:
            add(
                "headline_minus_trim",
                headline - rt.cpi_trim,
                "Headline minus CPI-trim (transitory shocks, e.g. energy)",
            )
    for core in ("cpi_trim", "cpi_median", "cpi_common"):
        if core in rt:
            add(f"{core}_chg_3m", rt[core].diff(3), f"3-month change in {core}")
            add(f"{core}_chg_12m", rt[core].diff(12), f"12-month change in {core}")

    for level, label in [
        ("bcpi_total", "BCPI total"),
        ("bcpi_energy", "BCPI energy"),
        ("bcpi_ex_energy", "BCPI excluding energy"),
        ("wti_oil", "WTI oil price"),
        ("usdcad", "USD/CAD"),
        ("ceer_nominal", "Nominal effective exchange rate"),
        ("employment", "Employment"),
        ("gdp_monthly", "Real GDP (monthly)"),
        ("us_cpi_index", "US CPI"),
    ]:
        if level in rt:
            add(f"{level}_yoy", _yoy(rt[level]), f"{label}, y/y % change")
    if _has(rt, "us_tariff_rate_on_canada"):
        add(
            "us_tariff_canada_chg_3m",
            rt.us_tariff_rate_on_canada.diff(3),
            "3-month change in the US effective tariff on Canada",
        )
        add(
            "us_tariff_canada_chg_12m",
            rt.us_tariff_rate_on_canada.diff(12),
            "12-month change in the US effective tariff on Canada",
        )
    if _has(rt, "us_tariff_rate_on_canada", "us_tariff_rate_on_china"):
        add(
            "us_tariff_china_minus_canada",
            rt.us_tariff_rate_on_china - rt.us_tariff_rate_on_canada,
            "Tariff gap China vs Canada (relative competitiveness on the US market)",
        )
    if "trade_policy_uncertainty" in rt:
        add(
            "trade_policy_uncertainty_z",
            (rt.trade_policy_uncertainty - rt.trade_policy_uncertainty.rolling(60, min_periods=24).mean())
            / rt.trade_policy_uncertainty.rolling(60, min_periods=24).std(),
            "Trade-policy uncertainty, z-score vs its 5-year history",
        )
    for level, label in [("us_import_prices_from_canada", "US import prices from Canada")]:
        if level in rt:
            add(f"{level}_yoy", _yoy(rt[level]), f"{label}, y/y % change")
    if "wti_oil" in rt:
        add("wti_oil_chg_3m_pct", (rt.wti_oil / rt.wti_oil.shift(3) - 1) * 100, "WTI oil price, 3-month % change")
    if "unemployment_rate" in rt:
        add("unemployment_chg_3m", rt.unemployment_rate.diff(3), "3-month change in the unemployment rate")
        add("unemployment_chg_12m", rt.unemployment_rate.diff(12), "12-month change in the unemployment rate")
        add(
            "unemployment_gap_12m_min",
            rt.unemployment_rate - rt.unemployment_rate.rolling(12, min_periods=6).min(),
            "Unemployment minus its 12-month low (Sahm-style slack signal)",
        )
    return f, doc


# --------------------------------------------------------------------------- targets
def _direction(change: pd.Series) -> pd.Series:
    direction = np.sign(change.where(change.abs() >= POLICY_TOLERANCE, 0.0))
    return direction.where(change.notna())


def build_targets(reference: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str]]:
    t = pd.DataFrame(index=reference.index)
    doc: dict[str, str] = {}

    inflation = {}
    for core in ("cpi_trim", "cpi_median"):
        if core in reference:
            inflation[core] = reference[core]
    if "cpi_all_items_index" in reference:
        inflation["cpi_headline_yoy"] = _yoy(reference.cpi_all_items_index)

    for name, series in inflation.items():
        for h in HORIZONS_INFLATION:
            col = f"y_{name}_h{h}"
            t[col] = series.shift(-h)
            doc[col] = f"[Problem A] {name} for reference month t+{h}"

    if "policy_rate" in reference:
        rate = reference.policy_rate
        for h in HORIZONS_POLICY:
            change = rate.shift(-h) - rate
            t[f"y_policy_change_{h}m"] = change
            t[f"y_policy_dir_{h}m"] = _direction(change)
            doc[f"y_policy_change_{h}m"] = f"[Problem B] Policy rate change (pts) from end of t to end of t+{h}"
            doc[f"y_policy_dir_{h}m"] = f"[Problem B] Direction over the next {h} month(s): -1 cut, 0 hold, +1 hike"
    return t, doc


# --------------------------------------------------------------------------- assembly
def build_gold(observations: pd.DataFrame, registry: Registry) -> pd.DataFrame:
    reference = to_monthly(observations, registry)
    rt = to_real_time(reference, registry)
    derived, derived_doc = derive_features(rt)
    targets, target_doc = build_targets(reference)

    table = pd.concat([rt, derived, targets], axis=1)
    current_month = pd.Timestamp.now().to_period("M")
    table.insert(0, "is_partial_month", table.index >= current_month)

    specs = registry.by_name()
    dictionary = pd.DataFrame(
        [
            {"column": "is_partial_month", "role": "meta", "description": "Row describes a month that is not over yet"},
            *[
                {
                    "column": c,
                    "role": "feature_raw",
                    "description": (
                        f"{specs[c].description} "
                        f"[{specs[c].source}:{specs[c].source_id}, lag {specs[c].release_lag_months}m]"
                    ),
                }
                for c in rt.columns
            ],
            *[{"column": c, "role": "feature_derived", "description": d} for c, d in derived_doc.items()],
            *[{"column": c, "role": "target", "description": d} for c, d in target_doc.items()],
        ]
    )

    out = gold_dir()
    out.mkdir(parents=True, exist_ok=True)
    export = table.copy()
    export.index = export.index.to_timestamp()
    export.index.name = "month"
    export.to_parquet(out / "model_table_monthly.parquet")
    export.to_csv(out / "model_table_monthly.csv", float_format="%.4f")
    dictionary.to_csv(out / "column_dictionary.csv", index=False)
    log.info("Gold: %d months x %d columns (%s → %s)", *table.shape, table.index.min(), table.index.max())
    return table


def read_gold() -> pd.DataFrame:
    return pd.read_parquet(gold_dir() / "model_table_monthly.parquet")
