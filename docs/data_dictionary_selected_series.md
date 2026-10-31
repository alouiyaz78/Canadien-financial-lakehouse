# Data Dictionary — Canadian Financial Lakehouse
### Selected series from the Bank of Canada Valet API

This document describes the 27 series selected during Phase 1 (Data Discovery): their exact financial meaning, time horizon (short/medium/long term), frequency, and analytical relevance for the banking and financial sector.

> **Methodological note**: explanations below are based on the well-known nature of these standard macro-financial indicators (policy rate, yield curve, FX, CPI, monetary aggregates). Empirical verification (actual coverage dates, latest observation, missing values) was performed in Phase 1 (notebook `02_series_metadata_verification`) and is reflected in the frequency and range figures below.

---

## 1. Interest Rates — Policy Rate

### `CBC20210` — Target for the overnight rate (V39079)
- **Definition**: The Bank of Canada's target rate for overnight funding, set at 8 scheduled policy announcements per year. It is the rate at which major financial institutions lend to each other overnight.
- **Horizon**: **Very short-term instrument**, but structurally important — its level influences every other rate in the economy (monetary policy transmission).
- **Publication frequency**: Changes only at policy announcements (~8x/year), but published daily at a constant value between announcements.
- **Why it matters**: The starting point of any monetary policy analysis. A rate hike raises the cost of credit throughout the economy (mortgages, commercial loans, credit cards) with a transmission lag of several months to a year.
- **Financial reading**: A high rate = restrictive monetary policy (fighting inflation). A low rate = accommodative policy (supporting growth).

---

## 2. Fixed Income — Bonds and Treasury Bills

These series form the Canadian **yield curve** — one of the most widely used tools in finance for reading the state of the economy.

### `TB.CDN.30D.MID`, `TB.CDN.60D.MID`, `TB.CDN.90D.MID`, `TB.CDN.180D.MID`, `TB.CDN.1Y.MID` — Treasury bills (1, 2, 3, 6 months, 1 year)
- **Definition**: Yields on very short-term (≤1 year) Government of Canada debt securities. Considered "risk-free" (the Canadian government does not default).
- **Horizon**: **Short-term** (1 month to 1 year).
- **Frequency**: Daily.
- **Financial reading**: These rates track the policy rate very closely — they reflect market expectations of the Bank of Canada's next moves. The 3-month bill (`90D`) is the most widely cited benchmark in financial media.

### `BD.CDN.2YR.DQ.YLD` — 2-year bond
- **Horizon**: **Short-to-medium term**.
- **Financial reading**: Mostly reflects 2-year monetary policy expectations. Highly sensitive to Bank of Canada decisions.

### `BD.CDN.3YR.DQ.YLD` — 3-year bond
- **Horizon**: **Medium-term**.
- **Financial reading**: Intermediate point on the curve, less watched individually but useful for smoothing the full curve.

### `BD.CDN.5YR.DQ.YLD` — 5-year bond
- **Horizon**: **Medium-term**.
- **Financial reading**: **Highly important for the Canadian banking sector** — it is the reference rate banks use to price the 5-year fixed mortgage (the most popular mortgage product in Canada). A rise in this yield feeds through almost directly into `V80691335` (5-year mortgage rate) below.

### `BD.CDN.7YR.DQ.YLD` — 7-year bond
- **Horizon**: **Medium-to-long term**.
- **Financial reading**: Less used in day-to-day commercial practice, mainly useful for analyzing the full shape of the curve.

### `BD.CDN.10YR.DQ.YLD` — 10-year bond
- **Horizon**: **Long-term**.
- **Financial reading**: THE global long-term benchmark in finance. Used to compare "country risk," discount long-term cash flows, and benchmark corporate bonds. The spread with the US 10-year is closely watched by investors.

### `BD.CDN.LONG.DQ.YLD` — Long-term bond (typically 30 years)
- **Horizon**: **Very long-term**.
- **Financial reading**: Reflects very long-term inflation and growth expectations. Used by pension funds and insurers for asset-liability duration matching.

### 💡 Key insight — the yield curve (2-year vs 10-year)
The spread between the 10-year and the 2-year (`BD.CDN.10YR.DQ.YLD - BD.CDN.2YR.DQ.YLD`) is **one of the most closely watched macro-financial signals in the world**. Normally positive (long-term yields exceed short-term ones). When it turns negative (inverted curve), it has historically been a leading signal of recession — an excellent metric to visualize in the Power BI dashboard.

---

## 3. Foreign Exchange — Daily Exchange Rates

### `FXUSDCAD` — USD/CAD
- **Definition**: Value of one US dollar expressed in Canadian dollars.
- **Horizon**: Daily data, but relevant across scales (intraday trading up to multi-year trend analysis).
- **Financial reading**: The most important pair for Canada — trade with the US accounts for roughly 75% of Canadian exports. Strongly correlated with oil prices (Canada being a commodity exporter) and with the Canada-US interest rate differential.

### `FXEURCAD`, `FXGBPCAD`, `FXJPYCAD`, `FXCHFCAD`, `FXCNYCAD` — Major currencies vs CAD
- **Horizon**: Daily.
- **Financial reading**:
  - **EUR/CAD, GBP/CAD**: trade exposure to Europe.
  - **JPY/CAD**: the yen is often used as a "safe-haven" currency — useful for tracking risk-off market moves.
  - **CHF/CAD**: the Swiss franc is the archetypal safe-haven currency.
  - **CNY/CAD**: trade exposure to China, Canada's second-largest trading partner.

### 💡 Key insight — interest rate parity
The policy rate spread between Canada and the US explains much of the medium-term movement in USD/CAD (interest rate parity theory). Comparing `CBC20210` with the evolution of `FXUSDCAD` is an excellent analytical exercise for the portfolio.

---

## 4. Inflation — CPI and Core Measures

### `INDINF_CPI_M` — CPI inflation (monthly)
- **Definition**: Percentage change in the reference basket of goods and services (Consumer Price Index), month-over-month or year-over-year.
- **Horizon**: **Short-to-medium term** in its publication frequency, but interpreted over trends spanning several months/quarters.
- **Financial reading**: The "headline" inflation figure — the one reported in the media. Bank of Canada's official target: 2%, within a tolerance band of 1% to 3%.

### `CPI_COMMON`, `CPI_MEDIAN`, `CPI_TRIM` — Core inflation measures
- **Definition**:
  - **CPI-trim**: excludes basket components with the most extreme price changes (both high and low) each month.
  - **CPI-median**: takes the median price change among all basket components.
  - **CPI-common**: measures price movements common across all categories (a different statistical approach based on a factor model).
- **Horizon**: Monthly, interpreted as a trend.
- **Financial reading**: These are **the three measures the Bank of Canada itself prioritizes** for monetary policy decisions, since they filter out one-off volatility (e.g., an oil price shock) to reveal the underlying inflation trend. If headline CPI is volatile but these three measures remain stable around 2%, the Bank is less likely to act.

---

## 5. Monetary Aggregates

### `M1PP_12MTH` — M1++ (year-over-year growth)
- **Definition**: A measure of the most "liquid" money supply — currency in circulation plus demand deposits and chequing accounts at banks, credit unions, and trust companies.
- **Horizon**: Monthly, but a **leading indicator** — its movements often precede inflation/growth by several quarters.
- **Financial reading**: Rapid M1++ growth often signals an upcoming acceleration in spending and potentially inflation.

### `M2PP_12MTH` — M2++ (year-over-year growth)
- **Definition**: M1++ plus term deposits, savings accounts, and other lower-liquidity savings instruments.
- **Horizon**: Monthly, a leading indicator with a slightly longer horizon than M1++.
- **Financial reading**: A broader measure of available liquidity in the economy; useful alongside M1++ to distinguish "dormant" savings from money ready to be spent.

---

## 6. Banking — Mortgage Rates

### `V80691333` — Conventional mortgage: 1-year
- **Horizon**: **Short-term** product (annual renewal).
- **Financial reading**: Tracks the policy rate and T-bills very closely — borrowers choosing this term are betting on falling rates ahead.

### `V80691334` — Conventional mortgage: 3-year
- **Horizon**: **Medium-term**.
- **Financial reading**: A compromise between flexibility and stability; tracks the 3-to-5-year bond more closely.

### `V80691335` — Conventional mortgage: 5-year
- **Horizon**: **Medium-to-long term** — **Canada's most popular mortgage product**.
- **Financial reading**: Directly indexed to the 5-year Government of Canada bond (`BD.CDN.5YR.DQ.YLD`) plus a bank profit margin (the "spread"). Tracking the gap between these two series over time shows how the cost of bank credit evolves independently of the government's cost of funding — a directly usable insight for a banking-focused portfolio.

---

## Frequency and Coverage Summary (verified empirically)

| Series | Domain | Horizon | Actual frequency | Coverage |
|---|---|---|---|---|
| CBC20210 | Interest Rates | Structural (short-term reference) | Daily (constant between announcements) | 2001–present |
| TB.CDN.30D/60D/90D/180D/1Y | Fixed Income | Short-term (1–12 months) | Daily | 2001–present |
| BD.CDN.2YR/3YR | Fixed Income | Short-to-medium term | Daily | 2001–present |
| BD.CDN.5YR/7YR | Fixed Income | Medium-term | Daily | 2001–present |
| BD.CDN.10YR | Fixed Income | Long-term | Daily | 2001–present |
| BD.CDN.LONG | Fixed Income | Very long-term | Daily | 2001–present |
| FX*CAD (6 currencies) | Foreign Exchange | Short-term (analyzable as long trend) | Daily | 2017–present (API limitation, no earlier data available) |
| INDINF_CPI_M | Inflation | Short-to-medium term | Monthly | 1993–present |
| CPI_COMMON/MEDIAN/TRIM | Inflation | Medium-term (trend) | Monthly | 1995–present |
| M1PP_12MTH/M2PP_12MTH | Monetary Aggregates | Leading indicator (medium-term) | Monthly | 1969–present |
| V80691333/334/335 | Banking | Short to medium-long term | **Weekly** (confirmed empirically, max_gap_days = 7) | 1975/1980–present |

---

## Data Quality Notes (from empirical verification)

All 27 series passed structural quality checks with no missing values, no non-numeric entries, and no duplicate dates. A few extreme values are real historical facts, not data errors:

- Mortgage rates reaching ~21% in the early 1980s (Bank of Canada's inflation-fighting era).
- Slightly negative short-term Treasury bill yields (`TB.CDN.60D.MID`, min -0.01%) during periods of market stress.
- CPI monthly deflation as low as -0.9% during major economic shocks.

Foreign exchange series are limited to 2017 onward — a known limitation of the Valet API's daily FX data, not a selection issue.

---

## Next Step

Phase 2 is implemented in `src/cfl/` (see the README): the selection above has been extended with real-economy,
commodity, expectations and US series in `config/sources.yaml`, and is ingested into a Bronze/Silver/Gold
Parquet lakehouse that produces the monthly model table.
