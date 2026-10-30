"""BI marts (Gold) for the Power BI report — a star schema at **reference dates**.

Unlike the ML table (``gold.py``), which shifts every series by its publication lag so a
backtest never sees the future, BI tables keep each value on the period it describes:
September CPI is shown in September. Mixing the two would make the charts lie.

Tables (``bi_`` prefix in Unity Catalog, ``data/gold/bi/`` locally):

    dim_date                     daily calendar 1990 → today
    dim_series                   one row per series of the registry (source, domain, unit, lag…)
    fact_observations            every observation (name, date, value) — generic exploration
    fact_yield_curve             daily yields by tenor (overnight → 30 years)
    fact_policy_decisions        every change of the policy rate since 2001, grouped in cycles
    fact_policy_calendar         announced Bank of Canada decision dates (config/boc_calendar.yaml)
    mart_macro_monthly           one row per month: inflation, labour, Taylor rule, oil in CAD,
                                 tariffs, mortgage renewal shock, spreads
    mart_energy_passthrough      correlation of energy prices with inflation k months later
    mart_policy_signals          latest hawkish / dovish scorecard (one row per indicator)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from cfl.config import PROJECT_ROOT, Registry, data_dir
from cfl.gold import to_monthly

BI_START = pd.Timestamp("1990-01-01")

INFLATION_TARGET = 2.0
TARGET_BAND = (1.0, 3.0)
# Bank of Canada estimate of the nominal neutral rate: 2.25%–3.25% → real neutral ≈ 0.25%–1.25%.
NEUTRAL_REAL_RATE = 0.75
# Okun's law: 1 point of unemployment above trend ≈ 2 points of negative output gap.
OKUN_COEFFICIENT = 2.0

YIELD_CURVE_TENORS = [
    ("policy_rate", "Overnight", 0),
    ("tbill_1m", "1M", 1),
    ("tbill_3m", "3M", 3),
    ("tbill_6m", "6M", 6),
    ("tbill_1y", "1Y", 12),
    ("bond_2y", "2Y", 24),
    ("bond_5y", "5Y", 60),
    ("bond_10y", "10Y", 120),
    ("bond_long", "30Y", 360),
]

CALENDAR_FILE = PROJECT_ROOT / "config" / "boc_calendar.yaml"


def bi_dir() -> Path:
    return data_dir() / "gold" / "bi"


# --------------------------------------------------------------------------- dimensions
def dim_date(start: pd.Timestamp = BI_START, end: pd.Timestamp | None = None) -> pd.DataFrame:
    dates = pd.date_range(start, end or pd.Timestamp.now().normalize(), freq="D")
    return pd.DataFrame(
        {
            "date": dates,
            "year": dates.year,
            "quarter": "Q" + dates.quarter.astype(str),
            "month_number": dates.month,
            "month_name": dates.strftime("%b"),
            "year_month": dates.strftime("%Y-%m"),
            "month_start": dates.to_period("M").to_timestamp(),
            "decade": (dates.year // 10 * 10).astype(str) + "s",
        }
    )


def dim_series(registry: Registry) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "name": s.name,
                "description": s.description,
                "source": s.source,
                "source_id": s.source_id,
                "domain": s.domain,
                "unit": s.unit,
                "frequency": s.frequency,
                "release_lag_months": s.release_lag_months,
                "discontinued": s.discontinued,
            }
            for s in registry.series
        ]
    )


# --------------------------------------------------------------------------- facts
def fact_observations(observations: pd.DataFrame) -> pd.DataFrame:
    out = observations[["name", "date", "value"]].copy()
    out["date"] = pd.to_datetime(out["date"])
    return out[out["date"] >= BI_START].sort_values(["name", "date"], ignore_index=True)


def _daily(observations: pd.DataFrame, name: str) -> pd.Series:
    frame = observations[observations["name"] == name]
    series = pd.Series(frame["value"].to_numpy(dtype=float), index=pd.to_datetime(frame["date"]))
    return series[~series.index.duplicated(keep="last")].sort_index()


def fact_yield_curve(observations: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for name, label, months in YIELD_CURVE_TENORS:
        series = _daily(observations, name)
        if series.empty:
            continue
        frames.append(
            pd.DataFrame({"date": series.index, "tenor": label, "tenor_months": months, "yield_pct": series.to_numpy()})
        )
    out = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return out[out["date"] >= BI_START].reset_index(drop=True) if len(out) else out


def fact_policy_decisions(observations: pd.DataFrame) -> pd.DataFrame:
    """Every change of the target overnight rate, with easing / tightening cycles.

    Valet's target-rate series (CBC20210 / V39079) records the **effective** date of a new rate, the
    business day after the announcement (Wednesday announcement → Thursday). ``announcement_date``
    is that previous business day, the date people refer to ("the 28 October hike").
    """
    rate = _daily(observations, "policy_rate").dropna()
    change = rate.diff()
    moves = change[change.abs() >= 0.01]
    if moves.empty:
        return pd.DataFrame(columns=["date", "previous_rate", "new_rate", "change_bp", "direction", "cycle_id"])
    out = pd.DataFrame(
        {
            "date": moves.index,
            "previous_rate": rate.shift(1).loc[moves.index].to_numpy(),
            "new_rate": rate.loc[moves.index].to_numpy(),
            "change_bp": (moves.to_numpy() * 100).round().astype(int),
        }
    )
    out.insert(1, "announcement_date", out["date"] - pd.offsets.BDay(1))
    out["direction"] = np.where(out["change_bp"] > 0, "Hike", "Cut")
    out["days_since_previous_move"] = out["date"].diff().dt.days
    new_cycle = out["direction"] != out["direction"].shift()
    out["cycle_id"] = new_cycle.cumsum().astype(int)
    cycle_start = out.groupby("cycle_id")["announcement_date"].transform("min")
    out["cycle"] = cycle_start.dt.strftime("%Y-%m") + " " + out["direction"]
    out["cumulative_cycle_bp"] = out.groupby("cycle_id")["change_bp"].cumsum()
    return out


def fact_policy_calendar(path: Path = CALENDAR_FILE) -> pd.DataFrame:
    with open(path, encoding="utf-8") as f:
        entries = yaml.safe_load(f)["decisions"]
    out = pd.DataFrame(entries)
    out["date"] = pd.to_datetime(out["date"])
    return out.sort_values("date", ignore_index=True)


# --------------------------------------------------------------------------- monthly mart
def _yoy(series: pd.Series) -> pd.Series:
    return (series / series.shift(12) - 1.0) * 100.0


def _col(panel: pd.DataFrame, name: str) -> pd.Series:
    return panel[name] if name in panel.columns else pd.Series(np.nan, index=panel.index)


def mart_macro_monthly(observations: pd.DataFrame, registry: Registry) -> pd.DataFrame:
    p = to_monthly(observations, registry)
    m = pd.DataFrame(index=p.index)

    # Rates
    for name in ("policy_rate", "corra", "tbill_3m", "tbill_6m", "bond_2y", "bond_5y", "bond_10y", "us_fed_funds"):
        m[name] = _col(p, name)
    m["term_spread_10y_2y"] = m["bond_10y"] - m["bond_2y"]
    m["market_implied_6m_bp"] = (m["tbill_6m"] - m["policy_rate"]) * 100
    m["ca_us_policy_gap"] = m["policy_rate"] - m["us_fed_funds"]
    m["ca_us_10y_spread"] = m["bond_10y"] - _col(p, "us_treasury_10y")

    # Inflation (reference month = the month the price change describes)
    m["cpi_headline_yoy"] = _yoy(_col(p, "cpi_all_items_index"))
    for core in ("cpi_trim", "cpi_median", "cpi_common"):
        m[core] = _col(p, core)
    cores = m[["cpi_trim", "cpi_median", "cpi_common"]]
    m["core_avg"] = cores.mean(axis=1, skipna=False)
    m["core_range"] = cores.max(axis=1, skipna=False) - cores.min(axis=1, skipna=False)
    m["headline_minus_core"] = m["cpi_headline_yoy"] - m["core_avg"]
    m["inflation_target"] = INFLATION_TARGET
    m["target_low"], m["target_high"] = TARGET_BAND
    m["infl_exp_consensus_2_3y"] = _col(p, "infl_exp_consensus_2_3y").ffill(limit=2)
    m["bos_firms_infl_above_3"] = _col(p, "bos_firms_infl_above_3").ffill(limit=2)

    # Labour and activity
    m["unemployment_rate"] = _col(p, "unemployment_rate")
    # Trend = 10-year rolling MEDIAN, not mean: the 2020 spike (14.2%) pulled the 10-year mean up by
    # ~0.3 pt (6.57% vs 6.30% median in Sep 2026), which made today's 6.5% look like a tight market.
    m["unemployment_trend_10y"] = m["unemployment_rate"].rolling(120, min_periods=60).median()
    m["unemployment_gap"] = m["unemployment_rate"] - m["unemployment_trend_10y"]
    m["employment_yoy"] = _yoy(_col(p, "employment"))
    m["gdp_yoy"] = _yoy(_col(p, "gdp_monthly"))
    m["wage_growth_lfs"] = _col(p, "wage_growth_lfs")

    # Taylor rule: i = r* + π + 0.5 (π − 2) + 0.5 · output gap, output gap ≈ −Okun · unemployment gap
    m["real_policy_rate"] = m["policy_rate"] - m["core_avg"]
    m["taylor_rule_rate"] = (
        NEUTRAL_REAL_RATE
        + m["core_avg"]
        + 0.5 * (m["core_avg"] - INFLATION_TARGET)
        - 0.5 * OKUN_COEFFICIENT * m["unemployment_gap"]
    )
    m["taylor_gap"] = m["policy_rate"] - m["taylor_rule_rate"]

    # Oil shock, in Canadian dollars
    m["wti_usd"] = _col(p, "wti_oil")
    m["usdcad"] = _col(p, "usdcad")
    m["wti_cad"] = m["wti_usd"] * m["usdcad"]
    m["wti_usd_yoy"] = _yoy(m["wti_usd"])
    m["wti_cad_yoy"] = _yoy(m["wti_cad"])
    m["bcpi_energy_yoy"] = _yoy(_col(p, "bcpi_energy"))
    m["bcpi_ex_energy_yoy"] = _yoy(_col(p, "bcpi_ex_energy"))

    # Tariffs: announced vs actually paid
    for name in ("us_tariff_rate_on_canada", "us_tariff_rate_on_mexico", "us_tariff_rate_on_china"):
        m[name] = _col(p, name)
    m["canada_tariff_advantage_vs_china"] = m["us_tariff_rate_on_china"] - m["us_tariff_rate_on_canada"]
    m["us_import_prices_from_canada_yoy"] = _yoy(_col(p, "us_import_prices_from_canada"))
    m["trade_policy_uncertainty"] = _col(p, "trade_policy_uncertainty")
    m["usdcad_yoy"] = _yoy(m["usdcad"])

    # Mortgage renewal shock: a 5-year term renewing today was signed 60 months ago
    m["mortgage_5y"] = _col(p, "mortgage_5y")
    m["mortgage_5y_at_origination"] = m["mortgage_5y"].shift(60)
    m["renewal_rate_change"] = m["mortgage_5y"] - m["mortgage_5y_at_origination"]
    m["mortgage_spread_5y"] = m["mortgage_5y"] - m["bond_5y"]

    m = m.loc[m.index >= BI_START.to_period("M")]
    out = m.reset_index()
    out["month"] = out["month"].dt.to_timestamp()
    out.insert(1, "is_partial_month", out["month"].dt.to_period("M") >= pd.Timestamp.now().to_period("M"))
    return out


def mart_energy_passthrough(macro: pd.DataFrame, max_lag: int = 18, since: str = "2000-01-01") -> pd.DataFrame:
    """Correlation between energy-price inflation in month t and inflation in month t + k.

    Headline CPI reacts within weeks (gasoline); core inflation only moves if the shock spreads
    to other prices (second-round effects), which shows up as a correlation peaking months later.
    """
    sample = macro[macro["month"] >= pd.Timestamp(since)].set_index("month")
    energy = sample["bcpi_energy_yoy"]
    rows = []
    for k in range(max_lag + 1):
        rows.append(
            {
                "lag_months": k,
                "corr_headline": energy.corr(sample["cpi_headline_yoy"].shift(-k)),
                "corr_core": energy.corr(sample["core_avg"].shift(-k)),
                "n_months": int(pd.concat([energy, sample["core_avg"].shift(-k)], axis=1).dropna().shape[0]),
            }
        )
    return pd.DataFrame(rows)


@dataclass(frozen=True)
class SignalRule:
    indicator: str
    column: str
    unit: str
    hawkish_above: float | None
    dovish_below: float | None
    rationale: str
    reverse: bool = False  # True: a LOW value is hawkish (e.g. unemployment gap, Taylor gap)


SIGNAL_RULES = [
    SignalRule(
        "Core inflation (avg of trim/median/common)",
        "core_avg",
        "%",
        2.5,
        1.5,
        "Core inflation is what the Bank targets in practice.",
    ),
    SignalRule(
        "Headline CPI inflation",
        "cpi_headline_yoy",
        "%",
        3.0,
        1.0,
        "Outside the 1–3% control range the Bank must explain itself.",
    ),
    SignalRule(
        "Inflation expectations, 2–3 years (Consensus)",
        "infl_exp_consensus_2_3y",
        "%",
        2.3,
        1.7,
        "De-anchored expectations are the main reason to react to an energy shock.",
    ),
    SignalRule(
        "Firms expecting inflation above 3% (BOS)",
        "bos_firms_infl_above_3",
        "% of firms",
        30.0,
        15.0,
        "Business price-setting intentions.",
    ),
    SignalRule(
        "Wage growth (LFS)",
        "wage_growth_lfs",
        "%",
        4.0,
        2.5,
        "Wages above ~3.5% are hard to reconcile with 2% inflation.",
    ),
    SignalRule(
        "Unemployment gap vs 10-year median",
        "unemployment_gap",
        "pts",
        -0.3,
        0.3,
        "A tight labour market (negative gap) is inflationary.",
        reverse=True,
    ),
    SignalRule(
        "Oil price in CAD, year over year",
        "wti_cad_yoy",
        "%",
        20.0,
        -20.0,
        "Energy shocks lift headline inflation and can spread.",
    ),
    SignalRule(
        "Market-implied move over 6 months",
        "market_implied_6m_bp",
        "bp",
        15.0,
        -15.0,
        "6-month T-bill minus policy rate: what markets price in.",
    ),
    SignalRule(
        "Policy rate minus Taylor rule",
        "taylor_gap",
        "pts",
        -0.5,
        0.5,
        "Policy below the rule-implied rate argues for hikes.",
        reverse=True,
    ),
]


def mart_policy_signals(macro: pd.DataFrame) -> pd.DataFrame:
    """Latest value of each indicator → +1 hawkish (hike), −1 dovish (cut), 0 neutral."""
    rows = []
    for rule in SIGNAL_RULES:
        series = macro.set_index("month")[rule.column].dropna() if rule.column in macro else pd.Series(dtype=float)
        if series.empty:
            continue
        value, month = float(series.iloc[-1]), series.index[-1]
        if rule.reverse:
            signal = 1 if value < rule.hawkish_above else (-1 if value > rule.dovish_below else 0)
        else:
            signal = 1 if value > rule.hawkish_above else (-1 if value < rule.dovish_below else 0)
        rows.append(
            {
                "indicator": rule.indicator,
                "column": rule.column,
                "latest_value": round(value, 3),
                "unit": rule.unit,
                "reference_month": month,
                "hawkish_threshold": rule.hawkish_above,
                "dovish_threshold": rule.dovish_below,
                "signal": signal,
                "signal_label": {1: "Hawkish (hike)", 0: "Neutral", -1: "Dovish (cut)"}[signal],
                "rationale": rule.rationale,
            }
        )
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- assembly
def build_bi_tables(observations: pd.DataFrame, registry: Registry) -> dict[str, pd.DataFrame]:
    macro = mart_macro_monthly(observations, registry)
    tables = {
        "dim_date": dim_date(),
        "dim_series": dim_series(registry),
        "fact_observations": fact_observations(observations),
        "fact_yield_curve": fact_yield_curve(observations),
        "fact_policy_decisions": fact_policy_decisions(observations),
        "fact_policy_calendar": fact_policy_calendar(),
        "mart_macro_monthly": macro,
        "mart_energy_passthrough": mart_energy_passthrough(macro),
        "mart_policy_signals": mart_policy_signals(macro),
    }
    for name, frame in tables.items():
        float_cols = frame.select_dtypes("float").columns
        frame[float_cols] = frame[float_cols].round(4)
        tables[name] = frame
    return tables


# Columns stored as DATE (not TIMESTAMP) in Unity Catalog, for clean Power BI date relationships.
DATE_COLUMNS = {
    "dim_date": ["date", "month_start"],
    "fact_observations": ["date"],
    "fact_yield_curve": ["date"],
    "fact_policy_decisions": ["date", "announcement_date"],
    "fact_policy_calendar": ["date"],
    "mart_macro_monthly": ["month"],
    "mart_policy_signals": ["reference_month"],
}


def write_local(tables: dict[str, pd.DataFrame]) -> Path:
    """Parquet + CSV per table in data/gold/bi/ — Power BI can read this folder without Databricks."""
    out = bi_dir()
    out.mkdir(parents=True, exist_ok=True)
    for name, frame in tables.items():
        frame.to_parquet(out / f"{name}.parquet", index=False)
        frame.to_csv(out / f"{name}.csv", index=False, date_format="%Y-%m-%d")
    return out
