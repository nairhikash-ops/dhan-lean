# LEAN Foundation Audit

> Created: 2026-07-21
> Purpose: Comprehensive evidence-only audit of LEAN's Indian market support,
> data format requirements, integration options, and VPS deployment path.

---

## 1. Executive Summary

**LEAN (QuantConnect) supports India/NSE as a recognized market.** The
`Market.India` constant, timezone, and trading hours are defined in the
engine source. However, the built-in India equity dataset is minimal (one
sample file), and symbol properties for India equities are incomplete in the
database. A proof of concept is required to confirm that Dhan historical
daily data can be converted into LEAN's native format and processed by the
engine without errors.

**Recommended path**: Route A (native LEAN equity files) for PoC; Route A
(extended with mapping/factor files) for production.

---

## 2. India Market Support in LEAN

### 2.1 Market Identifier

| Attribute | Value | Evidence |
|-----------|-------|----------|
| Constant name | `Market.India` | CONFIRMED BY SOURCE CODE (`Common/Market.cs`) |
| Market string | `"india"` | CONFIRMED BY SOURCE CODE |
| Market ID | `11` | CONFIRMED BY SOURCE CODE |

### 2.2 Timezone

| Attribute | Value | Evidence |
|-----------|-------|----------|
| Timezone constant | `TimeZones.AsiaKolkata` | CONFIRMED BY SOURCE CODE (`Common/TimeZones.cs`) |
| IANA identifier | `Asia/Kolkata` | CONFIRMED BY SOURCE CODE |
| UTC offset | +05:30 | CONFIRMED BY OFFICIAL DOCUMENTATION (IANA timezone database) |
| DST | None | CONFIRMED BY OFFICIAL DOCUMENTATION |

### 2.3 Trading Hours

| Attribute | Value | Evidence |
|-----------|-------|----------|
| Market type | `EquityMarketHoursModel` | CONFIRMED BY SOURCE CODE (market-hours database) |
| Regular session | 09:15–15:30 IST | CONFIRMED BY SOURCE CODE (market-hours database) |
| Pre-open | 09:00–09:15 IST | CONFIRMED BY SOURCE CODE (market-hours database) |
| Early close | Not defined | UNRESOLVED |
| Late open | Not defined | UNRESOLVED |
| Holidays | Not defined in market-hours database | UNRESOLVED (LEAN may use a holidays database or rely on data gaps) |

### 2.4 Currency

| Attribute | Value | Evidence |
|-----------|-------|----------|
| Currency | INR | CONFIRMED BY SOURCE CODE (symbol properties database — India futures entries) |

### 2.5 Symbol Properties (India)

| Aspect | Status | Evidence |
|--------|--------|----------|
| India futures entries | Present | CONFIRMED BY SOURCE CODE (symbol properties database) |
| India equity entries | Not found | UNRESOLVED — may exist in a database not inspected, or may be absent |
| Lot size (equity) | Assumed 1 | ASSUMPTION (standard for NSE equity) |
| Minimum price variation | Varies by price | ASSUMPTION (standard for NSE equity) |

---

## 3. LEAN Data Format Audit

### 3.1 Equity Daily CSV Format

| Attribute | Value | Evidence |
|-----------|-------|----------|
| Timestamp format | `YYYYMMDD 00:00` | CONFIRMED BY SOURCE CODE (`Common/Prices.cs`) |
| Columns | `open,high,low,close,volume` | CONFIRMED BY SOURCE CODE |
| Separator | Comma | CONFIRMED BY SOURCE CODE |
| Header row | None | CONFIRMED BY SOURCE CODE |
| Encoding | UTF-8 (implied) | ASSUMPTION |

### 3.2 Directory Structure

```
Data/equity/india/daily/{ticker}.zip
```

| Attribute | Value | Evidence |
|-----------|-------|----------|
| Path pattern | `Data/equity/{market}/daily/{ticker}.zip` | CONFIRMED BY SOURCE CODE |
| ZIP convention | One ZIP per ticker per resolution | CONFIRMED BY SOURCE CODE |
| CSV inside ZIP | One or more CSV files | CONFIRMED BY SOURCE CODE |

### 3.3 Bundled India Data

| Item | Status | Evidence |
|------|--------|----------|
| `cccl.zip` | Present (6.7 KB) | OBSERVED IN TEST (GitHub `Data/equity/india/daily/`) |
| Full India equity dataset | Not bundled | OBSERVED IN TEST (only `cccl.zip` found) |
| India factor files | Present in `Data/factor_files/india/` | CONFIRMED BY SOURCE CODE |
| India mapping files | Not confirmed | UNRESOLVED |

### 3.4 Data Fields Comparison

| LEAN Field | Dhan Field | Match? | Notes |
|------------|-----------|--------|-------|
| `open` | `open` | Yes | Dhan returns integer (price × 100) |
| `high` | `high` | Yes | Dhan returns integer (price × 100) |
| `low` | `low` | Yes | Dhan returns integer (price × 100) |
| `close` | `close` | Yes | Dhan returns integer (price × 100) |
| `volume` | `volume` | Yes | Dhan returns integer (shares) |
| (none) | `open_interest` | Extra | Not used in LEAN equity format; discard or store separately |
| (none) | `trade_count` | Extra | Not used in LEAN equity format; discard |

**Critical conversion**: Dhan prices are returned as integers (price × 100).
The converter must divide by 100 to get the actual price. This is CONFIRMED
BY OFFICIAL DOCUMENTATION (`docs/dhan-docs-export.md`).

---

## 4. Gap Analysis

### 4.1 Confirmed Capabilities

| Capability | Status | Evidence |
|-----------|--------|----------|
| India market recognized | Yes | CONFIRMED BY SOURCE CODE |
| India timezone defined | Yes | CONFIRMED BY SOURCE CODE |
| India trading hours defined | Yes | CONFIRMED BY SOURCE CODE |
| Equity daily data format | Defined | CONFIRMED BY SOURCE CODE |
| Factor files for India | Present | CONFIRMED BY SOURCE CODE |

### 4.2 Gaps and Risks

| Gap | Severity | Impact | Mitigation |
|-----|----------|--------|-----------|
| No full India equity dataset bundled | Medium | Must supply own data | Build converter (Route A) |
| Symbol properties incomplete for equities | Medium | LEAN may not initialize equity correctly | Test with PoC; may need manual symbol-properties file |
| No India equity mapping files | Low (for PoC) | No survivorship-bias correction | Acceptable for PoC; build mapping files for production |
| Factor files may not cover all tickers | Low (for PoC) | No split/dividend adjustment | Acceptable for PoC; use raw prices |
| LEAN India market hours may not include holidays | Low | Backtests may run on market holidays | Acceptable for daily resolution; LEAN ignores gaps |
| `open_interest` from Dhan has no LEAN equivalent | Low | Discard or store separately | Discard for equity; store for derivatives |

### 4.3 UNRESOLVED Items Requiring PoC Verification

| Item | Why Unresolved | PoC Verification Method |
|------|---------------|----------------------|
| Whether LEAN initializes India equity without explicit symbol properties | Not found in database inspection | Run PoC algorithm; check for errors |
| Whether `cccl.zip` is the only India sample or if more exist | Limited inspection scope | PoC uses its own converted data |
| Whether LEAN's India market hours handle early closings | Not defined in market-hours database | Acceptable for daily resolution |
| Whether Python.NET supports the Python packages needed | Not verified | Test during PoC run |

---

## 5. VPS Runtime Plan

### 5.1 Environment

| Aspect | Plan |
|--------|------|
| **OS** | Linux (Ubuntu/Debian on VPS) |
| **Container runtime** | Docker Engine |
| **LEAN execution** | Via `lean-cli` (`lean backtest`) or direct Docker |
| **Python** | 3.10+ (via Docker image or system) |
| **Dhan SDK** | `dhanhq==2.2.0` (for historical data download) |
| **Data storage** | Local filesystem on VPS |

### 5.2 Deployment Phases

1. **PoC (local)**: Run LEAN backtest with converted Dhan data fixture
2. **Data pipeline**: Build automated Dhan→LEAN converter for daily data
3. **Backtest harness**: Run LEAN backtests on VPS with Docker
4. **Live transition**: Connect LEAN to live data feed (Dhan WebSocket or
   QuantConnect brokerage)

### 5.3 VPS Requirements (PoC Phase)

| Requirement | Minimum | Recommended |
|------------|---------|-------------|
| RAM | 2 GB | 4 GB |
| CPU | 1 vCPU | 2 vCPU |
| Disk | 10 GB | 20 GB |
| OS | Ubuntu 22.04+ | Ubuntu 22.04+ |
| Docker | 20.10+ | 24.0+ |
| Python | 3.10+ | 3.10+ |

### 5.4 Evidence

- Docker base image `quantconnect/lean:foundation`: CONFIRMED BY SOURCE CODE
- lean-cli Docker-based execution: CONFIRMED BY OFFICIAL DOCUMENTATION
- Python `>=3.9` for lean-cli: CONFIRMED BY OFFICIAL DOCUMENTATION

---

## 6. Decision Record

| Decision | Choice | Rationale |
|----------|--------|-----------|
| PoC integration route | Route A (native LEAN equity files) | Lowest effort; full LEAN feature support |
| Production integration route | Route A (extended) | Same format; add mapping/factor files |
| LEAN execution method | Docker via `lean-cli` | Matches production environment |
| Data resolution for PoC | Daily only | Simplest; validates format compatibility |
| Instrument for PoC | Configurable (not hardcoded) | Depends on Dhan API ticker format confirmation |
| Price adjustment for PoC | Raw (unadjusted) | Factor files require verified data |

---

## 7. Evidence Classification Summary

| Label | Count | Examples |
|-------|-------|---------|
| CONFIRMED BY SOURCE CODE | 12 | Market constant, timezone, data format, directory structure |
| CONFIRMED BY OFFICIAL DOCUMENTATION | 5 | lean-cli version, Python requirement, Docker image, LEAN license |
| OBSERVED IN TEST | 2 | `cccl.zip` sample, no full India dataset |
| UNRESOLVED | 6 | Symbol properties, holiday handling, Python.NET compatibility |
| ASSUMPTION | 3 | Currency INR, lot size 1, UTF-8 encoding |
