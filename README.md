# Canadian Financial Lakehouse

A lakehouse project on Canadian macro-financial data from the **Bank of Canada Valet API**. The goal is to ingest, clean and model 27 interest-rate, bond, FX, inflation, money-supply and mortgage series with **Databricks and Delta Lake** (medallion architecture), then expose them in a **Power BI** dashboard.

## Project status

| Phase | Content | Status |
|---|---|---|
| 1. Data discovery | Explore the Valet API catalog, select and verify 27 series | Done |
| 2. Bronze ingestion | Unified Delta Lake schema and ingestion pipeline | Next |
| 3. Silver | Cleaning, typing, standardised daily/weekly/monthly tables | Planned |
| 4. Gold | Analytics-ready tables (spreads, trends) | Planned |
| 5. Power BI | Dashboard on the gold layer | Planned |

## Data

27 series selected from the Bank of Canada Valet API:

| Domain | Series | Frequency |
|---|---|---|
| Policy rate | 1 (overnight target) | Daily |
| Treasury bills and bonds | 11 (1 month to long-term) | Daily |
| Foreign exchange (vs CAD) | 6 (USD, EUR, GBP, JPY, CHF, CNY) | Daily (2017 onward) |
| Inflation | 4 (CPI, CPI-trim, CPI-median, CPI-common) | Monthly |
| Monetary aggregates | 2 (M1++, M2++ growth) | Monthly |
| Conventional mortgage rates | 3 (1, 3 and 5 years) | Weekly |

The full data dictionary is in [docs/data_dicionnary_selected_series.md](docs/data_dicionnary_selected_series.md).

## Data quality findings (Phase 1)

All 27 series passed structural checks: no missing values, no non-numeric entries, no duplicate dates. A few extreme values are real historical facts (mortgage rates near 21% in the early 1980s, slightly negative T-bill yields in stress periods, monthly CPI deflation as low as -0.9%). FX history starts in 2017 because of an API limitation.

## Planned analyses

- Yield curve: 10-year minus 2-year spread (inversion as a recession signal)
- Bank credit cost: 5-year mortgage rate vs 5-year Government of Canada bond
- Policy rate differential vs USD/CAD

## Repository structure

```
discovery/   Valet API catalog exploration (explore_series.py, series.json)
notebooks/   01_data_discovery_series_exploration, 02_series_metadata_verification
docs/        Data dictionary of the selected series
main.py      Entry point
pyproject.toml, uv.lock   Python dependencies (uv)
```

## Run the discovery step

```bash
uv sync
uv run python discovery/explore_series.py
```

This reads `discovery/series.json` and writes a CSV, an Excel file and a summary to `discovery/outputs/`.

## Tech stack

Python, pandas, Bank of Canada Valet API, Databricks, Delta Lake, PySpark, Power BI.
