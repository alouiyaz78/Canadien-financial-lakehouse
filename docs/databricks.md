# Running the lakehouse on Databricks

The same pipeline runs on Databricks (Free Edition is enough), deployed as code with a
**Databricks Asset Bundle** ([`databricks.yml`](../databricks.yml)).

| Layer | Local | Databricks (Unity Catalog) |
|---|---|---|
| Bronze | `data/bronze/` raw files | Volume `workspace.cfl.lake` → `/Volumes/workspace/cfl/lake/bronze/` |
| Audit | `_manifest/run_*.jsonl` | table `bronze_ingestion_log` |
| Silver | Delta table `data/silver/observations` | tables `silver_observations`, `silver_quality_report` |
| Gold | Delta table `data/gold/model_table_monthly` | tables `gold_model_table_monthly` (column comments), `gold_column_dictionary` |
| Orchestration | `uv run cfl run` | Job `cfl-daily-refresh` (serverless, daily 07:43 Toronto) |

The notebooks in [`databricks/notebooks/`](../databricks/notebooks) are thin wrappers: they import the
`cfl` package from `src/` and only change *where* data is stored.

## One-time setup

1. **Workspace** — create a free account: <https://www.databricks.com/learn/free-edition>.
   Copy the workspace URL from your browser (`https://<something>.cloud.databricks.com`).

2. **CLI** (in WSL / Linux / macOS):

   ```bash
   curl -fsSL https://raw.githubusercontent.com/databricks/setup-cli/main/install.sh | sudo sh
   databricks auth login --host https://<your-workspace>.cloud.databricks.com
   ```

3. **Census API key as a secret** (the tariff series need it; without it they are skipped):

   ```bash
   databricks secrets create-scope cfl
   databricks secrets put-secret cfl census_api_key --string-value "$CENSUS_API_KEY"
   ```

## Deploy and run

```bash
databricks bundle validate -t prod
databricks bundle deploy   -t prod      # schema, volume, notebooks, job
databricks bundle run cfl_daily_refresh -t prod
```

The `dev` target (default) deploys a personal copy with prefixed names and a paused schedule —
use it to try changes without touching the `prod` tables.

## What to look at

* **Catalog Explorer → workspace → cfl**: tables with descriptions, column comments, *Lineage* tab
  (Volume → Silver → Gold), *History* tab (one Delta version per daily run).
* **Jobs & Pipelines → cfl-daily-refresh**: run history, task graph, durations.
* SQL time travel:

  ```sql
  DESCRIBE HISTORY workspace.cfl.gold_model_table_monthly;
  SELECT * FROM workspace.cfl.gold_model_table_monthly VERSION AS OF 0;
  ```
