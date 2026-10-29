"""Delta Lake storage for the Silver and Gold layers (delta-rs, no Spark/JVM needed).

Every write is a new table version, so any past state can be read back:

    read_table(path)               latest version
    read_table(path, version=3)    time travel — e.g. the exact training data of an old model
    history(path)                  list of versions with timestamps
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def write_table(frame: pd.DataFrame, path: Path) -> int:
    """Overwrite the table with ``frame`` (schema changes allowed) and return the new version number."""
    import pyarrow as pa
    from deltalake import DeltaTable, write_deltalake

    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(frame, preserve_index=False)
    write_deltalake(str(path), table, mode="overwrite", schema_mode="overwrite")
    return DeltaTable(str(path)).version()


def read_table(path: Path, version: int | None = None) -> pd.DataFrame:
    from deltalake import DeltaTable

    table = DeltaTable(str(path), version=version) if version is not None else DeltaTable(str(path))
    return table.to_pandas()


def history(path: Path) -> pd.DataFrame:
    from deltalake import DeltaTable

    records = DeltaTable(str(path)).history()
    frame = pd.DataFrame(records)
    keep = [c for c in ("version", "timestamp", "operation") if c in frame.columns]
    frame = frame[keep]
    if "timestamp" in frame:
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], unit="ms", utc=True)
    return frame.sort_values("version")
