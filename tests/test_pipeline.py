"""End-to-end test: Bronze → Silver → Gold on synthetic payloads, with the timing rules checked."""

import numpy as np
import pandas as pd
import pytest

from cfl import bronze, gold, silver
from cfl.config import Registry
from cfl.sources.base import RawPayload
from tests.conftest import monthly_dates, spec, statcan_payload, valet_payload

N_MONTHS = 48


@pytest.fixture
def registry():
    return Registry(
        series=[
            spec(name="policy_rate", source_id="CBC20210", frequency="D", monthly_agg="last"),
            spec(name="cpi_trim", source_id="CPI_TRIM", release_lag_months=1),
            spec(name="cpi_all_items_index", source="statcan", source_id="41690973", release_lag_months=1),
            spec(name="infl_exp", source_id="EXPQ", frequency="Q", release_lag_months=1),
        ]
    )


@pytest.fixture
def fake_payloads(registry):
    months = monthly_dates("2022-01-01", N_MONTHS)
    # Policy rate: daily points; hikes of 25 bp on the 15th of months 10 and 30.
    days = pd.date_range("2022-01-01", periods=N_MONTHS * 31, freq="D")
    rate = np.where(days >= pd.Timestamp(months[10]) + pd.Timedelta(days=14), 2.25, 2.0)
    rate = np.where(days >= pd.Timestamp(months[30]) + pd.Timedelta(days=14), 2.5, rate)
    quarters = [f"{y}Q{q}" for y in range(2022, 2026) for q in range(1, 5)]
    return {
        "policy_rate": valet_payload(
            "CBC20210", [(d.strftime("%Y-%m-%d"), f"{r:.2f}") for d, r in zip(days, rate, strict=True)]
        ),
        "cpi_trim": valet_payload("CPI_TRIM", [(m, f"{i / 10:.1f}") for i, m in enumerate(months)]),
        "cpi_all_items_index": statcan_payload(41690973, [(m, 100 + i) for i, m in enumerate(months)]),
        "infl_exp": valet_payload("EXPQ", [(q, f"{i}") for i, q in enumerate(quarters)]),
    }


@pytest.fixture
def lake(tmp_lake, registry, fake_payloads, monkeypatch):
    def fake_fetch(s, session):
        ext = "json"
        return RawPayload(content=fake_payloads[s.name], url=f"fake://{s.name}", extension=ext)

    from cfl.sources import statcan, valet

    monkeypatch.setattr(valet, "fetch", fake_fetch)
    monkeypatch.setattr(statcan, "fetch", fake_fetch)

    results = bronze.ingest(registry.series)
    assert all(r.ok for r in results)
    observations, report = silver.build_silver(registry.series)
    table = gold.build_gold(observations, registry)
    return {"observations": observations, "report": report, "table": table, "root": tmp_lake}


def test_bronze_writes_raw_files_and_manifest(lake):
    root = lake["root"]
    assert len(list((root / "bronze").rglob("*.json"))) == 4
    manifest = bronze.read_manifest()
    assert len(manifest) == 4 and set(manifest["status"]) == {"ok"}
    assert len(list((root / "bronze" / "_manifest").glob("run_*.jsonl"))) == 1


def test_silver_quality_report(lake):
    report = lake["report"].set_index("name")
    assert report.loc["cpi_trim", "n_clean"] == N_MONTHS
    assert (lake["root"] / "silver" / "observations" / "_delta_log").exists()


def test_gold_shifts_features_by_release_lag(lake):
    table = lake["table"]
    # CPI-trim for reference month i is i/10, published one month later.
    row = table.loc[pd.Period("2022-06", "M")]
    assert row["cpi_trim"] == pytest.approx(0.4)  # May value (index 4) visible at end of June


def test_gold_targets_look_forward_from_reference_values(lake):
    table = lake["table"]
    row = table.loc[pd.Period("2022-06", "M")]
    assert row["y_cpi_trim_h3"] == pytest.approx(0.8)  # September 2022 = index 8
    assert row["y_cpi_trim_h12"] == pytest.approx(1.7)


def test_no_target_leaks_into_features(lake):
    table = lake["table"]
    features = [c for c in table.columns if not c.startswith("y_") and c != "is_partial_month"]
    for h in (3, 6, 12):
        target = table[f"y_cpi_trim_h{h}"]
        for col in features:
            same = (table[col] - target).abs() < 1e-12
            assert not same.dropna().all(), f"{col} equals target y_cpi_trim_h{h}"


def test_policy_direction_targets(lake):
    table = lake["table"]
    hike_month = pd.Period("2022-11", "M")  # months[10]
    assert table.loc[hike_month - 1, "y_policy_dir_1m"] == 1
    assert table.loc[hike_month - 1, "y_policy_change_1m"] == pytest.approx(0.25)
    assert table.loc[hike_month, "y_policy_dir_1m"] == 0
    assert table.loc[hike_month - 3, "y_policy_dir_3m"] == 1
    assert table.loc[hike_month - 4, "y_policy_dir_3m"] == 0
    assert table.loc[hike_month, "policy_rate_chg_1m"] == pytest.approx(0.25)


def test_quarterly_series_is_stamped_on_quarter_end_and_lagged(lake):
    table = lake["table"]
    # 2022Q1 value (0) is stamped on March, published with a 1-month lag → first visible in April.
    assert pd.isna(table.loc[pd.Period("2022-03", "M"), "infl_exp"])
    assert table.loc[pd.Period("2022-04", "M"), "infl_exp"] == 0
    assert table.loc[pd.Period("2022-06", "M"), "infl_exp"] == 0  # carried forward
    assert table.loc[pd.Period("2022-07", "M"), "infl_exp"] == 1  # Q2 value


def test_headline_inflation_derived_from_index(lake):
    table = lake["table"]
    row = table.loc[pd.Period("2023-06", "M")]
    # real-time: index known for May 2023 (i=16) vs May 2022 (i=4)
    assert row["cpi_headline_yoy"] == pytest.approx((116 / 104 - 1) * 100)


def test_gold_files_written(lake):
    out = lake["root"] / "gold"
    assert (out / "model_table_monthly" / "_delta_log").exists()
    dictionary = pd.read_csv(out / "column_dictionary.csv")
    assert set(dictionary["role"]) == {"meta", "feature_raw", "feature_derived", "target"}


def test_gold_is_versioned_and_readable_back(lake, registry):
    from cfl.storage import history

    first = gold.read_gold()
    pd.testing.assert_index_equal(first.index, lake["table"].index)
    gold.build_gold(lake["observations"], registry)  # second run → new Delta version
    versions = history(lake["root"] / "gold" / "model_table_monthly")
    assert versions["version"].tolist() == [0, 1]
    assert gold.read_gold(version=0).shape == first.shape


def test_survey_quarter_stamped_on_first_month():
    reg = Registry(series=[spec(name="survey", source_id="S", frequency="Q", quarter_stamp="start")])
    obs = pd.DataFrame({"name": "survey", "date": pd.to_datetime(["2022-01-01", "2022-04-01"]), "value": [1.0, 2.0]})
    panel = gold.to_monthly(obs, reg)
    assert panel.loc[pd.Period("2022-01", "M"), "survey"] == 1.0
    assert panel.loc[pd.Period("2022-04", "M"), "survey"] == 2.0
