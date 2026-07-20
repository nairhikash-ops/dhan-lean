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
- No full India equity dataset is bundled with LEAN
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

## Integration Routes

### Route A: Convert Dhan Data → Native LEAN Equity Files

**Approach**: Download Dhan daily data, convert to LEAN CSV format, ZIP into
the expected directory structure, and place under `Data/equity/india/daily/`.

| Aspect | Assessment |
|--------|-----------|
| **Implementation effort** | Medium — one-time converter script |
| **Backtest fidelity** | High — native LEAN data path, full engine support |
| **Normal order simulation** | Full support (LEAN's equity models) |
| **Indicator compatibility** | Full (all LEAN indicators work natively) |
| **Corporate-action handling** | Requires separate mapping/factor files |
| **Universe support** | Full (universe selection, screening) |
| **Live-transition complexity** | Low — same data format for live and backtest |
| **Maintenance burden** | Low — converter runs once per data refresh |

**Pros**: Fastest path to a working backtest; leverages all LEAN features.
**Cons**: Must build mapping/factor files for survivorship-bias-free results;
requires understanding LEAN's exact file format.

### Route B: LEAN Custom Data Classes

**Approach**: Write a Python `CustomData` class that reads Dhan data from
local files and feeds it into LEAN as a custom data source.

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
**Cons**: More code; custom data has subtle differences from native equity
data; harder to use LEAN's equity-specific features (margin, settlement).

### Route C: Custom LEAN History/Data Provider

**Approach**: Implement `IDataProvider` or `IDataFeed` to serve Dhan data
on-demand during backtesting.

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
**Cons**: Significant implementation complexity; requires deep LEAN knowledge;
fragile across LEAN version updates.

### Route D: QuantConnect Brokerage for Live + Dhan for Historical

**Approach**: Use QuantConnect's cloud or a supported brokerage for live
trading, while using Dhan data only for historical backtesting via Route A.

| Aspect | Assessment |
|--------|-----------|
| **Implementation effort** | Low for backtest (Route A), high for live (brokerage migration) |
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

### First Proof of Concept: Route A

**Rationale**:
- Lowest implementation effort for a working backtest
- Native LEAN data path means no custom code to maintain
- Full indicator and order simulation support
- Can validate Dhan-to-LEAN compatibility quickly
- Mapping/factor files are optional for the initial PoC (raw prices are fine)

### Final Production Architecture: Route A (with mapping/factor files)

**Rationale**:
- Native LEAN format is the most battle-tested path
- Mapping files enable survivorship-bias-free backtests
- Factor files enable adjusted-price backtests
- Same data format works for both backtest and live (via custom data provider
  for live feed, or by downloading data periodically)
- Lowest long-term maintenance burden

### When Route B Might Be Preferred

Route B (Custom Data) is preferred if:
- Dhan provides data fields that don't fit LEAN's equity model (e.g., bid-ask
  from Dhan's market feed)
- The project needs to blend Dhan data with other proprietary data in the
  same custom data stream
- Intraday data from Dhan has non-standard timestamp conventions

This decision should be deferred until the PoC validates Route A.

---

## Evidence Summary

| Claim | Evidence |
|-------|----------|
| LEAN equity daily CSV format | CONFIRMED BY SOURCE CODE (LEAN `Data/` directory structure, `LeanData.cs`) |
| Market `"india"` ID `11` | CONFIRMED BY SOURCE CODE (`Common/Market.cs`) |
| NSE trading hours 09:15–15:30 | CONFIRMED BY SOURCE CODE (market-hours database) |
| One sample file `cccl.zip` | OBSERVED IN TEST (GitHub `Data/equity/india/daily/`) |
| No full India dataset bundled | OBSERVED IN TEST (only `cccl.zip` found) |
| Dhan response shape | CONFIRMED BY OFFICIAL DOCUMENTATION (`docs/dhan-docs-export.md`) |
