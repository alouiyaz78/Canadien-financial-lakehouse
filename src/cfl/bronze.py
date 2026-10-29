"""Bronze layer: store raw API responses exactly as received.

Layout::

    data/bronze/<source>/<series_name>/<UTC timestamp>.<json|csv>
    data/bronze/_manifest/run_<UTC timestamp>.jsonl    one line per series of that run (audit trail)

Raw files are never modified; every run adds new snapshots. Keeping snapshots
gives a free audit trail of data revisions (StatCan revises GDP and LFS data).
Files are only ever created, never appended to, so the same code works on a
local disk and on a Databricks Unity Catalog Volume.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from cfl.config import SeriesSpec, data_dir
from cfl.sources import client_for
from cfl.sources.base import make_session

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class IngestResult:
    name: str
    ok: bool
    path: Path | None
    error: str | None = None
    record: dict = field(default_factory=dict)


def bronze_dir() -> Path:
    return data_dir() / "bronze"


def ingest_series(spec: SeriesSpec, session=None) -> IngestResult:
    session = session or make_session()
    ingested_at = datetime.now(UTC)
    record = {
        "name": spec.name,
        "source": spec.source,
        "source_id": spec.source_id,
        "ingested_at": ingested_at.isoformat(),
    }
    try:
        payload = client_for(spec.source).fetch(spec, session)
    except Exception as exc:  # noqa: BLE001 — one failing series must not stop the run
        log.error("FAILED %-28s %s", spec.name, exc)
        record |= {"status": "error", "error": str(exc)[:500]}
        return IngestResult(spec.name, ok=False, path=None, error=str(exc), record=record)

    target = bronze_dir() / spec.source / spec.name / f"{ingested_at:%Y%m%dT%H%M%S%fZ}.{payload.extension}"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload.content)
    record |= {
        "status": "ok",
        "url": payload.url,
        "path": str(target.relative_to(data_dir())),
        "bytes": len(payload.content),
        "sha256": hashlib.sha256(payload.content).hexdigest(),
    }
    log.info("ok     %-28s %8d bytes", spec.name, len(payload.content))
    return IngestResult(spec.name, ok=True, path=target, record=record)


def ingest(specs: list[SeriesSpec]) -> list[IngestResult]:
    session = make_session()
    started = datetime.now(UTC)
    results = [ingest_series(spec, session) for spec in specs]
    manifest = bronze_dir() / "_manifest" / f"run_{started:%Y%m%dT%H%M%S%fZ}.jsonl"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text("".join(json.dumps(r.record) + "\n" for r in results), encoding="utf-8")
    return results


def read_manifest() -> pd.DataFrame:
    """All ingestion attempts across runs, newest first."""
    files = sorted((bronze_dir() / "_manifest").glob("run_*.jsonl"))
    records = [json.loads(line) for f in files for line in f.read_text(encoding="utf-8").splitlines() if line]
    frame = pd.DataFrame(records)
    return frame.sort_values("ingested_at", ascending=False, ignore_index=True) if len(frame) else frame


def latest_snapshot(spec: SeriesSpec) -> Path | None:
    folder = bronze_dir() / spec.source / spec.name
    snapshots = sorted(folder.glob("*.*")) if folder.exists() else []
    return snapshots[-1] if snapshots else None
