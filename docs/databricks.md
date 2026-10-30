# Running the lakehouse on Databricks

The same pipeline runs on Databricks (Free Edition is enough), deployed as code with a
**Databricks Asset Bundle** ([`databricks.yml`](../databricks.yml)).

| Layer | Local | Databricks (Unity Catalog) |
|---|---|---|
| Bronze | `data/bronze/` raw files | Volume `workspace.cfl.lake` → `/Volumes/workspace/cfl/lake/bronze/` |
| Audit | `_manifest/run_*.jsonl` | table `bronze_ingestion_log` (one row per series per run, `changed` flag) |
| Freshness | `uv run cfl freshness` | table `freshness_report` (`ok` / `late` / `missing` per series) |
| Silver | Delta table `data/silver/observations` | `silver_observations` (incremental **MERGE** on name+date), `silver_quality_report` |
| Gold | Delta table `data/gold/model_table_monthly` | tables `gold_model_table_monthly` (column comments), `gold_column_dictionary` |
| BI (Power BI) | `uv run cfl bi` → `data/gold/bi/` | `bi_dim_*`, `bi_fact_*`, `bi_mart_*` tables (see [`powerbi/GUIDE.md`](../powerbi/GUIDE.md)) |
| Orchestration | `uv run cfl run` (skips Silver/Gold if nothing changed) | Job `cfl-daily-refresh` (serverless, daily 07:43 Toronto) |

## Job design: poll daily, work only when something changed

Publication dates are irregular (CPI mid-month, LFS first Friday, GDP ~2 months later, revisions any
time), so the job **polls every morning** and is cheap when nothing is new:

```
ingest_valet ───┐
ingest_statcan ─┤                                  ┌─ true ─► silver_transform ─┬─► gold_model_table (ML)
ingest_fred ────┼─► audit_freshness ─► any_changes ┤                            └─► gold_bi_marts (Power BI)
ingest_census ──┘   (run_if ALL_DONE)              └─ false ─► (stop)
```

* **Idempotent Bronze** — a raw snapshot is written only if its SHA-256 differs from the latest one.
* **Isolated sources** — one task per source with its own retry; a StatCan outage does not block Valet.
* **Change gate** — a `condition_task` reads the task value `any_changed`; Silver/Gold are skipped otherwise.
* **Incremental Silver** — only changed series are merged: new dates inserted, revised values updated,
  vanished dates deleted; `run_id`/`updated_at` record which run touched each row.
* **Freshness monitoring** — `freshness_report` flags series older than their publication calendar allows.
* Force a full rebuild: run the job with the parameter `full_refresh=true`.

A self-contained PySpark reference on one series (raw JSON → `explode` → window dedup → `MERGE` →
monthly aggregation) is in
[`databricks/notebooks/examples/pyspark_valet_policy_rate.py`](../databricks/notebooks/examples/pyspark_valet_policy_rate.py).

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
