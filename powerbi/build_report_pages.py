# ruff: noqa: E501 — page layouts read better on one line per visual
"""Generate the analytical pages of the Power BI report (PBIR format) from readable Python.

    uv run python powerbi/build_report_pages.py

Close Power BI Desktop first, run the script, then reopen canadian_financial_lakehouse.pbip.
Pages written here are fully regenerated on every run (page 1, built by hand, is left alone except
for resetting its what-if sliders to their default values).
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

REPORT = Path(__file__).parent / "canadian_financial_lakehouse.Report" / "definition"
PAGES = REPORT / "pages"
SCHEMA_VISUAL = (
    "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.14.0/schema.json"
)
SCHEMA_PAGE = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.1.0/schema.json"
M = "_Measures"
DATE = ("bi_dim_date", "month_start")

# ------------------------------------------------------------------ expression helpers


def lit(value: str) -> dict:
    return {"expr": {"Literal": {"Value": value}}}


def text(value: str) -> dict:
    return lit("'" + value.replace("'", "''") + "'")


def theme_color(color_id: int, percent: float = 0) -> dict:
    return {"solid": {"color": {"expr": {"ThemeDataColor": {"ColorId": color_id, "Percent": percent}}}}}


def source(entity: str) -> dict:
    return {"Expression": {"SourceRef": {"Entity": entity}}}


def measure(name: str, label: str | None = None) -> dict:
    out = {
        "field": {"Measure": {**source(M), "Property": name}},
        "queryRef": f"{M}.{name}",
        "nativeQueryRef": label or name,
    }
    if label:
        out["displayName"] = label
    return out


def column(entity: str, col: str, label: str | None = None) -> dict:
    out = {
        "field": {"Column": {**source(entity), "Property": col}},
        "queryRef": f"{entity}.{col}",
        "nativeQueryRef": label or col,
        "active": True,
    }
    if label:
        out["displayName"] = label
    return out


def total(entity: str, col: str, label: str | None = None) -> dict:
    out = {
        "field": {"Aggregation": {"Expression": {"Column": {**source(entity), "Property": col}}, "Function": 0}},
        "queryRef": f"Sum({entity}.{col})",
        "nativeQueryRef": label or col,
    }
    if label:
        out["displayName"] = label
    return out


def title_objects(title: str | None, subtitle: str | None = None) -> dict:
    if title is None:
        return {"title": [{"properties": {"show": lit("false")}}]}
    out = {"title": [{"properties": {"show": lit("true"), "text": text(title)}}]}
    if subtitle:
        out["subTitle"] = [{"properties": {"show": lit("true"), "text": text(subtitle)}}]
    return out


def sort_by(field: dict, direction: str = "Ascending") -> dict:
    return {"sort": [{"field": field["field"], "direction": direction}], "isDefaultSort": True}


# ------------------------------------------------------------------ visuals


class Page:
    def __init__(self, key: str, display: str):
        self.key = key
        self.name = hashlib.sha1(key.encode()).hexdigest()[:20]
        self.display = display
        self.visuals: list[dict] = []

    def add(self, key: str, pos: tuple[float, float, float, float], visual: dict) -> None:
        x, y, w, h = pos
        n = len(self.visuals)
        self.visuals.append(
            {
                "$schema": SCHEMA_VISUAL,
                "name": hashlib.sha1(f"{self.key}/{key}".encode()).hexdigest()[:20],
                "position": {"x": x, "y": y, "z": n, "height": h, "width": w, "tabOrder": n},
                "visual": {**visual, "drillFilterOtherVisuals": True},
            }
        )

    # -- building blocks
    def headline(self, words: str) -> None:
        run = {
            "value": words,
            "textStyle": {
                "fontWeight": "bold",
                "fontFamily": "Segoe UI Semibold",
                "fontSize": "28pt",
                "color": "#0B2545",
            },
        }
        self.add(
            "title",
            (47, 12, 1845, 80),
            {
                "visualType": "textbox",
                "objects": {"general": [{"properties": {"paragraphs": [{"textRuns": [run]}]}}]},
                "visualContainerObjects": title_objects(None),
            },
        )

    def kpis(self, fields: list[dict]) -> None:
        self.add(
            "kpis",
            (47, 100, 1845, 200),
            {
                "visualType": "cardVisual",
                "query": {"queryState": {"Data": {"projections": fields}}},
                "objects": {
                    "label": [
                        {"properties": {"show": lit("true"), "fontSize": lit("13D")}, "selector": {"id": "default"}}
                    ],
                    "value": [
                        {
                            "properties": {
                                "fontSize": lit("26D"),
                                "bold": lit("true"),
                                "fontColor": theme_color(1, 0.2),
                            },
                            "selector": {"id": "default"},
                        }
                    ],
                    "accentBar": [
                        {
                            "properties": {"show": lit("true"), "width": lit("5D"), "color": theme_color(3)},
                            "selector": {"id": "default"},
                        }
                    ],
                },
                "visualContainerObjects": title_objects(None),
            },
        )

    def line(self, key, pos, ys: list[dict], title, subtitle=None, start="2000-01-01", category=None) -> None:
        cat = category or column(*DATE)
        objects = {"categoryAxis": [{"properties": {"fontSize": lit("9D"), "gridlineShow": lit("true")}}]}
        if category is None:
            objects["categoryAxis"][0]["properties"]["start"] = lit(f"datetime'{start}T00:00:00'")
        self.add(
            key,
            pos,
            {
                "visualType": "lineChart",
                "query": {
                    "queryState": {"Category": {"projections": [cat]}, "Y": {"projections": ys}},
                    "sortDefinition": sort_by(cat),
                },
                "objects": objects,
                "visualContainerObjects": title_objects(title, subtitle),
            },
        )

    def columns(self, key, pos, category: dict, ys: list[dict], title, subtitle=None, start=None) -> None:
        objects = {"categoryAxis": [{"properties": {"fontSize": lit("9D")}}]}
        if start:
            objects["categoryAxis"][0]["properties"]["start"] = lit(f"datetime'{start}T00:00:00'")
        self.add(
            key,
            pos,
            {
                "visualType": "clusteredColumnChart",
                "query": {
                    "queryState": {"Category": {"projections": [category]}, "Y": {"projections": ys}},
                    "sortDefinition": sort_by(category),
                },
                "objects": objects,
                "visualContainerObjects": title_objects(title, subtitle),
            },
        )

    def card(self, key, pos, field: dict, size: str = "20D") -> None:
        self.add(
            key,
            pos,
            {
                "visualType": "cardVisual",
                "query": {"queryState": {"Data": {"projections": [field]}}},
                "objects": {
                    "label": [
                        {"properties": {"show": lit("true"), "fontSize": lit("13D")}, "selector": {"id": "default"}}
                    ],
                    "value": [
                        {
                            "properties": {
                                "fontSize": lit(size),
                                "bold": lit("true"),
                                "fontColor": theme_color(1, 0.2),
                            },
                            "selector": {"id": "default"},
                        }
                    ],
                    "accentBar": [
                        {
                            "properties": {"show": lit("true"), "width": lit("5D"), "color": theme_color(3)},
                            "selector": {"id": "default"},
                        }
                    ],
                },
                "visualContainerObjects": title_objects(None),
            },
        )

    def table(
        self,
        key,
        pos,
        fields: list[dict],
        title,
        sort: dict | None = None,
        direction="Ascending",
        cell_color: tuple[str, str] | None = None,
    ) -> None:
        visual = {
            "visualType": "tableEx",
            "query": {"queryState": {"Values": {"projections": fields}}},
            "objects": {
                "values": [{"properties": {"fontSize": lit("11D")}}],
                "columnHeaders": [{"properties": {"fontSize": lit("11D"), "bold": lit("true")}}],
            },
            "visualContainerObjects": title_objects(title),
        }
        if sort:
            visual["query"]["sortDefinition"] = sort_by(sort, direction)
        if cell_color:  # (queryRef of the coloured column, measure returning a hex colour)
            ref, colour_measure = cell_color
            visual["objects"]["values"].append(
                {
                    "properties": {
                        "backColor": {
                            "solid": {"color": {"expr": {"Measure": {**source(M), "Property": colour_measure}}}}
                        },
                        "fontColor": {"solid": {"color": lit("'#FFFFFF'")}},
                    },
                    "selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}], "metadata": ref},
                }
            )
        self.add(key, pos, visual)

    def slicer(self, key, pos, entity: str) -> None:
        self.add(
            key,
            pos,
            {
                "visualType": "slicer",
                "query": {"queryState": {"Values": {"projections": [column(entity, entity)]}}},
                "objects": {
                    "data": [{"properties": {"mode": text("Single")}}],
                    "numericInputStyle": [{"properties": {"textSize": lit("16D"), "bold": lit("true")}}],
                },
            },
        )

    def write(self) -> None:
        folder = PAGES / self.name
        if folder.exists():
            shutil.rmtree(folder)
        (folder / "visuals").mkdir(parents=True)
        page = {
            "$schema": SCHEMA_PAGE,
            "name": self.name,
            "displayName": self.display,
            "displayOption": "FitToPage",
            "height": 1080,
            "width": 1920,
        }
        dump(folder / "page.json", page)
        for v in self.visuals:
            (folder / "visuals" / v["name"]).mkdir()
            dump(folder / "visuals" / v["name"] / "visual.json", v)


def dump(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# ------------------------------------------------------------------ pages

LEFT, RIGHT = (47, 320, 1100, 740), (1165, 320, 727, 740)


def signals_page() -> Page:
    p = Page("signals", "Signals & Inflation")
    p.headline("Core inflation sits on target — the energy shock is the risk")
    p.kpis(
        [
            measure("Latest Headline CPI", "Headline CPI (y/y %)"),
            measure("Latest Core Inflation", "Core inflation (%)"),
            measure("Latest Inflation Expectations 2-3Y", "Expected inflation 2–3y (%)"),
            measure("Latest Firms Expecting > 3% Inflation (%)", "Firms expecting > 3% (%)"),
            measure("Net Policy Stance Label", "Net policy stance"),
            measure("Market Pricing Label", "Market pricing (6 months)"),
        ]
    )
    p.line(
        "inflation",
        LEFT,
        [
            measure("Headline CPI (y/y)", "Headline CPI"),
            measure("CPI-trim"),
            measure("CPI-median"),
            measure("Target Band Low", "Band low (1%)"),
            measure("Target Band High", "Band high (3%)"),
        ],
        "Inflation vs the 1–3 % target band (y/y %)",
        "Headline moves with energy; CPI-trim and CPI-median show the underlying trend.",
        start="2015-01-01",
    )
    signal_label = column("bi_mart_policy_signals", "signal_label", "Signal")
    p.table(
        "signals",
        RIGHT,
        [
            column("bi_mart_policy_signals", "indicator", "Indicator"),
            total("bi_mart_policy_signals", "latest_value", "Latest"),
            column("bi_mart_policy_signals", "unit", "Unit"),
            signal_label,
        ],
        "Hawkish / dovish scorecard",
        sort=column("bi_mart_policy_signals", "indicator"),
        cell_color=(signal_label["queryRef"], "Signal Color"),
    )
    return p


def oil_page() -> Page:
    p = Page("oil", "Oil Shock")
    p.headline("Oil is up — will it reach core prices?")
    p.kpis(
        [
            measure("Latest WTI (USD)", "WTI (US$/bbl)"),
            measure("Latest WTI (CAD)", "WTI (C$/bbl)"),
            measure("Latest FX Effect on Oil (pts)", "FX effect, 12 m (pts)"),
            measure("Latest Headline minus Core (pts)", "Headline − core (pts)"),
            measure("Peak Lag to Core (months)", "Pass-through delay (months)"),
            measure("Peak Correlation to Core", "Peak correlation"),
        ]
    )
    p.line(
        "wti",
        (47, 320, 920, 740),
        [measure("WTI (USD)"), measure("WTI (CAD)")],
        "WTI crude, US$ vs C$ per barrel",
        "C$ price = US$ price × USD/CAD: the gap moves with the exchange rate.",
        start="2019-01-01",
    )
    p.columns(
        "passthrough",
        (985, 320, 907, 430),
        column("bi_mart_energy_passthrough", "lag_months", "Lag (months)"),
        [total("bi_mart_energy_passthrough", "corr_core", "Correlation with core")],
        "Energy → core inflation: correlation by lag",
        "The peak is the pass-through delay (since 2000).",
    )
    p.columns(
        "fx_effect",
        (985, 770, 907, 290),
        column(*DATE),
        [measure("FX Effect on Oil (pts)", "FX effect (pts)")],
        "Exchange-rate effect on oil (pts)",
        "> 0: a weaker loonie amplified the shock; < 0: it cushioned it.",
        start="2019-01-01",
    )
    return p


def tariffs_page() -> Page:
    p = Page("tariffs", "Tariffs")
    p.headline("Canada pays far less than the headlines suggest")
    p.kpis(
        [
            measure("Latest Tariff on Canada (%)", "Effective tariff: Canada (%)"),
            measure("Latest Tariff on Mexico (%)", "Mexico (%)"),
            measure("Latest Tariff on China (%)", "China (%)"),
            measure("Latest Canada Advantage vs China (pts)", "Canada's advantage vs China (pts)"),
            measure("Latest US Import Prices from Canada (y/y %)", "US import prices from Canada (y/y %)"),
            measure("Latest Trade Policy Uncertainty", "Trade policy uncertainty"),
        ]
    )
    p.line(
        "tariffs",
        LEFT,
        [
            measure("US Tariff on Canada (%)", "Canada"),
            measure("US Tariff on Mexico (%)", "Mexico"),
            measure("US Tariff on China (%)", "China"),
        ],
        "Effective US tariff rate = duties paid / import value (%)",
        "CUSMA-compliant goods are exempt: most Canadian exports still enter duty-free.",
        start="2023-01-01",
    )
    p.line(
        "uncertainty",
        (1165, 320, 727, 500),
        [measure("Trade Policy Uncertainty")],
        "Trade-policy uncertainty index",
        "Uncertainty delays investment even when tariffs paid stay low.",
        start="2023-01-01",
    )
    p.card(
        "absorption",
        (1165, 840, 727, 220),
        measure("Exporter Absorption Reading", "Are Canadian exporters absorbing tariffs?"),
        size="16D",
    )
    return p


def mortgage_page() -> Page:
    p = Page("mortgage", "Mortgage Renewal")
    p.headline("Renewals still raise payments — the wave peaks now")
    p.kpis(
        [
            measure("Latest Mortgage 5Y (%)", "5-year rate today (%)"),
            measure("Latest Rate at Origination (%)", "Rate signed 5 years ago (%)"),
            measure("Latest Renewal Rate Change (pts)", "Change at renewal (pts)"),
            measure("Payment at Origination", "Payment before ($/month)"),
            measure("Payment at Renewal", "Payment after ($/month)"),
            measure("Monthly Payment Shock (%)", "Payment shock (%)"),
        ]
    )
    p.line(
        "rates",
        LEFT,
        [
            measure("Mortgage 5Y Today (%)", "Rate today"),
            measure("Mortgage 5Y at Origination (%)", "Rate signed 5 years earlier"),
        ],
        "Posted 5-year mortgage rate: today vs at signing (%)",
        "Yellow above blue = households renew at a higher rate. Canadian terms are 5 years, so hikes reach borrowers with a lag.",
        start="2015-01-01",
    )
    p.slicer("amount", (1165, 320, 727, 180), "Mortgage amount")
    p.slicer("amortization", (1165, 510, 727, 180), "Amortization years")
    p.card(
        "shock_month", (1165, 700, 360, 360), measure("Monthly Payment Shock ($)", "Extra per month ($)"), size="28D"
    )
    p.card("shock_year", (1532, 700, 360, 360), measure("Annual Payment Shock ($)", "Extra per year ($)"), size="28D")
    return p


def health_page() -> Page:
    p = Page("health", "Data Health")
    p.headline("Every series is checked daily against its publication calendar")
    p.kpis(
        [
            measure("Series Monitored", "Series monitored"),
            measure("Series Late or Missing", "Late or missing"),
            measure("Data Freshness Score", "Up to date"),
            measure("Ingestion Runs", "Ingestion runs"),
            measure("Series Changed (runs)", "New payloads stored"),
            measure("Ingestion Errors", "Ingestion errors"),
        ]
    )
    age = column("freshness_report", "age_days", "Age (days)")
    p.table(
        "freshness",
        LEFT,
        [
            column("freshness_report", "name", "Series"),
            column("freshness_report", "source", "Source"),
            column("freshness_report", "frequency", "Freq."),
            column("freshness_report", "status", "Status"),
            column("freshness_report", "last_date", "Last observation"),
            age,
            column("freshness_report", "max_age_days", "Max age (days)"),
        ],
        "Freshness by series",
        sort=age,
        direction="Descending",
    )
    when = column("bronze_ingestion_log", "ingested_at", "Downloaded at (UTC)")
    p.table(
        "ingestion",
        RIGHT,
        [
            when,
            column("bronze_ingestion_log", "name", "Series"),
            column("bronze_ingestion_log", "status", "Status"),
            column("bronze_ingestion_log", "changed", "Changed"),
        ],
        "Ingestion log (latest first)",
        sort=when,
        direction="Descending",
    )
    return p


def reset_sliders() -> None:
    """Drop the slider positions saved on page 1, so the what-if defaults (0.75 / 0.5 / 0.5) apply."""
    for path in PAGES.glob("*/visuals/*/visual.json"):
        visual = json.loads(path.read_text(encoding="utf-8"))
        objects = visual.get("visual", {}).get("objects", {})
        if visual["visual"].get("visualType") != "slicer":
            continue
        objects.pop("general", None)
        for entry in objects.get("data", []):
            entry.get("properties", {}).pop("numericStart", None)
        dump(path, visual)


def main() -> None:
    pages = [signals_page(), oil_page(), tariffs_page(), mortgage_page(), health_page()]
    for page in pages:
        page.write()
    meta_path = PAGES / "pages.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    generated = [p.name for p in pages]
    manual = [name for name in meta["pageOrder"] if name not in generated]
    meta["pageOrder"] = manual + generated
    dump(meta_path, meta)
    reset_sliders()
    print(f"{len(pages)} pages written: " + ", ".join(p.display for p in pages))


if __name__ == "__main__":
    main()
