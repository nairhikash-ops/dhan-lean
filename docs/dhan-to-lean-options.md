# Dhan-to-LEAN Integration Options

> Created: 2026-07-21
> Purpose: Evaluate every viable route for getting Dhan historical data into
> LEAN for backtesting, with effort, fidelity, and maintenance trade-offs.

---

## Dhan Data Shape (from `docs/dhan-docs-export.md`)

The Dhan API v2 `historical_daily_data` endpoint returns daily OHLCV data.
The response structure (CONFIRMED BY OFFICIAL DOCUMENTATION):

```json
{
  "status": "success",
  "data": {
    "open": [...],
    "high": [...],
    "low": [...],
    "close": [...],
    "volume": [...],
    "open_interest": [...]
  }
}
```

Fields are returned as parallel arrays of floats/ints. Timestamps are not
included in the response; they must be reconstructed from the request date
range.

---

## LEAN Native Equity Data Format

### Directory Structure

```
Data/
  equity/
    india/
      daily/
        {ticker}.zip
      map/
        {ticker}.csv
      factor/
        {ticker}.csv
```

### CSV Format (daily, uncompressed inside ZIP)

```
YYYYMMDD 00:00,open,high,low,close,volume
```

- **Timestamp**: `YYYYMMDD 00:00` (market close date, midnight)
- **Fields**: open, high, low, close, volume (5 columns)
- **Separator**: comma
- **No header row**
- **No trade count or open interest columns**

### ZIP Convention

- One ZIP file per ticker per resolution
- Filename: `{ticker}.zip`
- Inside: one or more CSV files (can be split by year)
- LEAN reads the ZIP transparently

### Market Identifier

- Market string: `"india"` (CONFIRMED BY SOURCE CODE: `Common/Market.cs`)
- Market ID: `11`

### Timezone

- Exchange timezone: `Asia/Kolkata` (IST, UTC+05:30)
- No daylight saving time

### NSE Trading Hours

- Regular session: 09:15–15:30 IST
- Pre-open: 09:00–09:15 IST

### Symbol Properties (India)

- Currency: INR
- Lot size: 1 (equity)
- Minimum price variation: varies by price level
- Leverage: 1x (cash segment)

### Bundled Data

- One sample file exists: `Data/equity/india/daily/cccl.zip` (6.7 KB)
- No full India dataset bundled with LEAN
- No India equity symbol properties entries confirmed in the database
- India market hours ARE defined in the market-hours database

### Mapping Files

- LEAN uses mapping files to track ticker changes (e.g., RIL → RELIANCE)
- Format: `{ticker}.csv` with columns: date, mapped_symbol
- Must be provided or built for trustworthy survivorship-bias-free backtests

### Factor Files

- LEAN uses factor files for split/dividend adjustment
- Format: `{ticker}.csv` with columns: date, price_factor, split_factor
- Required for adjusted backtests; optional for raw-price backtests

---

## Approved Architecture: 1-Minute Permanent Data Pipeline

The project follows a 5-stage decoupled data architecture:

```text
Dhan API
  └──> Stage 1: Permanent Raw Unadjusted 1-Minute Archive
        └──> Stage 2: Validation & Resumable Download State
              └──> Stage 3: Higher Intervals Generated on Demand (5m, 15m, 30m, 60m, Daily)
                    └──> Stage 4: Temporary/Disposable LEAN-Native Exports
                          └──> Stage 5: Backtests & Permanent Result Records
```

### Approved MVP Scope

- **Data Source**: Dhan API v2 (`intraday_minute_data` primary for permanent raw 1-minute storage; `historical_daily_data` optional future validation).
- **Asset Class / Market**: NSE Equity pilot only (limited to a controlled list of liquid symbols and date ranges).
- **Primary Resolution**: 1-minute unadjusted OHLCV candles.
- **Storage Management**:
  - Configurable storage root path (environment variable / configuration driven).
  - Default current storage root path: `/srv/market-data` (current server-local default; default, not a hardcoded system requirement).
  - Storage abstraction supports future migration to larger internal storage without pipeline code changes.
- **Download & Ingestion Resilience**:
  - Request chunking aligned with Dhan rate limits (Quote: 1/s, Data: 5/s, 100k/day).
  - Interruption-safe, resumable download state tracking per symbol/date chunk.
  - Duplicate candle prevention and idempotent append/merge logic.
- **Data Validation & Quality**:
  - Timestamp ordering and validation.
  - OHLC relationship checks ($High \ge Open, High \ge Low, High \ge Close, Low \le Open, Low \le Close$).
  - Negative volume is invalid; zero volume may be retained or flagged according to source semantics.
  - Missing intervals reported as gaps (not automatically treated as errors while calendar/special-session handling is postponed).
- **Derived Candles & LEAN Export**:
  - Derived 5m, 15m, 30m, 60m, and daily candles aggregated on demand from 1m raw archive.
  - Temporary and disposable LEAN-native CSV-in-ZIP export (`Data/equity/india/minute/{symbol}.zip` and `daily/{symbol}.zip`) generated on demand into `{STORAGE_ROOT}/lean/` (default `/srv/market-data/lean/`).

### Explicitly Postponed Scope

The following features are intentionally out of scope for the initial MVP pipeline:
- Symbol-change and corporate-action continuity tracking.
- Stock splits, bonuses, rights issues, dividends, and price adjustments (raw prices used for initial pilot).
- NSE holiday calendar integration and special trading sessions (e.g., Muhurat trading).
- Delisted instruments and historical survivorship-bias corrections.
- Derivatives data: Futures, Options, Open Interest (OI), tick-level feeds, and order-book depth.
- Paper trading and live order execution.

---

## Integration Routes

### Route A: Convert Raw Archived Data → Native LEAN Equity Files (Approved Path)

**Approach**: Download Dhan 1m data via `intraday_minute_data` to raw archive (`{STORAGE_ROOT}/raw/`, default `/srv/market-data/raw/`), validate and store, then export on demand to temporary/disposable LEAN CSV-in-ZIP format under `{STORAGE_ROOT}/lean/`.

| Aspect | Assessment |
|--------|-----------|
| **Implementation effort** | Medium — one-time converter script from raw archive |
| **Backtest fidelity** | High — native LEAN data path, full engine support |
| **Normal order simulation** | Full support (LEAN's equity models) |
| **Indicator compatibility** | Full (all LEAN indicators work natively) |
| **Corporate-action handling** | Requires separate mapping/factor files |
| **Universe support** | Full (universe selection, screening) |
| **Live-transition complexity** | Low — same data format for live and backtest |
| **Maintenance burden** | Low — converter runs once per data refresh |

**Pros**: Native LEAN data path; leverage raw archive for multiple interval backtests.
**Cons**: Requires building export formatting logic; initial pilot relies on unadjusted raw prices.

### Route B: LEAN Custom Data Classes (Deferred Alternative)

**Approach**: Write a Python `CustomData` class that reads Dhan data from local files and feeds it into LEAN as a custom data source.

| Aspect | Assessment |
|--------|-----------|
| **Implementation effort** | Medium — custom data class + reader |
| **Backtest fidelity** | High — data enters LEAN's pipeline |
| **Normal order simulation** | Full (equity + custom data coexist) |
| **Indicator compatibility** | Full (indicators apply to custom data) |
| **Corporate-action handling** | Must handle separately |
| **Universe support** | Limited — custom data has different universe semantics |
| **Live-transition complexity** | Medium — custom data provider must be maintained |
| **Maintenance burden** | Medium — custom class must track LEAN API changes |

**Pros**: More flexible; can include extra fields (e.g., open interest).
**Cons**: More code; custom data has subtle differences from native equity data.

### Route C: Custom LEAN History/Data Provider (Deferred Alternative)

**Approach**: Implement `IDataProvider` or `IDataFeed` to serve Dhan data on-demand during backtesting.

| Aspect | Assessment |
|--------|-----------|
| **Implementation effort** | High — deep LEAN internals |
| **Backtest fidelity** | High — if implemented correctly |
| **Normal order simulation** | Full |
| **Indicator compatibility** | Full |
| **Corporate-action handling** | Must implement in provider |
| **Universe support** | Full |
| **Live-transition complexity** | High — provider must handle live streams |
| **Maintenance burden** | High — LEAN internals change between versions |

**Pros**: Most architecturally clean; data provider abstraction is LEAN-native.
**Cons**: Significant implementation complexity; fragile across LEAN version updates.

### Route D: QuantConnect Brokerage for Live + Dhan for Historical (Deferred Alternative)

**Approach**: Use QuantConnect's cloud or a supported brokerage for live trading, while using Dhan data only for historical backtesting via Route A.

| Aspect | Assessment |
|--------|-----------|
| **Implementation effort** | Low for backtest (Route A), high for live |
| **Backtest fidelity** | High (same as Route A) |
| **Normal order simulation** | Full |
| **Indicator compatibility** | Full |
| **Corporate-action handling** | QuantConnect provides for their data |
| **Universe support** | Full |
| **Live-transition complexity** | Very high — different data source for live vs backtest |
| **Maintenance burden** | High — maintaining two data pipelines |

**Pros**: Leverages QuantConnect's ecosystem.
**Cons**: Defeats the purpose of using Dhan; adds complexity and cost.

---

## Recommendation

### First Proof of Concept: Route A from Permanent Raw Archive

**Rationale**:
- Lowest implementation effort for a working backtest.
- Native LEAN data path means no custom engine code to maintain.
- Preserves raw 1-minute data permanently on configured storage root (`{STORAGE_ROOT}/raw/`, default `/srv/market-data/raw/`), enabling on-demand generation of any higher interval (5m, 15m, 30m, 60m, daily) without re-fetching from Dhan. Temporary LEAN export files (`{STORAGE_ROOT}/lean/`) remain disposable and reproducible on demand.

---

## Evidence Summary

| Claim | Evidence |
|-------|----------|
| LEAN equity daily/minute CSV format | CONFIRMED BY SOURCE CODE (LEAN `Data/` directory structure, `LeanData.cs`) |
| Market `"india"` ID `11` | CONFIRMED BY SOURCE CODE (`Common/Market.cs`) |
| NSE trading hours 09:15–15:30 | CONFIRMED BY SOURCE CODE (market-hours database) |
| One sample file `cccl.zip` | OBSERVED IN TEST (GitHub `Data/equity/india/daily/`) |
| No full India dataset bundled | OBSERVED IN TEST (only `cccl.zip` found) |
| Dhan response shape | CONFIRMED BY OFFICIAL DOCUMENTATION (`docs/dhan-docs-export.md`) |
