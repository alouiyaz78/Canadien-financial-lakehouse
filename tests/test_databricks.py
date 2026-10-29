"""The Databricks glue that needs no Spark (Spark-dependent parts are in test_spark.py)."""

from cfl import databricks as cfl_dbx


def test_configure_points_lake_to_volume(monkeypatch):
    monkeypatch.delenv("CENSUS_API_KEY", raising=False)

    class Secrets:
        def get(self, scope, key):
            assert (scope, key) == ("cfl", "census_api_key")
            return "secret-key"

    class DbUtils:
        secrets = Secrets()

    lake_root = cfl_dbx.configure("workspace", "cfl", DbUtils())
    import os

    assert lake_root == "/Volumes/workspace/cfl/lake" == os.environ["CFL_DATA_DIR"]
    assert os.environ["CENSUS_API_KEY"] == "secret-key"


def test_sql_string_escapes_quotes_and_backslashes():
    from cfl.databricks import sql_string

    assert sql_string("It's gold") == "'It\\'s gold'"
    assert sql_string("a\\b") == "'a\\\\b'"
