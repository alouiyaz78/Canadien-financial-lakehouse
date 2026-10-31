import pandas as pd

from cfl.config import Registry
from cfl.freshness import freshness_report
from tests.conftest import spec


def test_freshness_flags_late_and_missing_series():
    registry = Registry(
        series=[
            spec(name="daily_rate", frequency="D"),
            spec(name="cpi", frequency="M", release_lag_months=1),
            spec(name="gdp", frequency="M", release_lag_months=2),
            spec(name="never_loaded", frequency="M"),
        ]
    )
    today = pd.Timestamp("2026-10-29")
    last = pd.Series(
        {
            "daily_rate": "2026-10-10",  # 19 days old > 7 → late
            "cpi": "2026-09-01",  # September CPI, published in October → ok
            "gdp": "2026-07-01",  # July GDP, published end of September → ok (lag 2)
        }
    )
    report = freshness_report(last, registry, today).set_index("name")
    assert report.loc["daily_rate", "status"] == "late"
    assert report.loc["cpi", "status"] == "ok"
    assert report.loc["gdp", "status"] == "ok"
    assert report.loc["never_loaded", "status"] == "missing"
    assert report.index[0] == "never_loaded"  # worst first


def test_explicit_stale_after_days_overrides_default():
    assert spec(frequency="M", stale_after_days=10).max_age_days() == 10
    assert spec(frequency="M", release_lag_months=1).max_age_days() == 100


def test_discontinued_series_is_retired_not_late():
    registry = Registry(series=[spec(name="legacy_fx", frequency="D", discontinued=True)])
    report = freshness_report(pd.Series({"legacy_fx": "2017-04-28"}), registry, pd.Timestamp("2026-10-30"))
    assert report.set_index("name").loc["legacy_fx", "status"] == "retired"
