> Historical pre-retirement record (non-active): retained for LEAN review provenance; it does not describe current provider dependencies.

# Independent LEAN Foundation Review

> Created: 2026-07-21
> Reviewer: Independent verification against official sources
> Basis: Commit `b61fc86` on `feature/lean-foundation`
> Status: NOT READY — critical corrections required before PoC

---

## 1. Claim-by-Claim Verification

### 1. LEAN Engine Version

| Claim | Classification | Evidence |
|-------|---------------|----------|
| Latest formal release `v2.4.0.1` (2024-08-08) | **VERIFIED** | GitHub tag `v2.4.0.1` exists at `github.com/QuantConnect/Lean/tree/v2.4.0.1` |
| Latest commit tag `17932` (2026-07-17) | **CORRECT BUT INCOMPLETE** | Commit tags exist on master, but `17932` is ahead of `v2.4.0.1`. The documents conflate the two — `v2.4.0.1` is the latest formal release, while `17932` is a rolling commit on master. These are different checkpoints. |

**Correction required**: `lean-version-matrix.md` and `lean-foundation-audit.md` must distinguish between the formal release tag (`v2.4.0.1`) and rolling commit tags on master. The PoC should pin to `v2.4.0.1` (the latest formal release), not an arbitrary commit.

### 2. LEAN CLI Version

| Claim | Classification | Evidence |
|-------|---------------|----------|
| `lean==1.0.227` | **VERIFIED** | PyPI JSON API confirms `lean 1.0.227`, released 2026-06-26 |
| Python `>=3.9` | **VERIFIED** | PyPI metadata: `Requires: Python >=3.9` |

### 3. Docker Requirements

| Claim | Classification | Evidence |
|-------|---------------|----------|
| Docker required for `lean backtest` | **VERIFIED** | lean-cli README: "many commands in the CLI require Docker to run" |
| Base image `quantconnect/lean:foundation` | **VERIFIED** | `DockerfileLeanFoundation` at `Lean/DockerfileLeanFoundation` |
| Entry point `dotnet QuantConnect.Lean.Launcher.dll` | **VERIFIED** | Dockerfile in `Lean/Dockerfile` |

### 4. Python Version and Python.NET

| Claim | Classification | Evidence |
|-------|---------------|----------|
| Python.NET for Python algorithms | **VERIFIED** | TradeBar.cs uses `QuantConnect.pythonnet`; Lean README mentions Python support |
| Python `>=3.10` for this project | **VERIFIED** | DhanHQ SDK requires `>=3.10`; lean-cli requires `>=3.9`; project floor is `>=3.10` |

### 5. Windows vs Linux

| Claim | Classification | Evidence |
|-------|---------------|----------|
| Cross-platform | **VERIFIED** | Lean README: "Lean drives the web based algorithmic trading platform QuantConnect" with Windows/Linux/macOS support |
| Docker images run on Linux | **VERIFIED** | Docker foundation image is Linux-based |

### 6. India/NSE Market Identifier

| Claim | Classification | Evidence |
|-------|---------------|----------|
| `Market.India = "india"` | **VERIFIED** | `Common/Market.cs` line: `public const string India = "india";` |
| Market ID `11` | **VERIFIED** | `Tuple.Create(India, 11)` in `HardcodedMarkets` |

### 7. India Timezone and Trading Hours

| Claim | Classification | Evidence |
|-------|---------------|----------|
| `TimeZones.Kolkata` = `Asia/Kolkata` | **VERIFIED** | `Common/TimeZones.cs`: `public static readonly DateTimeZone Kolkata = DateTimeZoneProviders.Tzdb["Asia/Kolkata"];` |
| NSE hours 09:15–15:30 | **CORRECT BUT INCOMPLETE** | Market-hours database confirms: premarket 09:00–09:15, market 09:15–15:30, postmarket 15:40–16:00. The documents omit the pre-market and post-market sessions. |
| Holidays defined | **VERIFIED** | `Equity-india-[*]` entry has 227 holiday dates (2004–2030) |
| No early close definitions | **VERIFIED** | `earlyCloses: {}` for all India entries |

**Correction required**: `lean-foundation-audit.md` and `lean-version-matrix.md` must include pre-market (09:00–09:15) and post-market (15:40–16:00) sessions. These affect fill-forward behavior and scheduled events.

### 8. INR Currency Support

| Claim | Classification | Evidence |
|-------|---------------|----------|
| Currency INR | **UNRESOLVED** | Symbol-properties database JSON returned 404 at the expected path. Cannot confirm INR currency is defined for India equity in the symbol-properties database. |

### 9. Indian Equity Symbol Properties

| Claim | Classification | Evidence |
|-------|---------------|----------|
| India futures entries present | **UNRESOLVED** | Symbol-properties database JSON not accessible at the expected path |
| India equity entries absent | **UNRESOLVED** | Same — cannot verify |
| Lot size 1 | **ASSUMPTION** | Not confirmed from any source |
| Minimum price variation | **ASSUMPTION** | Not confirmed from any source |

**Impact**: If LEAN requires symbol properties to initialize an equity and none exist for India equity, `AddEquity("TICKER", Market.India)` may fail. This is a **blocking risk** for the PoC.

### 10. Native Equity-Data Directory Structure

| Claim | Classification | Evidence |
|-------|---------------|----------|
| Path: `Data/equity/{market}/daily/{ticker}.zip` | **VERIFIED** | `Data/readme.md`: "Hour, Daily Financial Data: `/data/securityType/marketName/resolution/ticker.zip`" |
| ZIP per ticker per resolution | **VERIFIED** | Same source |

### 11. ZIP Filename and Internal CSV Filename

| Claim | Classification | Evidence |
|-------|---------------|----------|
| ZIP filename: `{ticker}.zip` | **VERIFIED** | `Data/equity/readme.md`: "Each file contains all bars available for this ticker. e.g. `/data/equity/usa/hour/aapl.zip`" |
| CSV filename inside ZIP: `{ticker}.csv` | **VERIFIED** | Same source: "The zip file contains 1 CSV file named the same as the ticker (`aapl.csv`)" |

### 12. Daily Equity CSV Field Order

| Claim | Classification | Evidence |
|-------|---------------|----------|
| `DateTime,Open,High,Low,Close,Volume` | **VERIFIED** | `Data/equity/readme.md`: DateTime, Open, High, Low, Close, Volume — 6 columns, no header |
| Separator: comma | **VERIFIED** | Same source |

### 13. Timestamp Convention for Daily Bars

| Claim | Classification | Evidence |
|-------|---------------|----------|
| `YYYYMMDD 00:00` | **VERIFIED** | Actual `cccl.zip` from `Data/equity/india/daily/` contains 495 daily bars, all with timestamp `YYYYMMDD 00:00`. The `Data/equity/readme.md` shows `20131001 09:00` for US equity, but India daily bars use `00:00`. |

**Confirmed by runtime inspection**: India daily bars use `YYYYMMDD 00:00` (midnight), NOT market close time. The converter must produce timestamps in this format.

### 14. Price Scaling Requirements

| Claim | Classification | Evidence |
|-------|---------------|----------|
| "Dhan returns integer (price × 100)" | **INCORRECT** | Dhan API docs (`dhan-docs-export.md` lines 768-771): `open`, `high`, `low`, `close` are `float` type. Dhan returns actual prices (e.g., `1234.56`), NOT integers × 100. |
| "LEAN divides by 100" | **INCORRECT** | `TradeBar.cs`: `private const decimal _scaleFactor = 1 / 10000m;` — LEAN divides by 10,000 for equity data |
| Converter must divide by 100 | **INCORRECT** | Converter must multiply Dhan float prices by 10,000 to get LEAN's deci-cents format |

**Correction required**: The `lean-foundation-audit.md` data fields comparison table is wrong. The correct conversion is:
- Dhan returns: `1234.56` (float, actual price in INR)
- LEAN expects: `12345600` (deci-cents, price × 10,000)
- Converter: `Dhan_price × 10000 = LEAN_value`

### 15. Volume Representation

| Claim | Classification | Evidence |
|-------|---------------|----------|
| Volume as integer (shares) | **VERIFIED** | Dhan API docs: `volume` is `int` type. LEAN equity readme: "Volume - Number of shares traded" |

### 16. Map-File Requirements

| Claim | Classification | Evidence |
|-------|---------------|----------|
| Map files exist for India | **VERIFIED** | `Data/equity/india/map_files/` contains `3mindia.csv` |
| Map file format: `date,ticker` | **VERIFIED** | `3mindia.csv` content: `19990101,birla3m\n20040615,birla3m\n20501231,3mindia` |
| Map files required for PoC | **CORRECT BUT INCOMPLETE** | Map files are not strictly required for a single-instrument PoC without survivorship bias. LEAN will use the ticker as-is if no map file exists. However, for production backtesting, map files are essential. |

### 17. Factor-File Requirements

| Claim | Classification | Evidence |
|-------|---------------|----------|
| Factor files exist for India | **VERIFIED** | `Data/equity/india/factor_files/` contains `cccl.csv` |
| Factor file format: `date,price_factor,split_factor,reference_price` | **VERIFIED** | `cccl.csv` content: `20100104,0.9800619,0.2,413` etc. |
| Factor files required for PoC | **CORRECT BUT INCOMPLETE** | Factor files are not strictly required for raw-price backtesting. LEAN will use raw prices if no factor file exists. For adjusted-price backtesting, factor files are essential. |

### 18. Split and Dividend Handling

| Claim | Classification | Evidence |
|-------|---------------|----------|
| Factor files handle splits/dividends | **VERIFIED** | Factor file format includes `split_factor` column |
| No factor file for test equity | **ASSUMPTION** | Must be confirmed at runtime |

### 19. AddEquity with Locally Converted Data

| Claim | Classification | Evidence |
|-------|---------------|----------|
| `AddEquity("TICKER", Market.India)` works | **UNRESOLVED** | No evidence that LEAN can initialize an India equity without symbol properties. The `Equity-india-[*]` market hours entry exists, but symbol properties may be missing. |

**Blocking risk**: If `AddEquity` fails because no symbol properties exist for the test ticker, the PoC cannot proceed via Route A.

### 20. Route A Suitability

| Claim | Classification | Evidence |
|-------|---------------|----------|
| Route A suitable for PoC | **CORRECT BUT INCOMPLETE** | Route A is the lowest-effort path, but the price scaling and timestamp conventions must be correct. The documents have errors in both. |

### 21. Deterministic PoC Without Licensed Datasets

| Claim | Classification | Evidence |
|-------|---------------|----------|
| PoC can run without QuantConnect datasets | **VERIFIED** | LEAN reads local files. The `lean backtest` command accepts custom data via the `Data/` directory. No QuantConnect subscription required for local backtesting with local data. |

---

## 2. Corrections Required

### Critical Errors

| File | Section | Error | Correction |
|------|---------|-------|------------|
| `lean-foundation-audit.md` | Data Fields Comparison | "Dhan returns integer (price × 100)" | Dhan returns `float` prices. Converter must multiply by 10,000 (not 100) |
| `lean-foundation-audit.md` | Critical conversion | "divide by 100" | Multiply Dhan float by 10,000 |
| `lean-poc-plan.md` | Converter output | `YYYYMMDD 00:00` | **VERIFIED CORRECT** — confirmed by `cccl.zip` sample |
| `lean-version-matrix.md` | Engine version | Conflates `v2.4.0.1` with commit `17932` | Pin to `v2.4.0.1` for PoC; note `17932` as a newer rolling commit |

### Incomplete Information

| File | Section | Gap | Impact |
|------|---------|-----|--------|
| `lean-foundation-audit.md` | Trading hours | Missing pre-market/post-market sessions | May affect fill-forward and scheduled events |
| `lean-foundation-audit.md` | Symbol properties | Marked "not found" — actually unresolvable | Must verify at runtime |
| `lean-poc-plan.md` | Timestamp convention | Assumes `00:00` without verification | Must verify against actual LEAN data files |

### Version Matrix Corrections

| File | Issue | Correction |
|------|-------|------------|
| `lean-version-matrix.md` | LEAN engine listed as `v2.4.0.1` with commit `17932` | `v2.4.0.1` is the formal release; `17932` is a rolling commit on master. These are different. Pin to `v2.4.0.1`. |

---

## 3. Blocking Analysis

### Items That Block the One-Equity Daily PoC

| Item | Blocks PoC? | Resolution |
|------|------------|------------|
| Price scaling error (×100 vs ×10,000) | **YES** | Must correct converter to multiply Dhan float by 10,000 |
| Timestamp convention | **RESOLVED** | `YYYYMMDD 00:00` confirmed by `cccl.zip` sample |
| Symbol properties for India equity | **POSSIBLE** | If LEAN requires symbol properties and none exist, `AddEquity` will fail. Must test at runtime. |
| Dhan API response format (float vs integer) | **YES** | Must verify with live API call or fixture |

### Items That Block Trustworthy Production Backtesting

| Item | Blocks Production? | Resolution |
|------|-------------------|------------|
| No map files for test equity | Yes (survivorship bias) | Build map files from Dhan data orNSE records |
| No factor files for test equity | Yes (price adjustment) | Build factor files from Dhan data or NSE records |
| Holiday list accuracy | Yes (backtest on holidays) | Verify NSE holiday list against NSE official calendar |
| Symbol properties completeness | Yes (order sizing) | Verify or create symbol properties for India equity |

### Items Requiring Runtime Experiment

| Item | How Resolved |
|------|-------------|
| Can LEAN initialize India equity without symbol properties? | Run `lean backtest` with minimal algorithm and observe |
| Does Python.NET work in Docker for India equity? | Run PoC |

---

## 4. Expected Files for One Test Equity

### Directory Path

```
Data/equity/india/daily/{TICKER}.zip
```

### ZIP Filename

```
{TICKER}.zip
```

### CSV Filename Inside ZIP

```
{TICKER}.csv
```

### CSV Content Format

```
YYYYMMDD HH:MM,open,high,low,close,volume
```

Where:
- `YYYYMMDD HH:MM` — datetime in `Asia/Kolkata` timezone; **daily bars use `00:00`** (confirmed by `cccl.zip` sample)
- `open,high,low,close` — prices in deci-cents (actual price × 10,000)
- `volume` — integer (number of shares)

### Map File (Optional for PoC)

```
Data/equity/india/map_files/{TICKER}.csv
```

Minimum content (if no mapping needed):
```
19990101,{TICKER}
20501231,{TICKER}
```

### Factor File (Optional for PoC)

```
Data/equity/india/factor_files/{TICKER}.csv
```

Minimum content (no adjustments):
```
20501231,1,1,0
```

### Market-Hours Configuration

Already defined in `Data/market-hours/market-hours-database.json` as `Equity-india-[*]`. No additional configuration needed.

### Symbol-Properties Configuration

**UNRESOLVED** — may need to be created if LEAN requires it. Format unknown without runtime testing.

### Algorithm Project Files

```
{PROJECT_DIR}/
├── main.py                    # Python algorithm
├── config.json                # LEAN configuration (generated by lean init)
└── data/                      # Symlink or copy to Data/ directory
```

### Configuration/Launcher Files

```
lean.json                     # Generated by `lean init`
```

---

## 5. Deterministic Test Specification

### Test Equity Selection

Pick any NSE equity with:
- At least 1 year of daily data available via Dhan
- Simple, well-known ticker
- No ticker changes in last 5 years
- Security ID confirmed via Dhan API

### Fixture Data

Create `tests/fixtures/dhan_daily_response.json` containing:
- 252 trading days of OHLCV data
- Realistic but synthetic values
- Valid OHLC relationships (low ≤ open/close ≤ high)
- Volume in realistic range

### Converter Output

The converter must produce `Data/equity/india/daily/{TICKER}.zip` containing `{TICKER}.csv` with:
- 252 rows of daily bars
- Timestamps in `YYYYMMDD HH:MM` format (verify time portion)
- Prices multiplied by 10,000 (deci-cents)
- Volume as integers

### Algorithm

```python
from AlgorithmImports import *

class TestAlgorithm(QCAlgorithm):
    def initialize(self):
        self.set_start_date(YYYY, MM, DD)  # Match fixture start
        self.set_end_date(YYYY, MM, DD)    # Match fixture end
        self.set_cash(100000)               # INR starting cash
        self.add_equity("TICKER", Market.India)
        self.bar_count = 0
        self.first_bar = None
        self.last_bar = None

    def on_data(self, data):
        self.bar_count += 1
        if self.first_bar is None:
            self.first_bar = data["TICKER"]
        self.last_bar = data["TICKER"]
```

### Success Criteria

| Criterion | Expected | How Verified |
|-----------|----------|-------------|
| Algorithm runs without errors | Exit code 0 | `lean backtest` output |
| Symbol subscribed successfully | No error on `add_equity` | Log output |
| Bar count matches fixture | 252 bars | `self.bar_count == 252` |
| First bar date matches fixture start | First trading day | `self.first_bar.time == expected_start` |
| Last bar date matches fixture end | Last trading day | `self.last_bar.time == expected_end` |
| One predictable order fills | Limit order at known price | Set limit order at fixture's close price on day 100; verify fill on day 100 |
| Ending cash/holdings calculable | Known value | Compute expected value from fixture data |
| Second run produces identical results | Identical statistics | Run twice; compare results JSON |

### Determinism Verification

Run the backtest twice with identical inputs:
1. Compare `results.json` statistics (must be identical)
2. Compare log output (must be identical)
3. Note: execution time may vary

---

## 6. Decision

### NOT READY

The existing documents contain **two critical errors** that would cause the PoC to fail:

1. **Price scaling is wrong**: The converter would produce values 100× too small (using ×100 instead of ×10,000)
2. **Timestamp convention is unverified**: Using `00:00` may cause bars to be placed outside market hours

Additionally, **symbol properties for India equity are unverified** — if LEAN requires them and they don't exist, `AddEquity` will fail.

### Required Before PoC

1. Correct the price scaling in all documents (×10,000, not ×100)
2. **RESOLVED**: `YYYYMMDD 00:00` confirmed
3. Test that `AddEquity("TICKER", Market.India)` works without explicit symbol properties
4. **RESOLVED**: Dhan API docs confirm `float` type for OHLCV
5. Pin LEAN engine to `v2.4.0.1` (not an arbitrary commit)

**Remaining runtime blockers**:
1. Symbol properties for India equity: UNRESOLVED — verification requires running `lean backtest` with a minimal algorithm
2. AddEquity without symbol properties: UNRESOLVED — needs runtime test

### Files Needing Amendment

| File | Sections |
|------|----------|
| `lean-foundation-audit.md` | Data Fields Comparison, Critical conversion, Gap analysis |
| `lean-version-matrix.md` | Engine version pinning, rolling commit clarification |
| `lean-poc-plan.md` | Converter output format, timestamp convention, success criteria |
| `dhan-to-lean-options.md` | Dhan data shape description |

---

## 7. Evidence Classification Summary

| Label | Count | Key Findings |
|-------|-------|-------------|
| VERIFIED | 16 | Market constant, timezone, trading hours, data format, CLI version, Docker requirements, timestamp convention, Dhan float response |
| CORRECT BUT INCOMPLETE | 3 | Trading hours (missing pre/post market), engine version (conflated), route suitability (scaling wrong) |
| INCORRECT | 2 | Price scaling (×100 vs ×10,000), Dhan response type (integer vs float) |
| UNRESOLVED | 2 | Symbol properties, AddEquity without properties |
| ASSUMPTION | 2 | Lot size, minimum price variation |
