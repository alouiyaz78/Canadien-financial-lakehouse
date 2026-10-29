"""Run the pipeline on Databricks (serverless) and publish the layers to Unity Catalog.

Mapping of the local lakehouse to Databricks:

    Bronze  raw API files  → UC Volume  /Volumes/<catalog>/<schema>/lake/bronze/...
    Silver  observations   → UC table   <catalog>.<schema>.silver_observations
            quality report → UC table   <catalog>.<schema>.silver_quality_report
    Gold    model table    → UC table   <catalog>.<schema>.gold_model_table_monthly
            dictionary     → UC table   <catalog>.<schema>.gold_column_dictionary
    Audit   ingestion log  → UC table   <catalog>.<schema>.bronze_ingestion_log

The same pure-Python code as locally does the work; only the storage changes.
Unity Catalog tables are Delta tables, so every daily run is a new version
(``DESCRIBE HISTORY``, ``SELECT ... VERSION AS OF n``).
"""

from __future__ import annotations

import logging
import os
from typing import Any

import pandas as pd

log = logging.getLogger(__name__)

SECRET_SCOPE = "cfl"
CENSUS_SECRET_KEY = "census_api_key"


def configure(catalog: str, schema: str, dbutils: Any | None = None) -> str:
    """Point the pipeline at the schema's Volume and load secrets. Returns the lake root path."""
    lake = f"/Volumes/{catalog}/{schema}/lake"
    os.environ["CFL_DATA_DIR"] = lake
    if dbutils is not None and not os.environ.get("CENSUS_API_KEY"):
        try:
            os.environ["CENSUS_API_KEY"] = dbutils.secrets.get(SECRET_SCOPE, CENSUS_SECRET_KEY)
        except Exception:  # noqa: BLE001 — without the key only the 3 tariff series are skipped
            log.warning("secret %s/%s not found: Census tariff series will be skipped", SECRET_SCOPE, CENSUS_SECRET_KEY)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s", force=True)
    return lake


def _spark_ready(frame: pd.DataFrame) -> pd.DataFrame:
    """Make a pandas frame safe for spark.createDataFrame (plain dtypes, no index, no Period)."""
    out = frame.reset_index(drop=True).copy()
    for col in out.columns:
        dtype = out[col].dtype
        if isinstance(dtype, pd.PeriodDtype):
            out[col] = out[col].dt.to_timestamp()
        elif pd.api.types.is_datetime64_any_dtype(dtype):
            out[col] = pd.to_datetime(out[col]).dt.tz_localize(None) if out[col].dt.tz else out[col]
        elif pd.api.types.is_bool_dtype(dtype):
            out[col] = out[col].astype(bool)
        elif not pd.api.types.is_numeric_dtype(dtype):
            # Plain Python values / None in an object column (pandas 3 would otherwise infer "str").
            raw = [None if (not isinstance(v, (list, dict)) and pd.isna(v)) else v for v in out[col].tolist()]
            is_flag = all(isinstance(v, bool) for v in raw if v is not None) and any(v is not None for v in raw)
            values = raw if is_flag else [None if v is None else str(v) for v in raw]
            out[col] = pd.Series(values, index=out.index, dtype=object)
    return out


def sql_string(text: str) -> str:
    """Quote ``text`` as a Spark SQL string literal (Spark escapes with backslashes, not doubled quotes)."""
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"


def save_table(
    spark: Any, frame: pd.DataFrame, table: str, comment: str = "", date_columns: tuple[str, ...] | list[str] = ()
) -> None:
    """Overwrite a Unity Catalog managed Delta table with ``frame`` (new table version each run).

    ``date_columns`` are stored as DATE instead of TIMESTAMP (e.g. the Gold ``month``).
    """
    from cfl.spark_silver import nan_to_null

    sdf = nan_to_null(spark.createDataFrame(_spark_ready(frame)))
    if date_columns:
        from pyspark.sql import functions as F

        for col in date_columns:
            sdf = sdf.withColumn(col, F.to_date(col))
    (sdf.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(table))
    if comment:
        spark.sql(f"COMMENT ON TABLE {table} IS {sql_string(comment)}")
    log.info("UC table %s written (%d rows)", table, len(frame))


def save_column_comments(spark: Any, table: str, dictionary: pd.DataFrame) -> None:
    """Attach each column's description from the Gold dictionary as a Unity Catalog column comment."""
    for row in dictionary.itertuples(index=False):
        text = sql_string(f"[{row.role}] {row.description}"[:1000])
        spark.sql(f"ALTER TABLE {table} ALTER COLUMN `{row.column}` COMMENT {text}")
