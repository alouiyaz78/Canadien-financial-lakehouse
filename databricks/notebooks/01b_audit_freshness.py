# Databricks notebook source
# MAGIC %md
# MAGIC # 01b · Audit — ingestion log, freshness, change gate
# MAGIC Runs after the four ingestion tasks (even if one failed):
# MAGIC
# MAGIC 1. publishes the ingestion log (`bronze_ingestion_log`): one row per series per run, with `changed`;
# MAGIC 2. publishes the **freshness report** (`freshness_report`): series whose latest observation is older than
# MAGIC    expected for its publication calendar are flagged `late`;
# MAGIC 3. sets the task value `any_changed`, used by the job's condition task to skip Silver/Gold when no source
# MAGIC    published anything new.

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

from cfl import bronze, silver  # noqa: E402
from cfl import databricks as cfl_dbx  # noqa: E402
from cfl.config import load_registry  # noqa: E402
from cfl.freshness import freshness_report  # noqa: E402

cfl_dbx.configure(catalog, schema, dbutils)  # noqa: F821
registry = load_registry()

# COMMAND ----------

manifest = bronze.read_manifest()
this_run = manifest[manifest["run_id"].astype(str) == params["run_id"]] if len(manifest) else manifest
n_changed = int(this_run["changed"].fillna(False).astype(bool).sum()) if len(this_run) else 0

cfl_dbx.save_table(
    spark,  # noqa: F821
    manifest,
    f"{catalog}.{schema}.bronze_ingestion_log",
    comment="One row per series per ingestion run: run_id, changed flag, URL, size, SHA-256 of the raw payload.",
)
display(this_run[["source", "name", "status", "changed", "bytes"]])  # noqa: F821

# COMMAND ----------

# Latest observation date per series, read from the latest Bronze snapshots (cheap: no Spark needed).
_, report = silver.assemble_silver(registry.series)
fresh = freshness_report(report.set_index("name")["last_date"], registry)
cfl_dbx.save_table(
    spark,  # noqa: F821
    fresh,
    f"{catalog}.{schema}.freshness_report",
    comment="Is each series as recent as its publication calendar implies? status = ok | late | missing | retired (discontinued series).",
)
display(fresh)  # noqa: F821

# COMMAND ----------

silver_exists = spark.catalog.tableExists(f"{catalog}.{schema}.silver_observations")  # noqa: F821
any_changed = params["full_refresh"].lower() == "true" or n_changed > 0 or not silver_exists
dbutils.jobs.taskValues.set(key="any_changed", value="true" if any_changed else "false")  # noqa: F821
print(f"{n_changed} series changed in run {params['run_id']} → any_changed = {any_changed}")
