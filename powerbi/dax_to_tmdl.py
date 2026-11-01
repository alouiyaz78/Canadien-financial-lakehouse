"""Convert powerbi/measures.dax into a TMDL script that Power BI Desktop applies in one go.

    uv run python powerbi/dax_to_tmdl.py      # writes powerbi/measures.tmdl and syncs the PBIP model

In Power BI Desktop: TMDL view → new tab → paste measures.tmdl → Apply. Every measure lands in the
table `_Measures` with its display folder, format string and description (the `//` comment above it).
measures.dax stays the human-readable source; this file is generated from it.
"""

from __future__ import annotations

import re
from pathlib import Path

HERE = Path(__file__).parent
SOURCE = HERE / "measures.dax"
TARGET = HERE / "measures.tmdl"
TABLE = "_Measures"
MODEL_TABLE = HERE / "canadian_financial_lakehouse.SemanticModel" / "definition" / "tables" / f"{TABLE}.tmdl"

HEADER = re.compile(r"^(?!VAR\b|RETURN\b|//)([A-Za-z0-9][^=]*?) =(?: (.*))?$")


def format_string(name: str, folder: str) -> str | None:
    if "($)" in name or name.startswith(("Payment", "Balance")):
        return r"\$#,0"
    if name.endswith("Shock (%)"):
        return "0.0%"
    counts = ("Days", "Months", "Series", "Ingestion", "Hawkish", "Dovish", "Net Policy Stance")
    if "Label" not in name and ("(bp)" in name or "(months)" in name or name.startswith(counts)):
        return "0"
    if name in {"Data Freshness Score"}:
        return "0%"
    if folder in {"Policy", "Inflation", "Energy", "Trade", "Mortgage", "Curve"} and not any(
        word in name for word in ("Label", "Reading", "Color", "Inverted", "Decision", "Uncertainty")
    ):
        return "0.00"
    return None


def parse(text: str) -> list[dict]:
    measures: list[dict] = []
    folder, pending_comment, current = "", [], None
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.startswith("// Folder:"):
            folder = line.removeprefix("// Folder:").split("(")[0].strip()
            continue
        match = HEADER.match(line) if line and not line[0].isspace() else None
        if match and "( " not in match.group(1):
            current = {"name": match.group(1).strip(), "folder": folder, "lines": [], "description": pending_comment}
            if match.group(2):
                current["lines"].append(match.group(2))
            measures.append(current)
            pending_comment = []
            continue
        if not line:
            current, pending_comment = None, []
            continue
        if current is None:
            if line.startswith("//") and not line.startswith("// ---") and not line.startswith("// ="):
                pending_comment.append(line.lstrip("/ "))
            continue
        current["lines"].append(line)
    return measures


def quote(name: str) -> str:
    return "'" + name.replace("'", "''") + "'"


def to_tmdl(measures: list[dict]) -> str:
    out = ["createOrReplace", "", f"\tref table {TABLE}", ""]
    for m in measures:
        for comment in m["description"]:
            out.append(f"\t\t/// {comment}")
        if len(m["lines"]) == 1:
            out.append(f"\t\tmeasure {quote(m['name'])} = {m['lines'][0]}")
        else:
            out.append(f"\t\tmeasure {quote(m['name'])} =")
            out += [f"\t\t\t\t{line}" for line in m["lines"]]
        fmt = format_string(m["name"], m["folder"])
        if fmt:
            out.append(f"\t\t\tformatString: {fmt}")
        out.append(f"\t\t\tdisplayFolder: {m['folder']}")
        out.append("")
    return "\n".join(out)


def measure_lines(m: dict, indent: int) -> list[str]:
    t = "\t" * indent
    out = [f"{t}/// {c}" for c in m["description"]]
    if len(m["lines"]) == 1:
        out.append(f"{t}measure {quote(m['name'])} = {m['lines'][0]}")
    else:
        out.append(f"{t}measure {quote(m['name'])} =")
        out += [f"{t}\t\t{line}" for line in m["lines"]]
    fmt = format_string(m["name"], m["folder"])
    if fmt:
        out.append(f"{t}\tformatString: {fmt}")
    out.append(f"{t}\tdisplayFolder: {m['folder']}")
    return out


def sync_model(measures: list[dict], path: Path = MODEL_TABLE) -> None:
    """Rewrite the measures of the PBIP model table, keeping lineage tags and the table's column/partition."""
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    # Look for each measure's lineage tag inside its own block only (a measure without a tag must not
    # borrow the next object's tag: duplicated tags make Power BI refuse to open the project).
    tags: dict[str, str] = {}
    taken = set(re.findall(r"^\t(?:column|table|partition)[^\n]*\n(?:\t\t[^\n]*\n)*?\t\tlineageTag: (\S+)", text, re.M))
    taken |= set(re.findall(r"^table .+\n\tlineageTag: (\S+)", text, re.M))
    for block in text.split("\n\n"):
        head = re.search(r"^\tmeasure (.+?) =", block, re.M)
        tag = re.search(r"^\t\tlineageTag: (\S+)", block, re.M)
        if head and tag and tag.group(1) not in taken and tag.group(1) not in tags.values():
            tags[head.group(1).strip("'").replace("''", "'")] = tag.group(1)
    table_tag = re.search(r"^table .+\n\tlineageTag: (\S+)", text, re.M).group(1)
    tail = text[text.index("\n\tcolumn ") + 1 :]
    if "\t\tisHidden" not in tail.split("\n\n")[0]:
        tail = tail.replace("\t\tdataType: string\n", "\t\tdataType: string\n\t\tisHidden\n", 1)
    out = [f"table {TABLE}", f"\tlineageTag: {table_tag}", ""]
    for m in measures:
        out += measure_lines(m, 1)
        if m["name"] in tags:
            out.append(f"\t\tlineageTag: {tags[m['name']]}")
        out.append("")
    path.write_text("\r\n".join(out + tail.split("\n")), encoding="utf-8", newline="")
    print(f"{len(measures)} measures synced → {path.relative_to(HERE)}")


def main() -> None:
    measures = parse(SOURCE.read_text(encoding="utf-8"))
    TARGET.write_text(to_tmdl(measures), encoding="utf-8")
    print(f"{len(measures)} measures → {TARGET}")
    sync_model(measures)


if __name__ == "__main__":
    main()
