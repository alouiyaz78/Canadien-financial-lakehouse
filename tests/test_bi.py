"""BI marts: reference dates, Taylor rule, decisions/cycles, pass-through lags, signals."""

import numpy as np
import pandas as pd
import pytest

from cfl import bi
from cfl.config import Registry
from tests.conftest import spec


def _obs(name: str, dates, values) -> pd.DataFrame:
    return pd.DataFrame({"name": name, "date": pd.to_datetime(list(dates)), "value": list(values)})


@pytest.fixture
def registry():
    return Registry(
        series=[
            spec(name="policy_rate", source_id="CBC20210", frequency="D"),
            spec(name="tbill_6m", source_id="TB6", frequency="D", monthly_agg="mean"),
            spec(name="bond_2y", source_id="B2", frequency="D", monthly_agg="mean"),
            spec(name="bond_10y", source_id="B10", frequency="D", monthly_agg="mean"),
            spec(name="cpi_trim", source_id="T", release_lag_months=1),
            spec(name="cpi_median", source_id="M", release_lag_months=1),
            spec(name="cpi_common", source_id="C", release_lag_months=1),
            spec(name="cpi_all_items_index", source="statcan", source_id="1", release_lag_months=1),
            spec(name="unemployment_rate", source="statcan", source_id="2", release_lag_months=1),
            spec(name="bcpi_energy", source_id="E", release_lag_months=1),
            spec(name="wti_oil", source="fred", source_id="WTI"),
            spec(name="usdcad", source_id="FX", frequency="D", monthly_agg="mean"),
            spec(name="mortgage_5y", source_id="MTG", frequency="W", monthly_agg="mean"),
        ]
    )


@pytest.fixture
def observations():
    months = pd.date_range("2005-01-01", "2026-09-01", freq="MS")
    n = len(months)
    rng = np.random.default_rng(1)
    days = pd.date_range("2005-01-01", "2026-10-29", freq="D")
    rate = pd.Series(1.0, index=days)
    rate[days >= "2010-06-01"] = 1.25  # hike
    rate[days >= "2010-09-08"] = 1.50  # hike (same cycle)
    rate[days >= "2015-01-21"] = 1.25  # cut → new cycle
    rate[days >= "2026-10-28"] = 1.50  # hike → new cycle
    energy = 100 * np.exp(np.cumsum(rng.normal(0, 0.05, n)))
    energy_yoy = pd.Series(energy, index=months).pct_change(12) * 100
    # Core inflation follows energy inflation with a 6-month delay.
    core = 2 + 0.05 * energy_yoy.shift(6).fillna(0).to_numpy()
    return pd.concat(
        [
            _obs("policy_rate", days, rate.to_numpy()),
            _obs("tbill_6m", days, rate.to_numpy() + 0.2),
            _obs("bond_2y", days, np.full(len(days), 2.0)),
            _obs("bond_10y", days, np.full(len(days), 3.0)),
            _obs("cpi_trim", months, core),
            _obs("cpi_median", months, core + 0.1),
            _obs("cpi_common", months, core - 0.1),
            _obs("cpi_all_items_index", months, 100 * 1.02 ** (np.arange(n) / 12)),
            _obs("unemployment_rate", months, np.full(n, 6.0)),
            _obs("bcpi_energy", months, energy),
            _obs("wti_oil", months, np.full(n, 80.0)),
            _obs("usdcad", days, np.full(len(days), 1.25)),
            _obs("mortgage_5y", months, np.linspace(5.0, 6.0, n)),
        ],
        ignore_index=True,
    )


@pytest.fixture
def macro(observations, registry):
    return bi.mart_macro_monthly(observations, registry).set_index("month")


def test_bi_mart_keeps_reference_dates(macro):
    # September 2026 CPI-trim is shown in September (the ML table would show it in October).
    assert not np.isnan(macro.loc[pd.Timestamp("2026-09-01"), "cpi_trim"])
    assert macro.index.min() == pd.Timestamp("2005-01-01")


def test_headline_yoy_and_core_statistics(macro):
    row = macro.loc[pd.Timestamp("2020-01-01")]
    assert row["cpi_headline_yoy"] == pytest.approx(2.0, abs=1e-3)
    assert row["core_avg"] == pytest.approx(row["cpi_trim"], abs=1e-6)  # +0.1 and −0.1 cancel out
    assert row["core_range"] == pytest.approx(0.2, abs=1e-6)


def test_taylor_rule(macro):
    row = macro.loc[pd.Timestamp("2020-01-01")]
    expected = bi.NEUTRAL_REAL_RATE + row["core_avg"] + 0.5 * (row["core_avg"] - 2.0) - 0.5 * 2.0 * 0.0
    assert row["unemployment_gap"] == pytest.approx(0.0)
    assert row["taylor_rule_rate"] == pytest.approx(expected, abs=1e-6)
    assert row["taylor_gap"] == pytest.approx(row["policy_rate"] - expected, abs=1e-6)


def test_oil_in_cad_and_market_implied(macro):
    row = macro.loc[pd.Timestamp("2020-01-01")]
    assert row["wti_cad"] == pytest.approx(100.0)
    assert row["market_implied_6m_bp"] == pytest.approx(20.0)
    assert row["term_spread_10y_2y"] == pytest.approx(1.0)


def test_mortgage_renewal_compares_with_rate_60_months_earlier(macro):
    assert macro.loc[pd.Timestamp("2020-01-01"), "mortgage_5y_at_origination"] == pytest.approx(
        macro.loc[pd.Timestamp("2015-01-01"), "mortgage_5y"]
    )
    assert macro.loc[pd.Timestamp("2020-01-01"), "renewal_rate_change"] > 0


def test_policy_decisions_and_cycles(observations):
    decisions = bi.fact_policy_decisions(observations)
    assert decisions["date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2010-06-01",
        "2010-09-08",
        "2015-01-21",
        "2026-10-28",
    ]
    assert decisions["change_bp"].tolist() == [25, 25, -25, 25]
    assert decisions["cycle_id"].tolist() == [1, 1, 2, 3]
    assert decisions["cumulative_cycle_bp"].tolist() == [25, 50, -25, 25]
    # Effective dates are the business day after the announcement (Wed → Thu, Fri → Mon).
    effective_to_announced = dict(zip(decisions["date"], decisions["announcement_date"], strict=True))
    assert effective_to_announced[pd.Timestamp("2026-10-28")] == pd.Timestamp("2026-10-27")
    assert effective_to_announced[pd.Timestamp("2010-06-01")] == pd.Timestamp("2010-05-31")


def test_yield_curve_long_format(observations):
    curve = bi.fact_yield_curve(observations)
    last = curve[curve["date"] == curve["date"].max()].set_index("tenor")
    assert last.loc["Overnight", "yield_pct"] == 1.5 and last.loc["10Y", "yield_pct"] == 3.0
    assert set(curve["tenor_months"]) == {0, 6, 24, 120}


def test_energy_passthrough_peaks_at_true_lag(macro):
    lags = bi.mart_energy_passthrough(macro.reset_index())
    assert lags.loc[lags["corr_core"].idxmax(), "lag_months"] == 6


def test_policy_signals_reverse_rules():
    macro = pd.DataFrame(
        {
            "month": pd.to_datetime(["2026-08-01", "2026-09-01"]),
            "core_avg": [2.0, 2.8],  # > 2.5 → hawkish
            "unemployment_gap": [0.0, 0.6],  # slack (> 0.3) → dovish, reverse rule
            "taylor_gap": [0.0, -1.0],  # policy below rule → hawkish, reverse rule
        }
    )
    signals = bi.mart_policy_signals(macro).set_index("column")
    assert signals.loc["core_avg", "signal"] == 1
    assert signals.loc["unemployment_gap", "signal"] == -1
    assert signals.loc["taylor_gap", "signal"] == 1
    assert len(signals) == 3  # indicators without data are skipped


def test_build_and_write_all_tables(observations, registry, tmp_lake):
    tables = bi.build_bi_tables(observations, registry)
    assert set(tables) == set(bi.DATE_COLUMNS) | {"dim_series", "mart_energy_passthrough"}
    out = bi.write_local(tables)
    assert (out / "mart_macro_monthly.parquet").exists() and (out / "dim_date.csv").exists()
    calendar = tables["fact_policy_calendar"]
    assert pd.Timestamp("2026-12-09") in set(calendar["date"])


def test_unemployment_trend_is_robust_to_a_spike(registry):
    months = pd.date_range("2010-01-01", "2020-12-01", freq="MS")
    rate = np.full(len(months), 6.0)
    rate[-9:-3] = 14.0  # a short pandemic-like spike
    obs = _obs("unemployment_rate", months, rate)
    macro = bi.mart_macro_monthly(obs, registry).set_index("month")
    assert macro.loc[pd.Timestamp("2020-12-01"), "unemployment_trend_10y"] == pytest.approx(6.0)
