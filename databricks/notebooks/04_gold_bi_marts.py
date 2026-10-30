# Databricks notebook source
# MAGIC %md
# MAGIC # 04 · Gold BI — star schema for Power BI
# MAGIC Builds the tables of the Power BI report, at **reference dates** (September CPI is shown in
# MAGIC September), unlike the ML table which is aligned on publication dates:
# MAGIC
# MAGIC | Table | Grain | Used by |
# MAGIC |---|---|---|
# MAGIC | `bi_dim_date`, `bi_dim_series` | day, series | every page (slicers, relationships) |
# MAGIC | `bi_fact_observations` | series × date | exploration page |
# MAGIC | `bi_fact_yield_curve` | date × tenor | yield curve |
# MAGIC | `bi_fact_policy_decisions`, `bi_fact_policy_calendar` | decision | policy monitor |
# MAGIC | `bi_mart_macro_monthly` | month | all analytical pages |
# MAGIC | `bi_mart_energy_passthrough` | lag (months) | oil shock page |
# MAGIC | `bi_mart_policy_signals` | indicator | hawkish / dovish scorecard |

# COMMAND ----------

# MAGIC %pip install -q "pydantic>=2.6" "pyyaml>=6"

# COMMAND ----------

dbutils.library.restartPython()  # noqa: F821

# COMMAND ----------

import pathlib
import sys

WIDGETS = [("catalog", "workspace"), ("schema", "cfl")]
for name, default in WIDGETS:
    dbutils.widgets.text(name, default)  # noqa: F821
params = {name: dbutils.widgets.get(name) for name, _ in WIDGETS}  # noqa: F821
catalog, schema = params["catalog"], params["schema"]

# The notebook lives in <repo>/databricks/notebooks: put <repo>/src on the import path.
REPO_ROOT = pathlib.Path.cwd().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import pandas as pd  # noqa: E402

from cfl import bi  # noqa: E402
from cfl import databricks as cfl_dbx  # noqa: E402
from cfl.config import load_registry  # noqa: E402

cfl_dbx.configure(catalog, schema, dbutils)  # noqa: F821

# COMMAND ----------

observations = spark.table(f"{catalog}.{schema}.silver_observations").select("name", "date", "value").toPandas()  # noqa: F821
observations["date"] = pd.to_datetime(observations["date"])
tables = bi.build_bi_tables(observations, load_registry())

COMMENTS = {
    "dim_date": "Daily calendar since 1990 (relationships and time slicers).",
    "dim_series": "One row per series: source, domain, unit, frequency, publication lag.",
    "fact_observations": "Every observation at its reference date (name, date, value).",
    "fact_yield_curve": "Daily Government of Canada yields by tenor, overnight to 30 years.",
    "fact_policy_decisions": "Every policy-rate change since 2001 with easing/tightening cycles.",
    "fact_policy_calendar": "Scheduled Bank of Canada decision dates (config/boc_calendar.yaml).",
    "mart_macro_monthly": "Monthly indicators at reference dates: inflation vs target, Taylor rule, oil in CAD, "
    "tariffs, mortgage renewal shock, spreads.",
    "mart_energy_passthrough": "Correlation of energy-price inflation with headline/core inflation k months later.",
    "mart_policy_signals": "Latest hawkish/dovish scorecard: one row per indicator with thresholds and rationale.",
}
for name, frame in tables.items():
    cfl_dbx.save_table(
        spark,  # noqa: F821
        frame,
        f"{catalog}.{schema}.bi_{name}",
        comment=COMMENTS[name],
        date_columns=bi.DATE_COLUMNS.get(name, ()),
    )

# COMMAND ----------

# MAGIC %md ## Today's scorecard

# COMMAND ----------

display(spark.table(f"{catalog}.{schema}.bi_mart_policy_signals"))  # noqa: F821
