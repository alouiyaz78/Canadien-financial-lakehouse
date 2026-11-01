"""Guards for the Power BI project (PBIP): Power BI Desktop refuses to open a model with these errors."""

import json
import re
from collections import Counter
from pathlib import Path

POWERBI = Path(__file__).parents[1] / "powerbi"
MODEL = POWERBI / "canadian_financial_lakehouse.SemanticModel" / "definition"
REPORT = POWERBI / "canadian_financial_lakehouse.Report" / "definition"


def test_lineage_tags_are_unique():
    tags = [
        t for f in MODEL.glob("tables/*.tmdl") for t in re.findall(r"lineageTag: (\S+)", f.read_text(encoding="utf-8"))
    ]
    assert [t for t, n in Counter(tags).items() if n > 1] == []


def test_report_only_uses_existing_measures():
    model = (MODEL / "tables" / "_Measures.tmdl").read_text(encoding="utf-8")
    measures = {m.strip("'").replace("''", "'") for m in re.findall(r"^\tmeasure (.+?) =", model, re.M)}
    used = set()
    for path in REPORT.glob("pages/*/visuals/*/visual.json"):
        used |= set(
            re.findall(
                r'"Measure": \{\s*"Expression": \{\s*"SourceRef": \{\s*"Entity": "_Measures"\s*\}\s*\},\s*"Property": "([^"]+)"',
                path.read_text(encoding="utf-8"),
            )
        )
    assert used and used <= measures, sorted(used - measures)


def test_page_order_matches_page_folders():
    order = json.loads((REPORT / "pages" / "pages.json").read_text(encoding="utf-8"))["pageOrder"]
    folders = {p.name for p in (REPORT / "pages").iterdir() if p.is_dir()}
    assert set(order) == folders
