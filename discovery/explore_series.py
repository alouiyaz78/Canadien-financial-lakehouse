#!/usr/bin/env python3
"""
Explore Bank of Canada Valet API series catalog.

Input:
    series.json

Output:
    outputs/
        ├── series_catalog.csv
        ├── series_catalog.xlsx
        └── summary.txt
"""

from pathlib import Path
import json
import pandas as pd

BASE_DIR = Path(__file__).parent
INPUT_FILE = BASE_DIR / "series.json"
OUTPUT_DIR = BASE_DIR / "outputs"

OUTPUT_DIR.mkdir(exist_ok=True)

print(f"Reading {INPUT_FILE}...")

with open(INPUT_FILE, "r", encoding="utf-8") as f:
    data = json.load(f)

rows = []

for series_id, metadata in data.get("series", {}).items():

    row = {
        "series_id": series_id,
    }

    # Copie toutes les métadonnées disponibles
    if isinstance(metadata, dict):
        for key, value in metadata.items():
            row[key] = value

    rows.append(row)

df = pd.DataFrame(rows)

df = df.sort_values("series_id")

csv_file = OUTPUT_DIR / "series_catalog.csv"
xlsx_file = OUTPUT_DIR / "series_catalog.xlsx"

df.to_csv(csv_file, index=False)
df.to_excel(xlsx_file, index=False)

summary = OUTPUT_DIR / "summary.txt"

with open(summary, "w") as f:

    f.write("BANK OF CANADA - SERIES CATALOG\n")
    f.write("=" * 40 + "\n\n")

    f.write(f"Number of series : {len(df)}\n")
    f.write(f"Number of columns: {len(df.columns)}\n\n")

    f.write("Columns\n")
    f.write("-" * 30 + "\n")

    for c in df.columns:
        f.write(c + "\n")

print("\nDone.")
print(f"Rows : {len(df)}")
print(f"Columns : {len(df.columns)}")
print()
print(df.head())
print()
print(f"CSV  : {csv_file}")
print(f"Excel: {xlsx_file}")
print(f"Summary: {summary}")