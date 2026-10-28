"""Bronze layer: store raw API responses exactly as received.

Layout::

    data/bronze/<source>/<series_name>/<UTC timestamp>.<json|csv>
    data/bronze/_manifest.jsonl     one line per ingestion attempt (audit trail)

Raw files are never modified; every run adds a new snapshot. Keeping snapshots
gives a free audit trail of data revisions (StatCan revises GDP and LFS data).
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

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


def bronze_dir() -> Path:
    return data_dir() / "bronze"


def _write_manifest(record: dict) -> None:
    manifest = bronze_dir() / "_manifest.jsonl"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


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
        _write_manifest({**record, "status": "error", "error": str(exc)[:500]})
        return IngestResult(spec.name, ok=False, path=None, error=str(exc))

    target = bronze_dir() / spec.source / spec.name / f"{ingested_at:%Y%m%dT%H%M%SZ}.{payload.extension}"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload.content)
    _write_manifest(
        {
            **record,
            "status": "ok",
            "url": payload.url,
            "path": str(target.relative_to(data_dir())),
            "bytes": len(payload.content),
            "sha256": hashlib.sha256(payload.content).hexdigest(),
        }
    )
    log.info("ok     %-28s %8d bytes", spec.name, len(payload.content))
    return IngestResult(spec.name, ok=True, path=target)


def ingest(specs: list[SeriesSpec]) -> list[IngestResult]:
    session = make_session()
    return [ingest_series(spec, session) for spec in specs]


def latest_snapshot(spec: SeriesSpec) -> Path | None:
    folder = bronze_dir() / spec.source / spec.name
    snapshots = sorted(folder.glob("*.*")) if folder.exists() else []
    return snapshots[-1] if snapshots else None
