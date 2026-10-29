# Databricks notebook source
# MAGIC %md
# MAGIC # 01 · Bronze — ingest raw API data
# MAGIC Downloads every series of `config/sources.yaml` (Bank of Canada Valet, Statistics Canada,
# MAGIC FRED, US Census) and stores the **raw responses, untouched**, in the Unity Catalog Volume
# MAGIC `/Volumes/<catalog>/<schema>/lake/bronze/`. Each run adds a new timestamped snapshot.
# MAGIC
# MAGIC The ingestion log is published as the table `bronze_ingestion_log`.

# COMMAND ----------

# MAGIC %pip install -q "pydantic>=2.6" "pyyaml>=6"

# COMMAND ----------

dbutils.library.restartPython()  # noqa: F821

# COMMAND ----------

import pathlib
import sys

dbutils.widgets.text("catalog", "workspace")  # noqa: F821
dbutils.widgets.text("schema", "cfl")  # noqa: F821
catalog = dbutils.widgets.get("catalog")  # noqa: F821
schema = dbutils.widgets.get("schema")  # noqa: F821

# The notebook lives in <repo>/databricks/notebooks: put <repo>/src on the import path.
REPO_ROOT = pathlib.Path.cwd().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog}.{schema}")  # noqa: F821
spark.sql(f"CREATE VOLUME IF NOT EXISTS {catalog}.{schema}.lake")  # noqa: F821

from cfl import bronze  # noqa: E402
from cfl import databricks as cfl_dbx  # noqa: E402
from cfl.config import load_registry  # noqa: E402

lake = cfl_dbx.configure(catalog, schema, dbutils)  # noqa: F821
print("Lake root:", lake)

# COMMAND ----------

registry = load_registry()
results = bronze.ingest(registry.series)

failed = [r for r in results if not r.ok]
print(f"Bronze: {len(results) - len(failed)}/{len(results)} series ingested")
for r in failed:
    print(f"  FAILED {r.name}: {r.error}")

# COMMAND ----------

cfl_dbx.save_table(
    spark,  # noqa: F821
    bronze.read_manifest(),
    f"{catalog}.{schema}.bronze_ingestion_log",
    comment="One row per series per ingestion run: URL, size, SHA-256 of the raw payload, status.",
)

# COMMAND ----------

# Fail the job if a core source is down; the Census tariff series alone are tolerated (key may be missing).
critical = [r.name for r in failed if registry.by_name()[r.name].source != "census"]
if critical:
    raise RuntimeError(f"Ingestion failed for core series: {critical}")
