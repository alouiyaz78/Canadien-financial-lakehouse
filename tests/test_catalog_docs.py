"""Data dictionary as code: every column documented, nothing stale, docs in sync, comments applied."""

import pandas as pd

from cfl import bronze, catalog_docs
from cfl.config import Registry
from cfl.freshness import freshness_report
from tests.conftest import spec
from tests.test_pipeline import fake_payloads, lake, registry  # noqa: F401 — pytest fixtures


def test_operations_tables_are_documented(lake):  # noqa: F811
    reg = Registry(series=[spec(name="cpi", frequency="M")])
    fresh = freshness_report(pd.Series({"cpi": "2026-09-01"}), reg, pd.Timestamp("2026-10-30"))
    assert catalog_docs.undocumented("freshness_report", list(fresh.columns)) == ([], [])
    missing, _ = catalog_docs.undocumented("bronze_ingestion_log", list(bronze.read_manifest().columns))
    assert not missing  # `error` only appears when a download failed


def test_markdown_is_in_sync_with_the_yaml():
    assert catalog_docs.MARKDOWN_FILE.read_text(encoding="utf-8") == catalog_docs.to_markdown(), (
        "docs/bi_data_dictionary.md is stale — run `uv run cfl docs`"
    )


class FakeTable:
    def __init__(self, columns):
        self.columns = columns


class FakeSpark:
    def __init__(self, columns):
        self.columns, self.sql_log = columns, []

    def table(self, name):
        return FakeTable(self.columns)

    def sql(self, statement):
        self.sql_log.append(statement)


def test_apply_to_unity_catalog_writes_comments_and_tags():
    spark = FakeSpark(["lag_months", "corr_headline", "corr_core", "n_months"])
    catalog_docs.apply_to_unity_catalog(spark, "workspace", "cfl", ["bi_mart_energy_passthrough"])
    sql = spark.sql_log
    assert sql[0].startswith("COMMENT ON TABLE workspace.cfl.bi_mart_energy_passthrough IS '")
    assert sum("ALTER COLUMN" in s for s in sql) == 4
    assert any("SET TAGS ('layer' = 'gold', 'kind' = 'mart')" in s for s in sql)
