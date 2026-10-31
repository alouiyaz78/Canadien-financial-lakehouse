# Databricks notebook source
# MAGIC %md
# MAGIC # 03 · Gold — monthly model table
# MAGIC Builds the monthly, model-ready table for both forecasting problems:
# MAGIC
# MAGIC * **A** — core inflation (CPI-trim, CPI-median, headline) 3, 6 and 12 months ahead
# MAGIC * **B** — direction of the Bank of Canada policy rate over the next 1 and 3 months
# MAGIC
# MAGIC Features are aligned in **real time**: each series is shifted by its publication lag, so a row
# MAGIC dated month *t* only contains what was published by the end of *t* (no look-ahead leakage).
# MAGIC Every column carries its description as a Unity Catalog column comment.

# COMMAND ----------

# MAGIC %pip install -q "pydantic>=2.6" "pyyaml>=6"

# COMMAND ----------

dbutils.library.restartPython()  # noqa: F821

# COMMAND ----------

import pathlib
import sys

WIDGETS = [('catalog', 'workspace'), ('schema', 'cfl')]
for name, default in WIDGETS:
    dbutils.widgets.text(name, default)  # noqa: F821
params = {name: dbutils.widgets.get(name) for name, _ in WIDGETS}  # noqa: F821
catalog, schema = params["catalog"], params["schema"]

# The notebook lives in <repo>/databricks/notebooks: put <repo>/src on the import path.
REPO_ROOT = pathlib.Path.cwd().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))


import pandas as pd  # noqa: E402

from cfl import databricks as cfl_dbx  # noqa: E402
from cfl import gold  # noqa: E402
from cfl.config import load_registry  # noqa: E402

cfl_dbx.configure(catalog, schema, dbutils)  # noqa: F821

# COMMAND ----------

observations = spark.table(f"{catalog}.{schema}.silver_observations").drop("run_id", "updated_at").toPandas()  # noqa: F821
observations["date"] = pd.to_datetime(observations["date"])
table, dictionary = gold.assemble_gold(observations, load_registry())
flat = gold.to_flat(table)
flat[flat.select_dtypes("float").columns] = flat.select_dtypes("float").round(4)

gold_table = f"{catalog}.{schema}.gold_model_table_monthly"
cfl_dbx.save_table(
    spark,  # noqa: F821
    flat,
    gold_table,
    comment="Monthly model table since 1990: real-time features (lagged by publication delay) and targets "
    "for core-inflation forecasting (A) and policy-rate direction (B).",
    date_columns=["month"],
)
cfl_dbx.save_column_comments(spark, gold_table, dictionary)  # noqa: F821
cfl_dbx.save_table(
    spark,  # noqa: F821
    dictionary,
    f"{catalog}.{schema}.gold_column_dictionary",
    comment="Role (feature_raw, feature_derived, target, meta) and meaning of every Gold column.",
)

# COMMAND ----------

# MAGIC %md ## Latest months

# COMMAND ----------

display(  # noqa: F821
    spark.sql(  # noqa: F821
        f"""
        SELECT month, policy_rate, cpi_trim, cpi_median, cpi_headline_yoy, unemployment_rate,
               wti_oil, us_tariff_rate_on_canada, term_spread_10y_2y
        FROM {gold_table}
        ORDER BY month DESC
        LIMIT 18
        """
    )
)
