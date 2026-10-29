"""The Databricks glue, tested with a fake Spark session (no cluster needed)."""

import pandas as pd

from cfl import databricks as cfl_dbx
from cfl import gold
from tests.test_pipeline import fake_payloads, lake, registry  # noqa: F401 — pytest fixtures


class FakeWriter:
    def __init__(self, store, frame):
        self.store, self.frame, self.options = store, frame, {}

    def mode(self, mode):
        self.options["mode"] = mode
        return self

    def option(self, key, value):
        self.options[key] = value
        return self

    def saveAsTable(self, name):  # noqa: N802 — Spark API name
        self.store["tables"][name] = (self.frame, dict(self.options))


class FakeDataFrame:
    def __init__(self, store, frame):
        self.write = FakeWriter(store, frame)


class FakeSpark:
    def __init__(self):
        self.store = {"tables": {}, "sql": []}

    def createDataFrame(self, frame):  # noqa: N802 — Spark API name
        return FakeDataFrame(self.store, frame)

    def sql(self, statement):
        self.store["sql"].append(statement)


def _is_spark_friendly(frame: pd.DataFrame) -> bool:
    return all(
        pd.api.types.is_numeric_dtype(t) or pd.api.types.is_datetime64_dtype(t) or pd.api.types.is_object_dtype(t)
        for t in frame.dtypes
    )


def test_configure_points_lake_to_volume(monkeypatch):
    monkeypatch.delenv("CENSUS_API_KEY", raising=False)

    class Secrets:
        def get(self, scope, key):
            assert (scope, key) == ("cfl", "census_api_key")
            return "secret-key"

    class DbUtils:
        secrets = Secrets()

    lake_root = cfl_dbx.configure("workspace", "cfl", DbUtils())
    import os

    assert lake_root == "/Volumes/workspace/cfl/lake" == os.environ["CFL_DATA_DIR"]
    assert os.environ["CENSUS_API_KEY"] == "secret-key"


def test_gold_and_silver_publish_to_unity_catalog(lake, registry):  # noqa: F811
    spark = FakeSpark()
    table, dictionary = gold.assemble_gold(lake["observations"], registry)
    cfl_dbx.save_table(spark, gold.to_flat(table), "workspace.cfl.gold_model_table_monthly", comment="It's gold")
    cfl_dbx.save_table(spark, lake["report"], "workspace.cfl.silver_quality_report")
    cfl_dbx.save_column_comments(spark, "workspace.cfl.gold_model_table_monthly", dictionary)

    written, options = spark.store["tables"]["workspace.cfl.gold_model_table_monthly"]
    assert options == {"mode": "overwrite", "overwriteSchema": "true"}
    assert "month" in written.columns and written["month"].iloc[0] == pd.Timestamp("2022-01-01")
    assert _is_spark_friendly(written)
    assert _is_spark_friendly(spark.store["tables"]["workspace.cfl.silver_quality_report"][0])
    assert "It''s gold" in spark.store["sql"][0]  # quotes escaped in SQL comments
    assert sum("ALTER COLUMN" in s for s in spark.store["sql"]) == len(dictionary)
