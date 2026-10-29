"""Bronze layer: store raw API responses exactly as received.

Layout::

    data/bronze/<source>/<series_name>/<UTC timestamp>.<json|csv>
    data/bronze/_manifest/run_<UTC timestamp>.jsonl    one line per series of that run (audit trail)

Raw files are never modified. A new snapshot is written **only when the payload
changed** (SHA-256 differs from the latest snapshot): new observations or a
revision (StatCan revises GDP and LFS data). Unchanged series are recorded in the
manifest with ``changed = false`` and downstream layers can skip them.
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

    @property
    def changed(self) -> bool:
        return bool(self.record.get("changed"))


def bronze_dir() -> Path:
    return data_dir() / "bronze"


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def ingest_series(spec: SeriesSpec, session=None, run_id: str | None = None) -> IngestResult:
    session = session or make_session()
    ingested_at = datetime.now(UTC)
    record = {
        "run_id": run_id,
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

    digest = _sha256(payload.content)
    previous = latest_snapshot(spec)
    changed = previous is None or _sha256(previous.read_bytes()) != digest
    if changed:
        target = bronze_dir() / spec.source / spec.name / f"{ingested_at:%Y%m%dT%H%M%S%fZ}.{payload.extension}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload.content)
    else:
        target = previous  # identical payload: keep the existing snapshot, write nothing
    record |= {
        "status": "ok",
        "changed": changed,
        "url": payload.url,
        "path": str(target.relative_to(data_dir())),
        "bytes": len(payload.content),
        "sha256": digest,
    }
    log.info("%-6s %-28s %8d bytes", "NEW" if changed else "same", spec.name, len(payload.content))
    return IngestResult(spec.name, ok=True, path=target, record=record)


def ingest(specs: list[SeriesSpec], run_id: str | None = None, tag: str = "") -> list[IngestResult]:
    """Ingest ``specs``; one manifest file per call (``tag`` distinguishes parallel tasks, e.g. a source)."""
    session = make_session()
    started = datetime.now(UTC)
    results = [ingest_series(spec, session, run_id) for spec in specs]
    suffix = f"_{tag}" if tag else ""
    manifest = bronze_dir() / "_manifest" / f"run_{started:%Y%m%dT%H%M%S%fZ}{suffix}.jsonl"
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
