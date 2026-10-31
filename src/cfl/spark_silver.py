"""Silver layer in PySpark: incremental MERGE into a Unity Catalog Delta table.

Used by databricks/notebooks/02_silver_transform.py. Parsing the four raw formats reuses the
pure-Python parsers (one source of truth, unit-tested offline); everything from the parsed rows
onwards is Spark:

    to_updates()        pandas rows → typed Spark DataFrame, deduplicated with a window
    merge_into_silver() Delta MERGE keyed on (name, date): update changed values, insert new
                        dates, delete dates that disappeared from the source (revisions)
    quality_report()    per-series coverage / gaps / last value, computed with Spark aggregates
"""

from __future__ import annotations

from typing import Any

import pandas as pd

SILVER_COLUMNS = ["name", "source", "source_id", "frequency", "date", "value"]


def silver_schema():
    from pyspark.sql import types as T

    return T.StructType(
        [
            T.StructField("name", T.StringType(), nullable=False),
            T.StructField("source", T.StringType(), nullable=False),
            T.StructField("source_id", T.StringType(), nullable=False),
            T.StructField("frequency", T.StringType(), nullable=False),
            T.StructField("date", T.DateType(), nullable=False),
            T.StructField("value", T.DoubleType(), nullable=True),
        ]
    )


def nan_to_null(sdf):
    """pandas missing values arrive in Spark as NaN; SQL expects NULL (NaN > every number, counts as a value)."""
    from pyspark.sql import functions as F

    doubles = [name for name, dtype in sdf.dtypes if dtype in ("double", "float")]
    return sdf.select(
        *[F.nanvl(F.col(c), F.lit(None).cast("double")).alias(c) if c in doubles else F.col(c) for c in sdf.columns]
    )


def to_updates(spark: Any, observations: pd.DataFrame, run_id: str):
    """Typed Spark DataFrame of the parsed rows, one row per (name, date), with lineage columns."""
    from pyspark.sql import Window
    from pyspark.sql import functions as F

    rows = observations[SILVER_COLUMNS].copy()
    rows["date"] = pd.to_datetime(rows["date"]).dt.date
    rows["value"] = rows["value"].astype(float)
    for col in ("name", "source", "source_id", "frequency"):
        rows[col] = rows[col].astype(object)

    updates = (
        nan_to_null(spark.createDataFrame(rows, schema=silver_schema()))
        .withColumn("run_id", F.lit(run_id))
        .withColumn("updated_at", F.current_timestamp())
    )
    # Defensive deduplication: keep one row per (name, date).
    latest_first = Window.partitionBy("name", "date").orderBy(F.col("updated_at").desc(), F.col("value").desc())
    return updates.withColumn("_rn", F.row_number().over(latest_first)).filter(F.col("_rn") == 1).drop("_rn")


def merge_into_silver(spark: Any, updates, table: str, series_names: list[str]) -> None:
    """Upsert ``updates`` into ``table`` for the given series only.

    * same (name, date), different value → UPDATE (a revision)
    * new (name, date)                    → INSERT (a new observation)
    * (name, date) gone from the source   → DELETE, restricted to the series being merged
    Unchanged rows are not rewritten, so ``updated_at`` tells exactly what each run changed.
    """
    from delta.tables import DeltaTable
    from pyspark.sql import functions as F

    (
        DeltaTable.forName(spark, table)
        .alias("t")
        .merge(updates.alias("s"), "t.name = s.name AND t.date = s.date")
        .whenMatchedUpdate(
            condition="NOT (t.value <=> s.value)",  # null-safe comparison
            set={"value": "s.value", "run_id": "s.run_id", "updated_at": "s.updated_at"},
        )
        .whenNotMatchedInsertAll()
        .whenNotMatchedBySourceDelete(condition=F.col("t.name").isin(series_names))
        .execute()
    )


def overwrite_silver(updates, table: str) -> None:
    """Full refresh: replace the whole table (first run, schema change or ``full_refresh=true``)."""
    updates.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(table)


def quality_report(observations_sdf):
    """Per-series data quality, computed in Spark from the Silver table."""
    from pyspark.sql import Window
    from pyspark.sql import functions as F

    by_series = Window.partitionBy("name").orderBy("date")
    return (
        observations_sdf.withColumn("gap_days", F.datediff("date", F.lag("date").over(by_series)))
        .groupBy("name", "source", "source_id", "frequency")
        .agg(
            F.min("date").alias("first_date"),
            F.max("date").alias("last_date"),
            F.count("*").alias("n_obs"),
            F.sum(F.col("value").isNull().cast("int")).alias("n_null_values"),
            F.max("gap_days").alias("max_gap_days"),
            F.max_by("value", "date").alias("last_value"),
            F.max("updated_at").alias("last_updated_at"),
        )
        .orderBy("source", "name")
    )
