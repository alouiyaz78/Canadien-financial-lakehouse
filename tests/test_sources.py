import pandas as pd

from cfl.config import load_registry
from cfl.sources import fred, statcan, valet
from tests.conftest import fred_payload, spec, statcan_payload, valet_payload


def test_valet_parses_strings_and_missing_values():
    payload = valet_payload("CBC20210", [("2026-10-27", "2.25"), ("2026-10-28", "2.50"), ("2026-10-29", None)])
    frame = valet.parse(payload, spec(source_id="CBC20210"))
    assert frame["value"].tolist()[:2] == [2.25, 2.50]
    assert pd.isna(frame["value"].iloc[2])
    assert frame["date"].iloc[1] == pd.Timestamp("2026-10-28")


def test_valet_parses_quarter_dates():
    payload = valet_payload("Q", [("2025Q3", "2.1"), ("2025-Q4", "2.2")])
    frame = valet.parse(payload, spec(source_id="Q", frequency="Q"))
    assert frame["date"].tolist() == [pd.Timestamp("2025-07-01"), pd.Timestamp("2025-10-01")]


def test_statcan_parses_vector_points():
    payload = statcan_payload(2062815, [("2026-08-01", 7.0), ("2026-09-01", 7.1)])
    frame = statcan.parse(payload, spec(source="statcan", source_id="2062815"))
    assert frame["value"].tolist() == [7.0, 7.1]


def test_statcan_failure_status_raises():
    import pytest

    with pytest.raises(RuntimeError):
        statcan.parse(b'[{"status": "FAILED", "object": "Vector not found"}]', spec(source="statcan", source_id="1"))


def test_fred_handles_dot_as_missing_and_old_header():
    frame = fred.parse(
        fred_payload("FEDFUNDS", [("2026-08-01", "4.33"), ("2026-09-01", ".")]), spec(source_id="FEDFUNDS")
    )
    assert frame["value"].iloc[0] == 4.33 and pd.isna(frame["value"].iloc[1])
    old = fred.parse(b"DATE,GS10\n2026-01-01,4.1\n", spec(source_id="GS10"))
    assert old["value"].iloc[0] == 4.1


def test_registry_is_valid_and_covers_both_problems():
    registry = load_registry()
    names = {s.name for s in registry.series}
    assert {
        "policy_rate",
        "cpi_trim",
        "cpi_median",
        "unemployment_rate",
        "bcpi_energy",
        "us_tariff_rate_on_canada",
    } <= names
    assert {s.source for s in registry.series} == {"valet", "statcan", "fred", "census"}


def test_census_effective_tariff_rate():
    from cfl.sources import census

    payload = (
        b'[["CTY_NAME","GEN_VAL_MO","CAL_DUT_MO","CTY_CODE","time"],'
        b'["CANADA","30000000000","300000000","1220","2025-04"],'
        b'["CANADA","0","0","1220","2025-05"]]'
    )
    frame = census.parse(payload, spec(source="census", source_id="1220"))
    assert frame["value"].iloc[0] == 1.0
    assert frame["date"].iloc[0] == pd.Timestamp("2025-04-01")
    assert pd.isna(frame["value"].iloc[1])
