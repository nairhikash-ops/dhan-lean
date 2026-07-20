# DhanHQ SDK Version Matrix

> Generated: 2026-07-17
> Purpose: Pre-LEAN reference hardening. Establishes the authoritative stable SDK
> baseline and classifies every observed difference before implementation begins.

---

## 1. Reference Sources

| Source | Path | Description |
|--------|------|-------------|
| **stable-src** | `references/DhanHQ-py-v2.2.0/` | Git tag `v2.2.0`, commit `06c830c4f5a7593ede3deeabbf203debd8632826` |
| **pre-release-src** | `references/DhanHQ-py/` | Git branch `main`, commit `1670f818f4a695434192b66eecb03c764cb14622`, describe `v2.3.0rc1-2-g1670f81` |
| **skill** | `.agents/skills/dhanhq/` | Installed dhanhq skill (SKILL.md + references/) |
| **docs-export** | `docs/dhan-docs-export.md` | Official Dhan API v2 documentation export, generated 2026-07-16 |

---

## 2. Package Identity

| Attribute | stable v2.2.0 | pre-release v2.3.0rc1 |
|-----------|---------------|----------------------|
| PyPI package | `dhanhq` | `dhanhq` |
| VERSION string | `2.2.0` | `2.3.0rc1` |
| PEP 440 note | Final release; installed by `pip install dhanhq` | Pre-release; requires `pip install --pre dhanhq` or explicit pin |
| `python_requires` | **not declared** in `setup.py` (no `python_requires` field) | `>=3.10` |
| Development Status classifier | not present | `4 - Beta` |
| License | `MIT LICENSE` | `MIT LICENSE` |

### Classification

| Difference | Classification |
|------------|---------------|
| `python_requires` absent in v2.2.0 | **stable-only** — v2.2.0 does not declare a floor; v2.3.0rc1 formalises `>=3.10`. Minimum Python for v2.2.0 is **unresolved from metadata alone** (inferred `>=3.8` from skill docs; not confirmed from v2.2.0 setup.py). |
| Version string `2.3.0rc1` vs `2.2.0` | **pre-release-only** |

---

## 3. `historical_daily_data` Signature

### stable v2.2.0 (`_historical_data.py`)

```python
def historical_daily_data(
    self,
    security_id,
    exchange_segment,
    instrument_type,
    from_date,
    to_date,
    expiry_code=0,
    oi=False,
):
```

**Payload fields sent:** `securityId`, `exchangeSegment`, `instrument`, `expiryCode`, `oi`, `fromDate`, `toDate`

**Validation:** `expiry_code not in [0, 1, 2, 3]` → returns `status: failure` immediately (no HTTP call).

**Endpoint:** `POST /charts/historical`

### pre-release v2.3.0rc1

Identical — same file content, same signature, same validation, same payload.

### skill reference (`market-data.md`)

```python
dhan.historical_daily_data(
    security_id,
    exchange_segment,
    instrument_type,
    from_date,
    to_date,
    expiry_code=0,
    oi=False,
)
```

Matches both versions exactly.

Skill note: *"The raw API docs currently document `expiryCode` values `0`, `1`, `2`. The installed SDK validation still accepts `3`. Prefer the documented values unless Dhan updates the API docs."*

### docs-export (`Get Daily Historical Data`)

Endpoint `POST /charts/historical`. Fields documented: `securityId`, `exchangeSegment`, `instrument`, `expiryCode`, `oi`, `fromDate`, `toDate`.

Annexure **Expiry Code** table lists values `1`, `2`, `3` only (no `0`). Response fields: `open`, `high`, `low`, `close`, `volume`, `open_interest`, `timestamp`.

### Classification

| Difference | Classification |
|------------|---------------|
| SDK validates `[0, 1, 2, 3]`; docs Annexure lists only `1`, `2`, `3` (no `0`) | **documentation mismatch** — SDK accepts `0` ("no expiry / cash") which is not listed in the Annexure. Treat `0` as the default for equity/cash instruments unless Dhan resolves this. |
| Skill note flags the gap | **compatible** — skill guidance is consistent with source code |
| Response field `open_interest` documented; test fixture is `{}` (empty) | **unresolved** — actual API response shape for the `oi=True` branch cannot be confirmed without a live call |

---

## 4. `intraday_minute_data` Signature

### stable v2.2.0 (`_historical_data.py`)

```python
def intraday_minute_data(
    self,
    security_id,
    exchange_segment,
    instrument_type,
    from_date,
    to_date,
    interval=1,
    oi=False,
):
```

**Payload fields sent:** `securityId`, `exchangeSegment`, `instrument`, `interval`, `oi`, `fromDate`, `toDate`

**Validation:** **None on `interval`** — any integer value is passed through to the API without client-side rejection.

**Endpoint:** `POST /charts/intraday`

### pre-release v2.3.0rc1

Identical — same signature, same absence of interval validation, same payload.

### Unit test contradiction (`test_dhanhq_historical_data.py` in both versions)

`test_intraday_minute_data_fails_for_bad_interval_input` asserts that passing `interval=100` returns `status: failure` and that no HTTP call is made. **This test is incorrect** — the source implementation does not validate `interval` in `intraday_minute_data`. The test will fail if executed against the installed package from either tag. This is a bug in the test suite, not a version difference.

### skill reference (`market-data.md`)

Documents supported intervals as `1`, `5`, `15`, `25`, `60`. No mention of client-side validation. States: *"The v2 historical-data page documents last 5 years for active instruments. The installed SDK docstring still says 'last 5 trading day'. Prefer the current v2 API docs when planning data windows."*

### docs-export (`Get Intraday Historical Data`)

Endpoint `POST /charts/intraday`. Documented intervals: `1`, `5`, `15`, `30`, `60` (note: **`30`**, not `25`). Response fields: `open`, `high`, `low`, `close`, `volume`, `open_interest`, `timestamp`.

SDK docstring says "last 5 trading day". Docs say "last 5 years".

### Classification

| Difference | Classification |
|------------|---------------|
| `intraday_minute_data` has **no interval validation** in either SDK version | **compatible** — both versions behave identically; the missing validation is consistent |
| Unit test `test_intraday_minute_data_fails_for_bad_interval_input` does not match implementation | **documentation mismatch** — test is wrong; do not rely on client-side interval rejection from this method |
| Skill documents interval `25`; official docs document `30` | **documentation mismatch** — use `30` per official docs; `25` appears in SDK docstring but not in official API spec |
| SDK docstring "last 5 trading day" vs docs "last 5 years" | **documentation mismatch** — official docs (`CONFIRMED BY OFFICIAL DOCUMENTATION`) is authoritative; plan data windows for up to 5 years |

---

## 5. `fetch_security_list` Signature

### stable v2.2.0 (`_security.py`)

```python
@staticmethod
def fetch_security_list(mode='compact', filename='security_id_list.csv'):
```

Modes: `'compact'` (default) → `https://images.dhan.co/api-data/api-scrip-master.csv`
       `'detailed'` → `https://images.dhan.co/api-data/api-scrip-master-detailed.csv`

Returns `pd.DataFrame` or `None` on error. Saves CSV to `filename` in current directory.

### pre-release v2.3.0rc1

`fetch_security_list` — **identical** to v2.2.0.

Additional method in v2.3.0rc1 only:

```python
@staticmethod
def fetch_global_security_list(filename='global_security_id_list.csv'):
```

URL: `https://api-global-stocks.dhan.co/api-data/us-stock-scrip-master.csv`

### skill reference (`SKILL.md`)

Documents `dhanhq.fetch_security_list()` (static call form). No mention of `fetch_global_security_list`.

### docs-export

Indian instruments: compact and detailed CSV URLs match exactly.
Global stocks CSV: `https://api-global-stocks.dhan.co/api-data/us-stock-scrip-master.csv` documented under Global Stocks section. Column description provided.

### Classification

| Difference | Classification |
|------------|---------------|
| `fetch_security_list` — identical in both versions | **compatible** |
| `fetch_global_security_list` — v2.3.0rc1 only | **pre-release-only** — do not use until stable release |
| Skill does not document `fetch_global_security_list` | **compatible** — skill is aligned with v2.2.0 stable |

---

## 6. Historical-Data Response Structure

### SDK test fixtures (both versions)

`tests/data/historical_daily_data.json`:
```json
{"status": "success", "remarks": "", "data": {}}
```

`tests/data/intraday_minute_data.json`:
```json
{"status": "success", "remarks": "", "data": {}}
```

Both fixtures use an **empty `data` object** — they test the HTTP plumbing only, not the response payload shape.

### skill reference (`market-data.md`) — inferred from usage patterns

```python
candles = response["data"]
timestamps = [dhan.convert_to_date_time(ts) for ts in candles["timestamp"]]
```

Implies `response["data"]` is a dict with array fields: `timestamp`, `open`, `high`, `low`, `close`, `volume`, and optionally `open_interest`.

### docs-export (`Get Daily Historical Data`, `Get Intraday Historical Data`)

Response fields listed at the top level, not nested under `data`:

| Field | Type |
|-------|------|
| `open` | float |
| `high` | float |
| `low` | float |
| `close` | float |
| `volume` | int |
| `open_interest` | int (F&O only) |
| `timestamp` | int (epoch) |

The docs do not show the `{"status": ..., "data": {...}}` wrapper — they document only the payload fields.

### Expired options response (docs-export)

```json
{
  "data": {
    "ce": {
      "iv": [], "oi": [], "strike": [], "spot": [],
      "open": [354, 360.3], "high": [], "low": [], "close": [],
      "volume": [], "timestamp": [1756698300, 1756699200]
    },
    "pe": null
  }
}
```

This is the only concrete response example in the docs export with populated arrays, confirming the columnar array format under `data.ce` / `data.pe`.

### Classification

| Difference | Classification |
|------------|---------------|
| SDK wraps response in `{"status", "remarks", "data"}`; docs show only field names | **compatible** — the SDK wrapper is the actual runtime shape; docs describe the fields inside `data` |
| Test fixtures use `"data": {}` (empty) | **compatible** — fixtures test plumbing only |
| Skill access pattern `response["data"]["timestamp"]` consistent with SDK wrapper | **compatible** |
| `open_interest` field present only when `oi=True`; docs list it unconditionally | **documentation mismatch** — treat `open_interest` as conditional; guard with `.get()` |
| Actual populated array shape unconfirmed for daily/intraday (only confirmed for rolling options) | **unresolved** — cannot confirm exact field names inside `response["data"]` for daily/intraday without a live call |

---

## 7. New Modules in v2.3.0rc1 (not in v2.2.0)

| Module | File | Summary |
|--------|------|---------|
| `ConditionalOrder` | `_conditional_order.py` | Place/get/modify/cancel conditional (alert-triggered) orders via `/alerts/orders` |
| `GlobalStocks` | `_global_stocks.py` | US equity trading via `/globalstocks/*` endpoints |
| `GlobalStocksFeed` | `global_stocks_feed.py` | WebSocket feed for US equities |
| `INX = 'INX_EQ'` constant | `dhanhq.py` | Exchange segment for Global Stocks |
| `fetch_global_security_list` | `_security.py` | US instrument master CSV |

`dhanhq` class MRO in v2.3.0rc1 adds `ConditionalOrder` and `GlobalStocks` to the inheritance chain.

### Classification

| Feature | Classification |
|---------|---------------|
| All v2.3.0rc1-only modules | **pre-release-only** — do not use in production implementation |
| `ConditionalOrder` documented in docs-export | **compatible** — API exists in docs; SDK implementation is pre-release only |
| `GlobalStocks` / `GlobalStocksFeed` documented in docs-export | **compatible** — API exists in docs; SDK implementation is pre-release only |

---

## 8. Modules Identical Between v2.2.0 and v2.3.0rc1

The following modules have identical source content in both versions:

| Module | File |
|--------|------|
| `HistoricalData` | `_historical_data.py` |
| `Security` (shared methods) | `_security.py` (excluding `fetch_global_security_list`) |
| `Order` | `_order.py` |
| `ForeverOrder` | `_forever_order.py` |
| `SuperOrder` | `_super_order.py` |
| `Portfolio` | `_portfolio.py` |
| `Funds` | `_funds.py` |
| `Statement` | `_statement.py` |
| `TraderControl` | `_trader_control.py` |
| `MarketFeed` | `_market_feed.py` |
| `OptionChain` | `_option_chain.py` |
| `DhanContext` | `dhan_context.py` |
| `DhanHTTP` | `dhan_http.py` |
| `DhanLogin` / `auth` | `auth.py` |
| `marketfeed` | `marketfeed.py` |
| `orderupdate` | `orderupdate.py` |
| `fulldepth` | `fulldepth.py` |

---

## 9. Skill Examples vs Stable Source

### `place_equity_order.py` and `place_fno_order.py`

Both examples use:
```python
from dhanhq import dhanhq
from scripts.dhan_helpers import get_client
dhan, _ = get_client()
```

- `DhanContext` initialization pattern matches v2.2.0 exactly.
- All SDK constants (`dhanhq.NSE`, `dhanhq.BUY`, `dhanhq.LIMIT`, `dhanhq.CNC`, `dhanhq.INTRA`, `dhanhq.DAY`) match v2.2.0 `dhanhq.py`.
- `dhan.expiry_list(under_security_id=..., under_exchange_segment=...)` called in F&O example — this delegates to `OptionChain.expiry_list()` which is identical in both versions.

### skill `SKILL.md` compatibility note

```
Requires Python 3.8+ and the dhanhq package (pip install dhanhq).
```

This states `3.8+`. v2.2.0 does not declare `python_requires`; v2.3.0rc1 declares `>=3.10`. The `3.8+` claim in the skill is not verifiable against v2.2.0 metadata alone.

### Classification

| Difference | Classification |
|------------|---------------|
| Skill examples consistent with v2.2.0 SDK constants and method signatures | **compatible** |
| Skill states `Python 3.8+`; v2.3.0rc1 source requires `>=3.10` | **documentation mismatch** — for safety, target `>=3.10` as the effective floor when using `dhanhq` |
| Skill references `use current SDK branch when you need newer v2 capabilities` | **pre-release-only** guidance — do not follow until explicitly approved |

---

## 10. Upstream Pre-Release Reference Record

This section records the exact state of `references/DhanHQ-py/` as the upstream
pre-release reference. This directory must not be modified.

| Attribute | Value |
|-----------|-------|
| Remote | `https://github.com/dhan-oss/DhanHQ-py` |
| Branch | `main` |
| HEAD commit | `1670f818f4a695434192b66eecb03c764cb14622` |
| Commit date | 2026-07-07 12:01:14 +0530 |
| Commit message | `Merge pull request #137 from Mirochill/fix-133-utcfromtimestamp-deprecation` |
| `git describe` | `v2.3.0rc1-2-g1670f81` |
| VERSION in setup.py | `2.3.0rc1` |
| `python_requires` | `>=3.10` |

---

## 11. Stable Source Reference Record

| Attribute | Value |
|-----------|-------|
| Remote | `https://github.com/dhan-oss/DhanHQ-py` |
| Tag | `v2.2.0` |
| HEAD commit | `06c830c4f5a7593ede3deeabbf203debd8632826` |
| `git describe` | `v2.2.0` |
| VERSION in setup.py | `2.2.0` |
| `python_requires` | not declared |

---

## 12. Consolidated Difference Classification

| # | Area | v2.2.0 | v2.3.0rc1/main | Skill | Docs | Classification |
|---|------|---------|----------------|-------|------|----------------|
| 1 | `python_requires` | not declared | `>=3.10` | says `3.8+` | n/a | **documentation mismatch** |
| 2 | `historical_daily_data` signature | 7 params | identical | identical | identical | **compatible** |
| 3 | `historical_daily_data` `expiry_code` validation | `[0,1,2,3]` | identical | consistent | Annexure lists `[1,2,3]` only | **documentation mismatch** |
| 4 | `historical_daily_data` response fields | `{}` in fixture | identical | `data.timestamp`, etc. | `open/high/low/close/volume/oi/timestamp` | **unresolved** (live shape unconfirmed) |
| 5 | `intraday_minute_data` signature | 7 params | identical | identical | identical | **compatible** |
| 6 | `intraday_minute_data` interval validation | absent | absent | not mentioned | n/a | **compatible** |
| 7 | `intraday_minute_data` bad-interval test | test asserts failure | same broken test | n/a | n/a | **documentation mismatch** (test is wrong) |
| 8 | `intraday_minute_data` supported intervals | docstring: `1,5,15,25,60` | identical | `1,5,15,25,60` | API docs: `1,5,15,30,60` | **documentation mismatch** — use `30`, not `25` |
| 9 | `intraday_minute_data` data window | docstring: "last 5 trading day" | identical | says "5 years" | "last 5 years" | **documentation mismatch** — docs win |
| 10 | `fetch_security_list` signature | present, static | identical | consistent | consistent | **compatible** |
| 11 | `fetch_global_security_list` | absent | present | absent | present | **pre-release-only** |
| 12 | `ConditionalOrder` module | absent | present | absent | present | **pre-release-only** |
| 13 | `GlobalStocks` module | absent | present | absent | present | **pre-release-only** |
| 14 | `GlobalStocksFeed` | absent | present | absent | present | **pre-release-only** |
| 15 | `INX = 'INX_EQ'` constant | absent | present | absent | present | **pre-release-only** |
| 16 | `open_interest` conditionality | SDK: conditional on `oi=True` | identical | uses `.get()` implicitly | listed unconditionally | **documentation mismatch** — guard with `.get()` |
| 17 | Skill `3.8+` Python claim | n/a | n/a | states `3.8+` | n/a | **documentation mismatch** (see row 1) |

---

## 13. Implementation Guidance for This Project

Based on the above analysis:

1. **Target `dhanhq==2.2.0`** for all production implementation (final stable release, no pre-release flags required for install).
2. **Effective Python floor is `>=3.10`** — use this as the project minimum even though v2.2.0 does not formally declare it, since v2.3.0rc1 makes it explicit and the skill's `3.8+` claim is unconfirmed.
3. **Use `expiry_code=0`** for equity/cash instruments (`historical_daily_data`). Do not use `expiry_code=3` until the Annexure discrepancy is resolved.
4. **Use interval `30`** (not `25`) for 30-minute intraday candles, per official docs.
5. **Data window for `intraday_minute_data`** — plan for up to 5 years per official docs; the SDK docstring "last 5 trading day" is wrong.
6. **Guard `open_interest`** with `.get('open_interest')` — it is conditional on `oi=True` and not always present.
7. **Do not use any v2.3.0rc1-only features** (`ConditionalOrder`, `GlobalStocks`, `GlobalStocksFeed`, `fetch_global_security_list`, `INX`) until explicitly approved.
8. **Do not rely on client-side interval rejection** from `intraday_minute_data` — validate intervals in calling code if needed.
