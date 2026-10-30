"""Freshness monitoring: is the latest observation of each series as recent as it should be?

Statuses: ``ok`` | ``late`` | ``missing`` | ``retired`` (series flagged ``discontinued`` in the registry,
kept for history, never alerted on).

A series is ``late`` when the age of its latest observation (today − last reference date)
exceeds ``SeriesSpec.max_age_days()``. This catches a source that silently stopped
updating, a changed series id, or a publication delayed beyond its usual calendar.
"""

from __future__ import annotations

import pandas as pd

from cfl.config import Registry


def freshness_report(last_dates: pd.Series, registry: Registry, today: pd.Timestamp | None = None) -> pd.DataFrame:
    """``last_dates``: latest observation date per series name. Missing series are reported as ``missing``."""
    today = (today or pd.Timestamp.now()).normalize()
    last = pd.to_datetime(last_dates)
    rows = []
    for spec in registry.series:
        last_date = last.get(spec.name)
        if last_date is None or pd.isna(last_date):
            rows.append({"name": spec.name, "status": "missing"})
            continue
        age = int((today - last_date).days)
        if spec.discontinued:
            status = "retired"
        else:
            status = "late" if age > spec.max_age_days() else "ok"
        rows.append(
            {
                "name": spec.name,
                "status": status,
                "last_date": last_date,
                "age_days": age,
                "max_age_days": spec.max_age_days(),
            }
        )
    meta = pd.DataFrame([{"name": s.name, "source": s.source, "frequency": s.frequency} for s in registry.series])
    report = meta.merge(pd.DataFrame(rows), on="name")
    report["checked_at"] = today
    order = {"missing": 0, "late": 1, "ok": 2, "retired": 3}
    return report.sort_values(["status", "name"], key=lambda c: c.map(order) if c.name == "status" else c)
