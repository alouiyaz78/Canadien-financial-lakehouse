-- Databricks notebook source
-- MAGIC %md
-- MAGIC # 05 · Analysis — one chart per cell
-- MAGIC Exploratory SQL on the Gold BI tables, one question per cell. Run a cell, then **+ → Visualization**
-- MAGIC to chart it (suggested chart type in each heading). The same queries feed the AI/BI dashboard
-- MAGIC `dashboards/cfl_dashboard.lvdash.json`, deployed by the bundle.
-- MAGIC
-- MAGIC All values are at **reference dates** (September CPI is shown in September).

-- COMMAND ----------

USE CATALOG workspace;
USE SCHEMA cfl;

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## 1 · Policy rate vs Taylor rule — *line, x = month, y = value, color = series*
-- MAGIC Rule = 0.75 (real neutral) + core inflation + 0.5 × (core − 2) − 0.5 × 2 × unemployment gap.
-- MAGIC Policy below the rule = room to hike; the 2020 gap is the effective lower bound, 2021–22 the
-- MAGIC "transitory" period.

-- COMMAND ----------

SELECT month, series, value
FROM bi_mart_macro_monthly
LATERAL VIEW stack(2, 'Policy rate', policy_rate, 'Taylor rule', taylor_rule_rate) s AS series, value
WHERE month >= DATE'2000-01-01' AND value IS NOT NULL
ORDER BY month, series;

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## 2 · Inflation vs the 1–3 % target band — *line, color = measure*

-- COMMAND ----------

SELECT month, measure, value
FROM bi_mart_macro_monthly
LATERAL VIEW stack(5,
    'Headline CPI', cpi_headline_yoy,
    'CPI-trim', cpi_trim,
    'CPI-median', cpi_median,
    'Band low (1%)', target_low,
    'Band high (3%)', target_high) s AS measure, value
WHERE month >= DATE'2015-01-01' AND value IS NOT NULL
ORDER BY month, measure;

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## 3 · Hawkish / dovish scorecard — *table; the sum of `signal` is the net stance*

-- COMMAND ----------

SELECT indicator, round(latest_value, 2) AS latest_value, unit, reference_month, signal, signal_label, rationale
FROM bi_mart_policy_signals
ORDER BY signal DESC, indicator;

-- COMMAND ----------

SELECT sum(signal) AS net_stance,
       count_if(signal = 1) AS hawkish_signals,
       count_if(signal = -1) AS dovish_signals
FROM bi_mart_policy_signals;

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## 4 · Yield curve: today vs one year ago — *line, x = tenor_months, color = curve*

-- COMMAND ----------

WITH last_day AS (SELECT max(date) AS d FROM bi_fact_yield_curve),
     year_ago AS (SELECT max(date) AS d FROM bi_fact_yield_curve, last_day WHERE date <= date_sub(last_day.d, 365))
SELECT 'Today' AS curve, c.tenor, c.tenor_months, c.yield_pct
FROM bi_fact_yield_curve c JOIN last_day ON c.date = last_day.d
UNION ALL
SELECT 'One year ago', c.tenor, c.tenor_months, c.yield_pct
FROM bi_fact_yield_curve c JOIN year_ago ON c.date = year_ago.d
ORDER BY curve, tenor_months;

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## 5 · Oil shock: WTI in USD vs CAD — *line*. The gap is the exchange-rate effect.

-- COMMAND ----------

SELECT month, series, value
FROM bi_mart_macro_monthly
LATERAL VIEW stack(2, 'WTI (USD)', wti_usd, 'WTI (CAD)', wti_cad) s AS series, value
WHERE month >= DATE'2020-01-01' AND value IS NOT NULL
ORDER BY month, series;

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## 6 · Energy → core pass-through — *bar, x = lag_months, y = corr_core*. The peak is the delay.

-- COMMAND ----------

SELECT lag_months, round(corr_core, 3) AS corr_core, round(corr_headline, 3) AS corr_headline, n_months
FROM bi_mart_energy_passthrough
ORDER BY lag_months;

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## 7 · Effective US tariff rates (duties paid / import value) — *line, color = partner*

-- COMMAND ----------

SELECT month, partner, value
FROM bi_mart_macro_monthly
LATERAL VIEW stack(3,
    'Canada', us_tariff_rate_on_canada,
    'Mexico', us_tariff_rate_on_mexico,
    'China', us_tariff_rate_on_china) s AS partner, value
WHERE month >= DATE'2023-01-01' AND value IS NOT NULL
ORDER BY month, partner;

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## 8 · Mortgage renewal shock — *line*: posted 5-year rate today vs the rate signed 5 years earlier

-- COMMAND ----------

SELECT month, series, value
FROM bi_mart_macro_monthly
LATERAL VIEW stack(2,
    'Rate today', mortgage_5y,
    'Rate at origination (5 years earlier)', mortgage_5y_at_origination) s AS series, value
WHERE month >= DATE'2015-01-01' AND value IS NOT NULL
ORDER BY month, series;

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## 9 · Data health — freshness status per series (*bar*) and the late ones (*table*)

-- COMMAND ----------

SELECT status, count(*) AS series
FROM freshness_report
GROUP BY status
ORDER BY series DESC;

-- COMMAND ----------

SELECT name, source, frequency, last_date, age_days, max_age_days
FROM freshness_report
WHERE status IN ('late', 'missing')
ORDER BY age_days DESC;

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## 10 · Ingestion activity — *bar, x = day, y = series, color = outcome*

-- COMMAND ----------

SELECT to_date(ingested_at) AS day,
       CASE WHEN status = 'error' THEN 'error' WHEN changed THEN 'new data' ELSE 'unchanged' END AS outcome,
       count(*) AS series
FROM bronze_ingestion_log
WHERE to_date(ingested_at) >= date_sub(current_date(), 30)
GROUP BY ALL
ORDER BY day, outcome;
