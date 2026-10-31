"""Data dictionary as code (dbt-style ``schema.yml``) for the BI and operations tables.

One YAML file (config/bi_dictionary.yaml) feeds:

* Unity Catalog — table comments, column comments and ``layer`` / ``kind`` tags, visible in Catalog
  Explorer and queryable through ``information_schema``;
* docs/bi_data_dictionary.md — rendered by ``uv run cfl docs``;
* tests — undocumented or stale columns fail the build.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from cfl.config import PROJECT_ROOT

log = logging.getLogger(__name__)

DICTIONARY_FILE = PROJECT_ROOT / "config" / "bi_dictionary.yaml"
MARKDOWN_FILE = PROJECT_ROOT / "docs" / "bi_data_dictionary.md"
KIND_ORDER = ["dimension", "fact", "mart", "operations"]


@lru_cache(maxsize=2)
def load_dictionary(path: Path = DICTIONARY_FILE) -> dict[str, dict]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)["tables"]


def undocumented(table: str, columns: list[str]) -> tuple[list[str], list[str]]:
    """(columns produced but not documented, columns documented but not produced)."""
    documented = load_dictionary()[table]["columns"]
    return [c for c in columns if c not in documented], [c for c in documented if c not in columns]


# --------------------------------------------------------------------------- Unity Catalog
def _sql_string(text: str) -> str:
    from cfl.databricks import sql_string

    return sql_string(" ".join(str(text).split()))


def apply_to_unity_catalog(spark: Any, catalog: str, schema: str, tables: list[str]) -> None:
    """Write descriptions as table/column comments and kind as a tag, for the given (existing) tables."""
    spec = load_dictionary()
    for table in tables:
        entry = spec[table]
        fqn = f"{catalog}.{schema}.{table}"
        existing = set(spark.table(fqn).columns)
        comment = f"{entry['description']} Grain: {entry['grain']}."
        spark.sql(f"COMMENT ON TABLE {fqn} IS {_sql_string(comment)}")
        for column, text in entry["columns"].items():
            if column in existing:
                spark.sql(f"ALTER TABLE {fqn} ALTER COLUMN `{column}` COMMENT {_sql_string(text)}")
        try:
            spark.sql(f"ALTER TABLE {fqn} SET TAGS ('layer' = 'gold', 'kind' = '{entry['kind']}')")
        except Exception as exc:  # noqa: BLE001 — tags are optional (permissions / edition)
            log.warning("could not tag %s: %s", fqn, exc)
        log.info("dictionary applied to %s (%d columns)", fqn, len(entry["columns"]))


# --------------------------------------------------------------------------- Markdown
def to_markdown() -> str:
    spec = load_dictionary()
    lines = [
        "# BI data dictionary",
        "",
        "Generated from [`config/bi_dictionary.yaml`](../config/bi_dictionary.yaml) by `uv run cfl docs` — "
        "do not edit by hand. The same descriptions are written to Unity Catalog as table and column comments.",
        "",
        "| Table | Kind | Grain | Description |",
        "| --- | --- | --- | --- |",
    ]
    ordered = sorted(spec.items(), key=lambda kv: (KIND_ORDER.index(kv[1]["kind"]), kv[0]))
    for name, entry in ordered:
        lines.append(
            f"| [`{name}`](#{name}) | {entry['kind']} | {entry['grain']} | {' '.join(entry['description'].split())} |"
        )
    for name, entry in ordered:
        lines += [
            "",
            f"## {name}",
            "",
            f"*{entry['kind']} — {entry['grain']}.* {' '.join(entry['description'].split())}",
            "",
            "| Column | Description |",
            "| --- | --- |",
        ]
        lines += [f"| `{col}` | {' '.join(str(text).split())} |" for col, text in entry["columns"].items()]
    return "\n".join(lines) + "\n"


def write_markdown(path: Path = MARKDOWN_FILE) -> Path:
    path.write_text(to_markdown(), encoding="utf-8")
    return path
