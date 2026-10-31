# Databricks notebook source
# MAGIC %md
# MAGIC # 02 · Silver — incremental MERGE (PySpark + Delta)
# MAGIC Only the series that **changed in this run** are parsed and merged into `silver_observations`
# MAGIC (keyed on `name`, `date`):
# MAGIC
# MAGIC * new dates → **INSERT**, revised values → **UPDATE**, dates removed at the source → **DELETE**;
# MAGIC * untouched rows keep their `updated_at`, so each run's effect is auditable (`DESCRIBE HISTORY`).
# MAGIC
# MAGIC `full_refresh=true` (or a missing table) rebuilds everything. The quality report is then recomputed
# MAGIC with Spark aggregates from the Silver table.

# COMMAND ----------

# MAGIC %pip install -q "pydantic>=2.6" "pyyaml>=6"

# COMMAND ----------

dbutils.library.restartPython()  # noqa: F821

# COMMAND ----------

import pathlib
import sys

WIDGETS = [('catalog', 'workspace'), ('schema', 'cfl'), ('run_id', 'manual'), ('full_refresh', 'false')]
for name, default in WIDGETS:
    dbutils.widgets.text(name, default)  # noqa: F821
params = {name: dbutils.widgets.get(name) for name, _ in WIDGETS}  # noqa: F821
catalog, schema = params["catalog"], params["schema"]

# The notebook lives in <repo>/databricks/notebooks: put <repo>/src on the import path.
REPO_ROOT = pathlib.Path.cwd().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))


from cfl import bronze, silver, spark_silver  # noqa: E402
from cfl import databricks as cfl_dbx  # noqa: E402
from cfl.config import load_registry  # noqa: E402

cfl_dbx.configure(catalog, schema, dbutils)  # noqa: F821
registry = load_registry()
target = f"{catalog}.{schema}.silver_observations"

# COMMAND ----------

# MAGIC %md ## Which series to process?

# COMMAND ----------

table_ok = spark.catalog.tableExists(target) and "updated_at" in spark.table(target).columns  # noqa: F821
full_refresh = params["full_refresh"].lower() == "true" or not table_ok

manifest = bronze.read_manifest()
this_run = manifest[(manifest["run_id"].astype(str) == params["run_id"]) & manifest["changed"].fillna(False).astype(bool)]
changed_names = set(this_run["name"])

specs = registry.series if full_refresh else [s for s in registry.series if s.name in changed_names]
print(f"full_refresh={full_refresh}; {len(specs)} series to process: {[s.name for s in specs]}")
if not specs:
    dbutils.notebook.exit("nothing changed")  # noqa: F821

# COMMAND ----------

# MAGIC %md ## Parse Bronze → typed Spark DataFrame → MERGE

# COMMAND ----------

observations, _ = silver.assemble_silver(specs)
updates = spark_silver.to_updates(spark, observations, run_id=params["run_id"])  # noqa: F821
updates.printSchema()

if full_refresh:
    spark_silver.overwrite_silver(updates, target)
else:
    spark_silver.merge_into_silver(spark, updates, target, [s.name for s in specs])  # noqa: F821

spark.sql(  # noqa: F821
    f"COMMENT ON TABLE {target} IS 'All series in long format (name, date, value). "
    "Incrementally merged from Bronze; run_id/updated_at show which run last changed each row.'"
)

# COMMAND ----------

# What did this run do? (numTargetRowsInserted / Updated / Deleted)
display(  # noqa: F821
    spark.sql(f"DESCRIBE HISTORY {target} LIMIT 1").select("version", "timestamp", "operation", "operationMetrics")  # noqa: F821
)

# COMMAND ----------

# MAGIC %md ## Quality report (Spark aggregates)

# COMMAND ----------

quality = spark_silver.quality_report(spark.table(target))  # noqa: F821
quality.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"{catalog}.{schema}.silver_quality_report")
display(quality)  # noqa: F821
