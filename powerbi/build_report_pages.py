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
    else:  # otherwise Power BI shows an automatic "X et Y par month_start" subtitle
        out["subTitle"] = [{"properties": {"show": lit("false")}}]
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
                "key": key,
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

    def navigator(self, pos) -> None:
        """Built-in page navigator: one button per report page, kept in sync by Power BI."""
        self.add(
            key="navigator",
            pos=pos,
            visual={"visualType": "pageNavigator", "visualContainerObjects": title_objects(None)},
        )

    def note(self, key, pos, paragraphs: list[tuple[str, bool]]) -> None:
        runs = [
            {
                "textRuns": [
                    {
                        "value": t,
                        "textStyle": {
                            "fontWeight": "bold" if b else "normal",
                            "fontSize": "13pt" if b else "11pt",
                            "color": "#0B2545" if b else "#33415C",
                        },
                    }
                ]
            }
            for t, b in paragraphs
        ]
        self.add(
            key,
            pos,
            {
                "visualType": "textbox",
                "objects": {"general": [{"properties": {"paragraphs": runs}}]},
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
                                "displayUnits": lit("1D"),
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

    def line(
        self, key, pos, ys: list[dict], title, subtitle=None, start="2000-01-01", category=None, y_range=None
    ) -> None:
        cat = category or column(*DATE)
        objects = {"categoryAxis": [{"properties": {"fontSize": lit("9D"), "gridlineShow": lit("true")}}]}
        if y_range:  # the axis start only clips x: pin y so older, higher values do not flatten the lines
            objects["valueAxis"] = [{"properties": {"start": lit(f"{y_range[0]}D"), "end": lit(f"{y_range[1]}D")}}]
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

    def columns(self, key, pos, category: dict, ys: list[dict], title, subtitle=None, start=None, y_range=None) -> None:
        objects = {"categoryAxis": [{"properties": {"fontSize": lit("9D")}}]}
        if y_range:
            objects["valueAxis"] = [{"properties": {"start": lit(f"{y_range[0]}D"), "end": lit(f"{y_range[1]}D")}}]
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
                                "displayUnits": lit("1D"),
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
                "total": [{"properties": {"totals": lit("false")}}],
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
        if self.key != "overview":
            for v in self.visuals:
                if v["key"] == "title":  # leave room for the back button on the right of the headline
                    v["position"]["width"] = BACK_POS[0] - 47 - 20
            self.add("back", BACK_POS, back_button_visual())
        for v in self.visuals:
            help_text = HELP.get((self.key, v["key"]))
            if help_text:
                add_help(v, help_text)
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
            dump(folder / "visuals" / v["name"] / "visual.json", {k: val for k, val in v.items() if k != "key"})


def dump(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False).replace("\n", "\r\n"), encoding="utf-8", newline="")


# ------------------------------------------------------------------ pages

LEFT, RIGHT = (47, 320, 1100, 740), (1165, 320, 727, 740)


def overview_page() -> Page:
    p = Page("overview", "Overview")
    p.headline("Canada's economy at a glance — refreshed daily from public sources")
    p.kpis(
        [
            measure("Policy Rate (latest)", "Policy rate (%)"),
            measure("Latest Headline CPI", "Headline CPI (y/y %)"),
            measure("Latest Core Inflation", "Core inflation (%)"),
            measure("Net Policy Stance Label", "Net policy stance"),
            measure("Latest Tariff on Canada (%)", "US tariff paid by Canada (%)"),
            measure("Monthly Payment Shock (%)", "Mortgage renewal shock (%)"),
        ]
    )
    w, gap = (1845 - 4 * 18) / 5, 18
    tiles = [
        (
            "t_policy",
            [measure("Policy Rate", "Policy rate"), measure("Taylor Rule Rate", "Taylor rule")],
            "Policy vs Taylor rule (%)",
            "2015-01-01",
        ),
        (
            "t_inflation",
            [measure("Headline CPI (y/y)", "Headline"), measure("Core Inflation (avg)", "Core")],
            "Inflation (y/y %)",
            "2015-01-01",
        ),
        ("t_oil", [measure("WTI (CAD)", "WTI in C$")], "Oil in C$ per barrel", "2019-01-01"),
        (
            "t_tariffs",
            [measure("US Tariff on Canada (%)", "Canada"), measure("US Tariff on China (%)", "China")],
            "Effective US tariff (%)",
            "2023-01-01",
        ),
        (
            "t_mortgage",
            [measure("Mortgage 5Y Today (%)", "Today"), measure("Mortgage 5Y at Origination (%)", "5 years earlier")],
            "5-year mortgage rate (%)",
            "2015-01-01",
        ),
    ]
    for i, (key, ys, title, start) in enumerate(tiles):
        p.line(
            key,
            (47 + i * (w + gap), 320, w, 400),
            ys,
            title,
            start=start,
            y_range=(4, 8) if key == "t_mortgage" else None,
        )
    p.navigator((47, 740, 1845, 90))
    p.note(
        "about",
        (47, 850, 1845, 210),
        [
            ("What is this report?", True),
            (
                "Questions the Bank of Canada faces after its 28 October 2026 hike: will the oil shock reach core inflation, how much do US tariffs really cost, "
                "and what do mortgage renewals do to households? Use the buttons above to open each analysis; hover the ? of any chart for a plain-language explanation.",
                False,
            ),
            (
                "Data: Bank of Canada (Valet), Statistics Canada, FRED and the US Census Bureau, ingested daily into a Databricks lakehouse (Bronze → Silver → Gold). "
                "Values are shown at reference dates. Source code: github.com/alouiyaz78/canadien-financial-lakehouse",
                False,
            ),
        ],
    )
    return p


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
            measure("Latest Market-Implied Move 6M (bp)", "Market-implied move, 6 m (bp)"),
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
            column("bi_mart_policy_signals", "latest_value", "Latest"),
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
        start="2022-01-01",
        y_range=(-15, 15),
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
            measure("Trade Uncertainty vs Normal", "Trade uncertainty"),
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
        "Trade-policy uncertainty (100 = normal level)",
        "Newspaper-based index: 1,000 = ten times the usual level. Uncertainty delays investment even when tariffs paid stay low.",
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
            measure("Payment Before (text)", "Payment before ($/month)"),
            measure("Payment After (text)", "Payment after ($/month)"),
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
        "First line above the second = households renew at a higher rate. Canadian terms are 5 years, so hikes reach borrowers with a lag.",
        start="2015-01-01",
        y_range=(4, 8),
    )
    p.slicer("amount", (1165, 320, 727, 180), "Mortgage amount")
    p.slicer("amortization", (1165, 510, 727, 180), "Amortization years")
    p.card("shock_month", (1165, 700, 360, 360), measure("Extra per Month (text)", "Extra per month"), size="28D")
    p.card("shock_year", (1532, 700, 360, 360), measure("Extra per Year (text)", "Extra per year"), size="28D")
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


# ------------------------------------------------------------------ help ("?" icon in each visual header)
# Plain-language Q&A for non-specialists: shown when the reader hovers or clicks the "?" of a visual.

HELP: dict[tuple[str, str], str] = {
    (
        "policy",
        "kpis",
    ): "What is the policy rate? The overnight rate set by the Bank of Canada eight times a year. It drives the rates banks charge on loans and mortgages. Net stance = hawkish minus dovish signals (see Signals & Inflation).",
    (
        "policy",
        "taylor",
    ): "What is the Taylor rule? A benchmark: the rate rises when inflation is above 2 % and falls when unemployment is high. The Bank uses it as a cross-check, not a formula. Big gaps: 2020, rates cannot go much below zero; 2021–22, inflation was judged temporary.",
    (
        "policy",
        "sliders",
    ): "What do the sliders change? r* is the real neutral rate, the level that neither stimulates nor slows the economy (Bank estimate about 0.75 %). The weights set how strongly the rule reacts to inflation and to unemployment. No selection = default values.",
    (
        "policy",
        "reading",
    ): "How is this decided? It compares the policy rate with the rule for the latest month: more than 0.5 point below the rule = room to hike, more than 0.5 above = room to cut.",
    (
        "signals",
        "kpis",
    ): "Latest published values. Firms expecting > 3 %: share of firms in the Bank's Business Outlook Survey expecting inflation above 3 %, a warning sign that the shock could spread. Market-implied move: 6-month T-bill minus policy rate, in basis points (100 bp = 1 %).",
    (
        "signals",
        "inflation",
    ): "What is inflation? How fast consumer prices rise over 12 months. The Bank targets 2 %, inside a 1–3 % band. Headline CPI includes volatile prices such as gasoline; CPI-trim and CPI-median remove extreme moves to show the underlying trend.",
    (
        "signals",
        "signals",
    ): "How do I read the scorecard? Each indicator votes: red argues for a rate hike, green for a cut, grey is neutral. Hikes minus cuts gives the net policy stance.",
    (
        "oil",
        "kpis",
    ): "Headline − core: the part of inflation driven by energy and other volatile prices. Pass-through delay: months until energy prices weigh most on core inflation.",
    (
        "oil",
        "wti",
    ): "Why two oil prices? Oil is priced in US dollars, but Canadians pay in Canadian dollars: C$ price = US$ price × exchange rate.",
    (
        "oil",
        "passthrough",
    ): "What is the pass-through delay? Each bar is the correlation between energy prices today and core inflation k months later. The peak, about a year, is how long energy takes to spread to other prices.",
    (
        "oil",
        "fx_effect",
    ): "What is the exchange-rate effect? 12-month change of oil in C$ minus in US$. Above zero: a weaker loonie made the shock worse for Canadians. Below zero: a stronger loonie softened it.",
    (
        "tariffs",
        "kpis",
    ): "Effective tariff = duties actually paid / value of goods imported by the US. Canada's advantage = China's rate minus Canada's, in percentage points.",
    (
        "tariffs",
        "tariffs",
    ): "What is the effective tariff? Duties actually paid divided by the value of goods the US imports, not the rate announced in the news. Goods that meet CUSMA rules of origin are exempt, so most Canadian exports still enter duty-free.",
    (
        "tariffs",
        "uncertainty",
    ): "What does this index measure? How often US newspapers write about uncertain trade policy. 100 = normal, 1,000 = ten times normal. Uncertainty delays business investment even when tariffs paid stay low.",
    (
        "tariffs",
        "absorption",
    ): "If US import prices of Canadian goods fall, Canadian exporters are cutting their prices to absorb part of the tariff.",
    (
        "mortgage",
        "kpis",
    ): "Posted rates are above the rates most borrowers negotiate, so focus on the change at renewal rather than the level.",
    (
        "mortgage",
        "rates",
    ): "What is a mortgage renewal? In Canada the rate is fixed for a term, usually 5 years, inside a 25-year loan. At the end of the term the household signs again at the market rate. When the rate today is above the rate signed 5 years earlier, renewing costs more.",
    (
        "mortgage",
        "amount",
    ): "How do I use the simulator? Pick a loan amount and an amortization. No selection = 500,000 $ over 25 years. The cards show the payment before and after renewal.",
    (
        "mortgage",
        "amortization",
    ): "Amortization: the total length of the loan, in years. Longer amortization = smaller monthly payment.",
    (
        "mortgage",
        "shock_month",
    ): "Extra monthly payment for a household renewing today, for the amount and amortization chosen.",
    (
        "health",
        "kpis",
    ): "An ingestion run is the daily job that downloads every series. A new copy is stored only when the source published something new.",
    (
        "health",
        "freshness",
    ): "What is freshness? Each series has an expected publication rhythm. It is 'late' when its last value is older than that rhythm allows.",
    (
        "health",
        "ingestion",
    ): "Why do errors appear? A source can be briefly unavailable. The job retries, the other series continue, and the error is logged here.",
}


OVERVIEW = hashlib.sha1(b"overview").hexdigest()[:20]  # page name of Overview (see Page.__init__)
BACK_POS = (1652, 22, 240, 60)


def back_button_visual() -> dict:
    """Navy "← Overview" button that jumps back to the main page (Ctrl+click in Desktop, plain click online)."""
    default = {"id": "default"}
    return {
        "visualType": "actionButton",
        "objects": {
            # "show" switches are state-independent; content and colours are set for the default state.
            "icon": [
                {"properties": {"show": lit("true")}},
                {"properties": {"shapeType": text("back"), "lineColor": {"solid": {"color": text("#FFFFFF")}}},
                 "selector": default},
            ],
            "text": [
                {"properties": {"show": lit("true")}},
                {
                    "properties": {
                        "text": text("Overview"),
                        "fontColor": {"solid": {"color": text("#FFFFFF")}},
                        "fontSize": lit("14D"),
                        "bold": lit("true"),
                    },
                    "selector": default,
                },
            ],
            "fill": [
                {"properties": {"show": lit("true")}},
                {
                    "properties": {
                        "fillColor": {"solid": {"color": text("#0B2545")}},
                        "transparency": lit("0D"),
                    },
                    "selector": default,
                },
            ],
        },
        "visualContainerObjects": {
            "visualLink": [
                {
                    "properties": {
                        "show": lit("true"),
                        "type": text("PageNavigation"),
                        "navigationSection": text(OVERVIEW),
                        "tooltip": text("Back to the overview page"),
                    }
                }
            ],
            "title": [{"properties": {"show": lit("false")}}],
        },
    }


def add_back_button_to_policy_page(folder: Path) -> None:
    name = hashlib.sha1(b"policy/back").hexdigest()[:20]
    target = folder / "visuals" / name
    target.mkdir(parents=True, exist_ok=True)
    x, y, w, h = BACK_POS
    dump(
        target / "visual.json",
        {
            "$schema": SCHEMA_VISUAL,
            "name": name,
            "position": {"x": x, "y": y, "z": 100, "height": h, "width": w, "tabOrder": 100},
            "visual": {**back_button_visual(), "drillFilterOtherVisuals": True},
        },
    )


def add_help(visual: dict, help_text: str) -> None:
    """Show a "?" in the visual header whose tooltip is ``help_text`` (Power BI: General → Header icons)."""
    objects = visual["visual"].setdefault("visualContainerObjects", {})
    objects["visualHeader"] = [{"properties": {"showTooltipButton": lit("true")}}]
    objects["visualHeaderTooltip"] = [{"properties": {"text": text(help_text)}}]


def fix_policy_page() -> None:
    """Page 1 is built by hand: remove the old Q&A strip, give the visuals their height back, add the "?" help."""
    folder = next(
        p
        for p in PAGES.iterdir()
        if p.is_dir()
        and json.loads((p / "page.json").read_text(encoding="utf-8-sig"))["displayName"] == "Policy Monitor"
    )
    for i in range(3):  # Q&A text boxes written by an earlier version of this script
        name = hashlib.sha1(f"policy/qa{i}".encode()).hexdigest()[:20]
        if (folder / "visuals" / name).exists():
            shutil.rmtree(folder / "visuals" / name)
    paths = list(folder.glob("visuals/*/visual.json"))
    visuals = {p: json.loads(p.read_text(encoding="utf-8-sig")) for p in paths}
    top, bottom = 358.0, 1060.0
    lowest = max(v["position"]["y"] + v["position"]["height"] for v in visuals.values())
    for path, visual in visuals.items():
        pos, kind = visual["position"], visual["visual"]["visualType"]
        if lowest < bottom - 1 and pos["y"] >= top - 1:
            scale = (bottom - top) / (lowest - top)
            pos["y"] = top + (pos["y"] - top) * scale
            pos["height"] = pos["height"] * scale
        if kind == "lineChart":
            add_help(visual, HELP[("policy", "taylor")])
        elif kind == "slicer":
            add_help(visual, HELP[("policy", "sliders")])
        elif kind == "cardVisual":
            add_help(visual, HELP[("policy", "kpis" if pos["y"] < top else "reading")])
        dump(path, visual)
    add_back_button_to_policy_page(folder)


BACKGROUND ="cfl_background.png"  # drawn by make_background.py


def apply_background() -> None:
    """Register the background image and use it on every page (visuals keep their white backgrounds)."""
    report_path = REPORT / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8-sig"))
    registered = next(p for p in report["resourcePackages"] if p["name"] == "RegisteredResources")
    if not any(item["name"] == BACKGROUND for item in registered["items"]):
        registered["items"].append({"name": BACKGROUND, "path": BACKGROUND, "type": "Image"})
        dump(report_path, report)
    image = {
        "image": {
            "name": text(BACKGROUND),
            "url": {
                "expr": {
                    "ResourcePackageItem": {
                        "PackageName": "RegisteredResources",
                        "PackageType": 1,
                        "ItemName": BACKGROUND,
                    }
                }
            },
            "scaling": text("Fill"),
        }
    }
    for path in PAGES.glob("*/page.json"):
        page = json.loads(path.read_text(encoding="utf-8-sig"))
        page.setdefault("objects", {})["background"] = [{"properties": {"image": image, "transparency": lit("0D")}}]
        dump(path, page)


# What-if parameters: default value (same as the SELECTEDVALUE fallback in the model) and its DAX literal.
SLIDER_DEFAULTS = {
    "Neutral real rate": "0.75D",
    "Inflation weight": "0.5D",
    "Slack weight": "0.5D",
    "Mortgage amount": "500000L",
    "Amortization years": "25L",
}


def reset_sliders() -> None:
    """Put every what-if slider on its default value, so the slider shows the number the measures use."""
    for path in PAGES.glob("*/visuals/*/visual.json"):
        visual = json.loads(path.read_text(encoding="utf-8-sig"))
        if visual["visual"].get("visualType") != "slicer":
            continue
        objects = visual["visual"].setdefault("objects", {})
        entity = visual["visual"]["query"]["queryState"]["Values"]["projections"][0]["field"]["Column"]["Property"]
        value = SLIDER_DEFAULTS.get(entity)
        if value is None:
            continue
        for entry in objects.setdefault("data", [{"properties": {}}]):
            entry.setdefault("properties", {})["numericStart"] = lit(value)
        alias = entity[0].lower()
        objects["general"] = [
            {
                "properties": {
                    "filter": {
                        "filter": {
                            "Version": 2,
                            "From": [{"Name": alias, "Entity": entity, "Type": 0}],
                            "Where": [
                                {
                                    "Condition": {
                                        "Comparison": {
                                            "ComparisonKind": 0,
                                            "Left": {
                                                "Column": {
                                                    "Expression": {"SourceRef": {"Source": alias}},
                                                    "Property": entity,
                                                }
                                            },
                                            "Right": {"Literal": {"Value": value}},
                                        }
                                    }
                                }
                            ],
                        }
                    }
                }
            }
        ]
        dump(path, visual)


def main() -> None:
    overview = overview_page()
    pages = [overview, signals_page(), oil_page(), tariffs_page(), mortgage_page(), health_page()]
    for page in pages:
        page.write()
    meta_path = PAGES / "pages.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8-sig"))
    generated = [p.name for p in pages]
    manual = [name for name in meta["pageOrder"] if name not in generated]
    meta["pageOrder"] = [overview.name] + manual + generated[1:]
    meta["activePageName"] = overview.name
    dump(meta_path, meta)
    reset_sliders()
    fix_policy_page()
    apply_background()
    print(f"{len(pages)} pages written: " + ", ".join(p.display for p in pages))


if __name__ == "__main__":
    main()
