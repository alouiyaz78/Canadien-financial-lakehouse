# Databricks notebook source
# MAGIC %md
# MAGIC # Example · One series end-to-end in pure PySpark
# MAGIC A self-contained reference of the PySpark / Delta commands used in the lakehouse, on one series:
# MAGIC the Bank of Canada **policy rate** (`CBC20210`), from the raw Valet JSON in the Bronze Volume to a
# MAGIC Delta table updated with `MERGE`.
# MAGIC
# MAGIC Run the job (or `01_bronze_ingest` with `source=valet`) once first, so Bronze files exist.
# MAGIC
# MAGIC | Step | PySpark |
# MAGIC |---|---|
# MAGIC | read raw JSON files + file metadata | `spark.read.option("multiLine", True).json(path)`, `_metadata.file_path` |
# MAGIC | flatten a nested array | `F.explode`, struct access `o.CBC20210.v` |
# MAGIC | types | `F.to_date`, `.cast("double")` |
# MAGIC | keep the latest snapshot per date | `Window.partitionBy(...).orderBy(...)`, `F.row_number()` |
# MAGIC | upsert | `DeltaTable.forName(...).merge(...)` |
# MAGIC | monthly aggregation, lag | `F.date_trunc`, `F.max_by`, `F.lag` |

# COMMAND ----------

dbutils.widgets.text("catalog", "workspace")  # noqa: F821
dbutils.widgets.text("schema", "cfl")  # noqa: F821
catalog = dbutils.widgets.get("catalog")  # noqa: F821
schema = dbutils.widgets.get("schema")  # noqa: F821

SERIES_ID = "CBC20210"
BRONZE_PATH = f"/Volumes/{catalog}/{schema}/lake/bronze/valet/policy_rate/"
TARGET = f"{catalog}.{schema}.example_policy_rate_daily"

# COMMAND ----------

# MAGIC %md ## 1. Read the raw Bronze files
# MAGIC Each file is one complete API response (`{"seriesDetail": ..., "observations": [...]}`), so `multiLine`
# MAGIC is required. `_metadata.file_path` tells which snapshot each row comes from.

# COMMAND ----------

from pyspark.sql import Window  # noqa: E402
from pyspark.sql import functions as F  # noqa: E402

raw = (
    spark.read.option("multiLine", True)  # noqa: F821
    .json(BRONZE_PATH)
    .select("observations", F.col("_metadata.file_path").alias("snapshot_file"))
)
raw.printSchema()

# COMMAND ----------

# MAGIC %md ## 2. Flatten, type, deduplicate

# COMMAND ----------

observations = (
    raw.select("snapshot_file", F.explode("observations").alias("o"))
    .select(
        F.to_date(F.col("o.d")).alias("date"),
        F.col(f"o.{SERIES_ID}.v").cast("double").alias("value"),  # Valet sends values as strings
        "snapshot_file",
    )
    .filter(F.col("value").isNotNull())
)

# Several snapshots contain the same date: keep the value from the most recent snapshot.
latest_snapshot_first = Window.partitionBy("date").orderBy(F.col("snapshot_file").desc())
daily = (
    observations.withColumn("rn", F.row_number().over(latest_snapshot_first))
    .filter("rn = 1")
    .drop("rn")
    .withColumn("series_id", F.lit(SERIES_ID))
    .withColumn("updated_at", F.current_timestamp())
)
display(daily.orderBy(F.col("date").desc()).limit(10))  # noqa: F821

# COMMAND ----------

# MAGIC %md ## 3. Write with MERGE (idempotent upsert)
# MAGIC First run creates the table; later runs only touch dates that are new or whose value changed.

# COMMAND ----------

from delta.tables import DeltaTable  # noqa: E402

if not spark.catalog.tableExists(TARGET):  # noqa: F821
    daily.write.saveAsTable(TARGET)
else:
    (
        DeltaTable.forName(spark, TARGET)  # noqa: F821
        .alias("t")
        .merge(daily.alias("s"), "t.date = s.date")
        .whenMatchedUpdate(
            condition="NOT (t.value <=> s.value)",
            set={"value": "s.value", "snapshot_file": "s.snapshot_file", "updated_at": "s.updated_at"},
        )
        .whenNotMatchedInsertAll()
        .execute()
    )

display(spark.sql(f"DESCRIBE HISTORY {TARGET}").select("version", "operation", "operationMetrics"))  # noqa: F821

# COMMAND ----------

# MAGIC %md ## 4. Analysis: month-end rate and every decision since 2001

# COMMAND ----------

monthly = (
    spark.table(TARGET)  # noqa: F821
    .groupBy(F.date_trunc("month", "date").cast("date").alias("month"))
    .agg(F.max_by("value", "date").alias("policy_rate"))  # last value of the month
)

decisions = (
    spark.table(TARGET)  # noqa: F821
    .withColumn("previous", F.lag("value").over(Window.orderBy("date")))
    .filter(F.col("value") != F.col("previous"))
    .select("date", "previous", "value", (F.col("value") - F.col("previous")).alias("change_pts"))
    .orderBy(F.col("date").desc())
)
display(decisions)  # noqa: F821

# COMMAND ----------

# MAGIC %md ## 5. Same question in SQL

# COMMAND ----------

display(  # noqa: F821
    spark.sql(  # noqa: F821
        f"""
        SELECT year(date) AS year,
               count_if(change_pts > 0) AS hikes,
               count_if(change_pts < 0) AS cuts,
               round(sum(change_pts), 2) AS net_change_pts
        FROM (
          SELECT date, value - lag(value) OVER (ORDER BY date) AS change_pts
          FROM {TARGET}
        )
        WHERE change_pts <> 0
        GROUP BY year(date)
        ORDER BY year DESC
        """
    )
)
