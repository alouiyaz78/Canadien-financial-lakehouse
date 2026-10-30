"""PySpark code paths, run on a local Spark session (skipped when pyspark is not installed).

The Delta MERGE itself needs Delta Lake jars and is exercised on Databricks; everything around it
(typing, deduplication, aggregates, raw JSON parsing used in the example notebook) is tested here.
"""

import datetime as dt
import json

import pandas as pd
import pytest

pyspark = pytest.importorskip("pyspark")

from pyspark.sql import SparkSession, Window  # noqa: E402
from pyspark.sql import functions as F  # noqa: E402

from cfl import databricks as cfl_dbx  # noqa: E402
from cfl import gold, spark_silver  # noqa: E402
from tests.test_pipeline import fake_payloads, lake, registry  # noqa: E402, F401 — pytest fixtures


@pytest.fixture(scope="module")
def spark(tmp_path_factory):
    session = (
        SparkSession.builder.master("local[1]")
        .appName("cfl-tests")
        .config("spark.sql.shuffle.partitions", "1")
        .config("spark.ui.enabled", "false")
        .config("spark.sql.warehouse.dir", str(tmp_path_factory.mktemp("warehouse")))
        .getOrCreate()
    )
    yield session
    session.stop()


def _observations():
    return pd.DataFrame(
        {
            "name": ["policy_rate"] * 3 + ["cpi_trim"] * 3,
            "source": ["valet"] * 6,
            "source_id": ["CBC20210"] * 3 + ["CPI_TRIM"] * 3,
            "frequency": ["D"] * 3 + ["M"] * 3,
            "date": pd.to_datetime(
                ["2026-10-27", "2026-10-28", "2026-10-28", "2026-07-01", "2026-08-01", "2026-10-01"]
            ),
            "value": [2.25, 2.5, 2.5, 2.0, None, 1.8],
        }
    )


def test_to_updates_types_and_dedupes(spark):
    updates = spark_silver.to_updates(spark, _observations(), run_id="r1")
    assert dict(updates.dtypes)["date"] == "date" and dict(updates.dtypes)["value"] == "double"
    assert updates.count() == 5  # duplicate (policy_rate, 2026-10-28) removed
    assert {r.run_id for r in updates.select("run_id").collect()} == {"r1"}


def test_quality_report_aggregates(spark):
    silver = spark_silver.to_updates(spark, _observations(), run_id="r1")
    report = {r.name: r for r in spark_silver.quality_report(silver).collect()}
    cpi = report["cpi_trim"]
    assert cpi.first_date == dt.date(2026, 7, 1) and cpi.last_date == dt.date(2026, 10, 1)
    assert cpi.n_obs == 3 and cpi.n_null_values == 1 and cpi.max_gap_days == 61
    assert cpi.last_value == 1.8
    assert report["policy_rate"].last_value == 2.5


def test_example_notebook_valet_json_logic(spark, tmp_path):
    """Same transformations as databricks/notebooks/examples/pyspark_valet_policy_rate.py."""
    old = {"observations": [{"d": "2026-10-27", "CBC20210": {"v": "2.25"}}]}
    new = {
        "observations": [
            {"d": "2026-10-27", "CBC20210": {"v": "2.25"}},
            {"d": "2026-10-28", "CBC20210": {"v": "2.50"}},
        ]
    }
    (tmp_path / "20261028T120000000000Z.json").write_text(json.dumps(old, indent=2))
    (tmp_path / "20261029T120000000000Z.json").write_text(json.dumps(new, indent=2))

    raw = (
        spark.read.option("multiLine", True)
        .json(str(tmp_path))
        .select("observations", F.col("_metadata.file_path").alias("snapshot_file"))
    )
    observations = raw.select("snapshot_file", F.explode("observations").alias("o")).select(
        F.to_date(F.col("o.d")).alias("date"),
        F.col("o.CBC20210.v").cast("double").alias("value"),
        "snapshot_file",
    )
    latest_first = Window.partitionBy("date").orderBy(F.col("snapshot_file").desc())
    daily = observations.withColumn("rn", F.row_number().over(latest_first)).filter("rn = 1").drop("rn")
    rows = {r.date: r for r in daily.collect()}
    assert len(rows) == 2 and rows[dt.date(2026, 10, 28)].value == 2.5
    assert rows[dt.date(2026, 10, 27)].snapshot_file.endswith("20261029T120000000000Z.json")

    decisions = (
        daily.withColumn("previous", F.lag("value").over(Window.orderBy("date")))
        .filter(F.col("value") != F.col("previous"))
        .select((F.col("value") - F.col("previous")).alias("change_pts"))
        .collect()
    )
    assert [round(r.change_pts, 2) for r in decisions] == [0.25]


def test_publish_gold_and_quality_report_as_tables(spark, lake, registry):  # noqa: F811
    table, dictionary = gold.assemble_gold(lake["observations"], registry)
    flat = gold.to_flat(table)
    cfl_dbx.save_table(spark, flat, "gold_model_table_monthly", comment="It's gold", date_columns=["month"])
    cfl_dbx.save_table(spark, lake["report"], "silver_quality_report")

    gold_sdf = spark.table("gold_model_table_monthly")
    assert dict(gold_sdf.dtypes)["month"] == "date"
    assert gold_sdf.count() == len(flat)
    # Missing values are NULL, not NaN.
    nan_count = gold_sdf.filter(F.isnan("y_cpi_trim_h12")).count()
    null_count = gold_sdf.filter(F.col("y_cpi_trim_h12").isNull()).count()
    assert nan_count == 0 and null_count == int(flat["y_cpi_trim_h12"].isna().sum()) > 0
    assert dict(gold_sdf.dtypes)["is_partial_month"] == "boolean"
    assert spark.table("silver_quality_report").count() == len(lake["report"])


def test_bi_tables_publish_with_date_columns(spark, tmp_lake):  # noqa: F811
    from cfl import bi
    from tests.test_bi import observations as obs_fixture  # noqa: F401
    from tests.test_bi import registry as bi_registry  # noqa: F401

    reg = bi_registry.__wrapped__()
    tables = bi.build_bi_tables(obs_fixture.__wrapped__(), reg)
    for name, frame in tables.items():
        cfl_dbx.save_table(spark, frame, f"bi_{name}", date_columns=bi.DATE_COLUMNS.get(name, ()))
        sdf = spark.table(f"bi_{name}")
        assert sdf.count() == len(frame), name
        for col in bi.DATE_COLUMNS.get(name, ()):
            assert dict(sdf.dtypes)[col] == "date", (name, col)
    signals = spark.table("bi_mart_policy_signals")
    assert signals.filter(F.col("latest_value").isNull()).count() == 0


def test_dictionary_comments_are_valid_spark_sql(spark):
    from cfl import catalog_docs

    spark.sql("CREATE DATABASE IF NOT EXISTS cfl_docs")
    frame = pd.DataFrame(
        {"lag_months": [0, 1], "corr_headline": [0.5, 0.4], "corr_core": [0.1, 0.2], "n_months": [300, 299]}
    )
    spark.createDataFrame(frame).write.mode("overwrite").saveAsTable("cfl_docs.bi_mart_energy_passthrough")
    # catalog "spark_catalog" = the local session catalog; SET TAGS is Databricks-only and is skipped with a warning.
    catalog_docs.apply_to_unity_catalog(spark, "spark_catalog", "cfl_docs", ["bi_mart_energy_passthrough"])
    described = {
        r["col_name"]: r["comment"] for r in spark.sql("DESCRIBE TABLE cfl_docs.bi_mart_energy_passthrough").collect()
    }
    assert described["corr_core"].startswith("Correlation with core inflation")
