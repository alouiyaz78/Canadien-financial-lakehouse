# Databricks notebook source
# MAGIC %md
# MAGIC # 02 · Silver — parse, clean, quality report
# MAGIC Parses the latest Bronze snapshot of every series into one tidy long table
# MAGIC (`silver_observations`: name, source, date, value) and a per-series quality report
# MAGIC (`silver_quality_report`: coverage, gaps, dropped values, parse errors).

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

REPO_ROOT = pathlib.Path.cwd().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from cfl import databricks as cfl_dbx  # noqa: E402
from cfl import silver  # noqa: E402
from cfl.config import load_registry  # noqa: E402

cfl_dbx.configure(catalog, schema, dbutils)  # noqa: F821

# COMMAND ----------

observations, report = silver.assemble_silver(load_registry().series)

cfl_dbx.save_table(
    spark,  # noqa: F821
    observations,
    f"{catalog}.{schema}.silver_observations",
    comment="All series in long format (name, source, source_id, frequency, date, value). Parsed from Bronze.",
)
cfl_dbx.save_table(
    spark,  # noqa: F821
    report,
    f"{catalog}.{schema}.silver_quality_report",
    comment="Per-series data quality: coverage dates, max gap, values dropped, parse errors.",
)

# COMMAND ----------

display(report)  # noqa: F821
