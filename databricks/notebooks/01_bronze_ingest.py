# Databricks notebook source
# MAGIC %md
# MAGIC # 01 · Bronze — ingest one source
# MAGIC Downloads every series of **one source** (`source` parameter: valet, statcan, fred or census) and stores the
# MAGIC raw responses, untouched, in the Unity Catalog Volume `/Volumes/<catalog>/<schema>/lake/bronze/`.
# MAGIC
# MAGIC A new snapshot is written **only if the payload changed** (SHA-256 compared with the latest snapshot), so
# MAGIC re-running the job is idempotent. The job runs one instance of this notebook per source, in parallel.

# COMMAND ----------

# MAGIC %pip install -q "pydantic>=2.6" "pyyaml>=6"

# COMMAND ----------

dbutils.library.restartPython()  # noqa: F821

# COMMAND ----------

import pathlib
import sys

WIDGETS = [('catalog', 'workspace'), ('schema', 'cfl'), ('source', 'valet'), ('run_id', 'manual')]
for name, default in WIDGETS:
    dbutils.widgets.text(name, default)  # noqa: F821
params = {name: dbutils.widgets.get(name) for name, _ in WIDGETS}  # noqa: F821
catalog, schema = params["catalog"], params["schema"]

# The notebook lives in <repo>/databricks/notebooks: put <repo>/src on the import path.
REPO_ROOT = pathlib.Path.cwd().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from cfl import bronze  # noqa: E402
from cfl import databricks as cfl_dbx  # noqa: E402
from cfl.config import load_registry  # noqa: E402

cfl_dbx.configure(catalog, schema, dbutils)  # noqa: F821
spark.sql(f"CREATE VOLUME IF NOT EXISTS {catalog}.{schema}.lake")  # noqa: F821

# COMMAND ----------

source = params["source"]
specs = load_registry().select(source=source)
results = bronze.ingest(specs, run_id=params["run_id"], tag=source)

failed = [r for r in results if not r.ok]
changed = [r.name for r in results if r.changed]
print(f"{source}: {len(results) - len(failed)}/{len(results)} fetched, {len(changed)} changed: {changed}")

# Read by the audit task and visible in the job run UI.
dbutils.jobs.taskValues.set(key="n_changed", value=len(changed))  # noqa: F821

# COMMAND ----------

# Census is tolerated without its API key; any other failure marks this task (and the run) as failed.
# Downstream tasks still run (run_if: ALL_DONE) with the sources that succeeded.
if failed and source != "census":
    raise RuntimeError(f"{source}: ingestion failed for {[(r.name, r.error) for r in failed]}")
