# ruff: noqa: E501 — SQL strings read better unwrapped
"""Generate the Databricks AI/BI dashboard definition (cfl_dashboard.lvdash.json) from readable Python.

    uv run python dashboards/build_dashboard.py

The JSON is deployed by the Asset Bundle (resources.dashboards in databricks.yml). Edit this file,
not the JSON: the queries and the layout stay reviewable in a pull request.
"""

from __future__ import annotations

import json
from pathlib import Path

SCHEMA = "workspace.cfl"
OUT = Path(__file__).with_name("cfl_dashboard.lvdash.json")


def long_format(columns: dict[str, str], label: str, since: str) -> str:
    pairs = ", ".join(f"'{name}', {col}" for name, col in columns.items())
    return (
        f"SELECT month, {label}, value FROM {SCHEMA}.bi_mart_macro_monthly "
        f"LATERAL VIEW stack({len(columns)}, {pairs}) s AS {label}, value "
        f"WHERE month >= DATE'{since}' AND value IS NOT NULL"
    )


DATASETS = {
    "kpis": (
        "Headline KPIs",
        f"""SELECT
  (SELECT yield_pct FROM {SCHEMA}.bi_fact_yield_curve WHERE tenor = 'Overnight' ORDER BY date DESC LIMIT 1) AS policy_rate,
  (SELECT round(cpi_headline_yoy, 1) FROM {SCHEMA}.bi_mart_macro_monthly WHERE cpi_headline_yoy IS NOT NULL ORDER BY month DESC LIMIT 1) AS headline_cpi,
  (SELECT round(core_avg, 1) FROM {SCHEMA}.bi_mart_macro_monthly WHERE core_avg IS NOT NULL ORDER BY month DESC LIMIT 1) AS core_inflation,
  (SELECT sum(signal) FROM {SCHEMA}.bi_mart_policy_signals) AS net_stance,
  (SELECT datediff(min(date), current_date()) FROM {SCHEMA}.bi_fact_policy_calendar WHERE date >= current_date()) AS days_to_decision,
  (SELECT round(100 * avg(CASE WHEN status IN ('ok', 'retired') THEN 1 ELSE 0 END)) FROM {SCHEMA}.freshness_report) AS fresh_pct""",
    ),
    "taylor": (
        "Policy rate vs Taylor rule",
        long_format({"Policy rate": "policy_rate", "Taylor rule": "taylor_rule_rate"}, "series", "2000-01-01"),
    ),
    "inflation": (
        "Inflation vs target",
        long_format(
            {
                "Headline CPI": "cpi_headline_yoy",
                "CPI-trim": "cpi_trim",
                "CPI-median": "cpi_median",
                "Band low (1%)": "target_low",
                "Band high (3%)": "target_high",
            },
            "series",
            "2015-01-01",
        ),
    ),
    "signals": (
        "Hawkish / dovish scorecard",
        f"SELECT indicator, round(latest_value, 2) AS latest_value, unit, signal_label "
        f"FROM {SCHEMA}.bi_mart_policy_signals ORDER BY signal DESC, indicator",
    ),
    "curve": (
        "Yield curve today vs one year ago",
        f"""WITH last_day AS (SELECT max(date) AS d FROM {SCHEMA}.bi_fact_yield_curve),
year_ago AS (SELECT max(c.date) AS d FROM {SCHEMA}.bi_fact_yield_curve c, last_day WHERE c.date <= date_sub(last_day.d, 365))
SELECT 'Today' AS curve, c.tenor_months, c.yield_pct FROM {SCHEMA}.bi_fact_yield_curve c JOIN last_day ON c.date = last_day.d
UNION ALL
SELECT 'One year ago', c.tenor_months, c.yield_pct FROM {SCHEMA}.bi_fact_yield_curve c JOIN year_ago ON c.date = year_ago.d""",
    ),
    "oil": ("WTI in USD vs CAD", long_format({"WTI (USD)": "wti_usd", "WTI (CAD)": "wti_cad"}, "series", "2020-01-01")),
    "passthrough": (
        "Energy to core pass-through",
        f"SELECT lag_months, round(corr_core, 3) AS corr_core FROM {SCHEMA}.bi_mart_energy_passthrough",
    ),
    "tariffs": (
        "Effective US tariff rates",
        long_format(
            {
                "Canada": "us_tariff_rate_on_canada",
                "Mexico": "us_tariff_rate_on_mexico",
                "China": "us_tariff_rate_on_china",
            },
            "series",
            "2023-01-01",
        ),
    ),
    "mortgage": (
        "Mortgage renewal shock",
        long_format(
            {"Rate today": "mortgage_5y", "Rate signed 5 years earlier": "mortgage_5y_at_origination"},
            "series",
            "2015-01-01",
        ),
    ),
    "freshness_status": (
        "Freshness status",
        f"SELECT status, count(*) AS series FROM {SCHEMA}.freshness_report GROUP BY status",
    ),
    "freshness_late": (
        "Late or missing series",
        f"SELECT name, source, frequency, CAST(last_date AS STRING) AS last_date, age_days, max_age_days "
        f"FROM {SCHEMA}.freshness_report WHERE status IN ('late', 'missing') ORDER BY age_days DESC",
    ),
    "ingestion": (
        "Ingestion activity (30 days)",
        f"""SELECT to_date(ingested_at) AS day,
  CASE WHEN status = 'error' THEN 'error' WHEN changed THEN 'new data' ELSE 'unchanged' END AS outcome,
  count(*) AS series
FROM {SCHEMA}.bronze_ingestion_log
WHERE to_date(ingested_at) >= date_sub(current_date(), 30)
GROUP BY ALL""",
    ),
}


def dataset(name: str) -> dict:
    display, sql = DATASETS[name]
    lines = sql.splitlines()
    return {"name": name, "displayName": display, "queryLines": [line + "\n" for line in lines[:-1]] + [lines[-1]]}


def query(ds: str, fields: list[str]) -> list[dict]:
    return [
        {
            "name": "main_query",
            "query": {
                "datasetName": ds,
                "fields": [{"name": f, "expression": f"`{f}`"} for f in fields],
                "disaggregated": True,
            },
        }
    ]


def frame(title: str, description: str = "") -> dict:
    out = {"showTitle": True, "title": title}
    if description:
        out |= {"showDescription": True, "description": description}
    return out


def position(x: int, y: int, w: int, h: int) -> dict:
    return {"x": x, "y": y, "width": w, "height": h}


def text(name: str, lines: list[str], pos: dict) -> dict:
    return {"widget": {"name": name, "multilineTextboxSpec": {"lines": lines}}, "position": pos}


def counter(name: str, field: str, title: str, pos: dict) -> dict:
    spec = {
        "version": 2,
        "widgetType": "counter",
        "encodings": {"value": {"fieldName": field, "displayName": title}},
        "frame": frame(title),
    }
    return {"widget": {"name": name, "queries": query("kpis", [field]), "spec": spec}, "position": pos}


def xy_chart(name, kind, ds, x, y, color, title, pos, *, x_type="temporal", x_label="", y_label="", desc=""):
    encodings = {
        "x": {"fieldName": x, "scale": {"type": x_type}, "displayName": x_label or x},
        "y": {"fieldName": y, "scale": {"type": "quantitative"}, "displayName": y_label or y},
    }
    fields = [x, y]
    if color:
        encodings["color"] = {"fieldName": color, "scale": {"type": "categorical"}, "displayName": color}
        fields.append(color)
    spec = {"version": 3, "widgetType": kind, "encodings": encodings, "frame": frame(title, desc)}
    return {"widget": {"name": name, "queries": query(ds, fields), "spec": spec}, "position": pos}


def table(name: str, ds: str, columns: list[tuple[str, str, str]], title: str, pos: dict) -> dict:
    cols = [
        {
            "fieldName": field,
            "displayName": label,
            "title": label,
            "type": kind,
            "displayAs": kind,
            "visible": True,
            "order": 100000 + i,
        }
        for i, (field, label, kind) in enumerate(columns)
    ]
    spec = {"version": 1, "widgetType": "table", "encodings": {"columns": cols}, "frame": frame(title)}
    return {
        "widget": {"name": name, "queries": query(ds, [c[0] for c in columns]), "spec": spec},
        "position": pos,
    }


POLICY_PAGE = [
    text(
        "title",
        [
            "# Canadian Financial Lakehouse — policy monitor\n",
            "Bank of Canada, Statistics Canada, FRED and US Census data, refreshed daily by the "
            "`cfl-daily-refresh` job. Values at reference dates.",
        ],
        position(0, 0, 6, 2),
    ),
    counter("kpi_policy", "policy_rate", "Policy rate (%)", position(0, 2, 1, 3)),
    counter("kpi_headline", "headline_cpi", "Headline CPI (y/y %)", position(1, 2, 1, 3)),
    counter("kpi_core", "core_inflation", "Core inflation (%)", position(2, 2, 1, 3)),
    counter("kpi_stance", "net_stance", "Net stance (+ hawkish)", position(3, 2, 1, 3)),
    counter("kpi_decision", "days_to_decision", "Days to next decision", position(4, 2, 1, 3)),
    counter("kpi_fresh", "fresh_pct", "Series up to date (%)", position(5, 2, 1, 3)),
    xy_chart(
        "chart_taylor",
        "line",
        "taylor",
        "month",
        "value",
        "series",
        "Policy rate vs Taylor rule (%)",
        position(0, 5, 4, 7),
        x_label="Month",
        y_label="%",
        desc="Policy below the rule = room to hike. 2020: effective lower bound; 2021–22: inflation judged transitory.",
    ),
    table(
        "table_signals",
        "signals",
        [
            ("indicator", "Indicator", "string"),
            ("latest_value", "Latest", "number"),
            ("unit", "Unit", "string"),
            ("signal_label", "Signal", "string"),
        ],
        "Hawkish / dovish scorecard",
        position(4, 5, 2, 7),
    ),
    xy_chart(
        "chart_inflation",
        "line",
        "inflation",
        "month",
        "value",
        "series",
        "Inflation vs the 1–3 % band",
        position(0, 12, 3, 6),
        x_label="Month",
        y_label="%",
    ),
    xy_chart(
        "chart_curve",
        "line",
        "curve",
        "tenor_months",
        "yield_pct",
        "curve",
        "Yield curve: today vs one year ago",
        position(3, 12, 3, 6),
        x_type="quantitative",
        x_label="Tenor (months)",
        y_label="Yield (%)",
    ),
    xy_chart(
        "chart_oil",
        "line",
        "oil",
        "month",
        "value",
        "series",
        "WTI in USD vs CAD",
        position(0, 18, 3, 6),
        x_label="Month",
        y_label="$ per barrel",
        desc="The gap between the two lines is the exchange-rate effect for Canadians.",
    ),
    xy_chart(
        "chart_passthrough",
        "bar",
        "passthrough",
        "lag_months",
        "corr_core",
        None,
        "Energy → core inflation: correlation by lag",
        position(3, 18, 3, 6),
        x_type="categorical",
        x_label="Lag (months)",
        y_label="Correlation",
        desc="The peak is the pass-through delay.",
    ),
    xy_chart(
        "chart_tariffs",
        "line",
        "tariffs",
        "month",
        "value",
        "series",
        "Effective US tariff rate (%)",
        position(0, 24, 3, 6),
        x_label="Month",
        y_label="Duties / imports (%)",
    ),
    xy_chart(
        "chart_mortgage",
        "line",
        "mortgage",
        "month",
        "value",
        "series",
        "Mortgage renewal shock (%)",
        position(3, 24, 3, 6),
        x_label="Month",
        y_label="Posted 5-year rate (%)",
    ),
]

OPS_PAGE = [
    text(
        "ops_title",
        [
            "# Data operations\n",
            "Freshness of each series against its publication calendar, and what every daily run downloaded.",
        ],
        position(0, 0, 6, 2),
    ),
    xy_chart(
        "chart_freshness",
        "bar",
        "freshness_status",
        "status",
        "series",
        None,
        "Series by freshness status",
        position(0, 2, 2, 6),
        x_type="categorical",
        x_label="Status",
        y_label="Series",
    ),
    table(
        "table_late",
        "freshness_late",
        [
            ("name", "Series", "string"),
            ("source", "Source", "string"),
            ("frequency", "Freq.", "string"),
            ("last_date", "Last observation", "string"),
            ("age_days", "Age (days)", "number"),
            ("max_age_days", "Max age", "number"),
        ],
        "Late or missing series",
        position(2, 2, 4, 6),
    ),
    xy_chart(
        "chart_ingestion",
        "bar",
        "ingestion",
        "day",
        "series",
        "outcome",
        "Ingestion activity — last 30 days",
        position(0, 8, 6, 6),
        x_label="Day",
        y_label="Series",
        desc="'unchanged' = the source published nothing new (SHA-256 identical), so Silver and Gold were skipped.",
    ),
]


def build() -> dict:
    return {
        "datasets": [dataset(name) for name in DATASETS],
        "pages": [
            {"name": "policy", "displayName": "Policy monitor", "pageType": "PAGE_TYPE_CANVAS", "layout": POLICY_PAGE},
            {
                "name": "operations",
                "displayName": "Data operations",
                "pageType": "PAGE_TYPE_CANVAS",
                "layout": OPS_PAGE,
            },
        ],
    }


if __name__ == "__main__":
    OUT.write_text(json.dumps(build(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{OUT} written")
