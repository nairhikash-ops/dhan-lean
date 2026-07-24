# Agent Handoff

- Updated date and time: 2026-07-24 00:33:30 +05:30
- Updated by: Offline SQLite StateLedger initial-claim checkpoint
- Local repository: `D:\Hikash Development\dhan-lean`
- Server repository: `/srv/dhan-lean`
- Server SSH: `hacker@100.121.84.8` (Tailscale)
- SSH key: `C:\Users\DELL\.ssh\swingserver_ed25519`
- Current branch: `feature/lean-foundation`

## Most recently completed task

Implemented and verified atomic initial claiming for registered `PLANNED` work items in `StateLedger`.

### Completed offline StateLedger initial-claim checkpoint

- Atomic initial claims are implemented.
- Claims require `claim_owner` and explicit positive lease duration.
- Attempt 1 stores attempt ID, run ID, owner, claim time and lease expiry.
- Attempt insertion and `PLANNED` → `CLAIMED` transition are atomic.
- Conditional update failure rolls everything back.
- Ledger tests: **15/15 passing**.
- Full suite: **91/91 passing**.

### Current scope boundary

- **Still unimplemented**:
  - success/failure completion
  - stale-lease review
  - retry authorization
  - download execution
  - reconciliation
- Planning, registration, and initial claim only.
- No live request authorized.
- Broad downloads and repeated live calls still require separate human approval.



## Previously completed controlled live pilot

Executed a controlled live Dhan API pilot (single POST request) to verify the
corrected one-minute download boundary behaviour for HDFCBANK on NSE_EQ.

### Controlled live pilot — HDFCBANK 2026-07-22

| Field | Value |
|---|---|
| Instrument symbol | HDFCBANK |
| Security ID | 1333 |
| Exchange segment | NSE_EQ |
| Instrument type | EQUITY |
| Session date | 2026-07-22 |
| Candle interval | 1 minute |
| `fromDate` sent | 2026-07-22 09:14:00 |
| `toDate` sent | 2026-07-22 15:30:00 |
| Boundary rationale | Dhan treats both `fromDate` and `toDate` as exclusive for this endpoint |
| Run ID | 20260723T165649Z |

**Verified live result:**

| Field | Value |
|---|---|
| HTTP status | 200 |
| Downloader success | `True` |
| Candle count | 375 |
| First candle timestamp | 2026-07-22 09:15:00 IST |
| Last candle timestamp | 2026-07-22 15:29:00 IST |
| Validation result | valid |
| Validation errors | none |
| Dhan token in artifacts | absent from all 6 generated artifacts |
| SHA-256 manifest | verified |
| Raw request/response bytes | retained |

**Safety properties of the pilot run:**
- Exactly one live POST request was made; no retry occurred.
- No `/profile` or authentication-probe request was made.
- Temporary pilot scripts were removed from `/tmp` and the local `scripts/` directory after the run.
- The swingserver Git working tree remained clean throughout.

**Artifact directory on swingserver:**
```
/srv/market-data/raw/dhan/nse_eq/equity/HDFCBANK/1333/1m/2026/07/22
```

### Relation to existing fixtures

The same date already contained two earlier external fixtures:
- An original 374-bar response beginning at 09:16 IST (incorrect boundary).
- A corrected 375-bar boundary response beginning at 09:15 IST.

The controlled live pilot independently confirmed the corrected 375-bar
`fromDate` = `09:14:00` / `toDate` = `15:30:00` boundary behaviour.

### Implementation modules (committed at 4707d0c)

- **`dhan_lean/data/transport.py`** (`DhanHttpTransport`): Standard-library HTTP
  transport built on `urllib.request`. Executes exactly 1 request per call with
  0 auto-retries. Enforces HTTPS scheme, non-empty hostname, credential rejection
  in URLs, and non-empty token validation. Redacts tokens in `repr()`, `str()`,
  and `TransportError` messages. Serializes response headers deterministically
  (sorted by key/value, CRLF line endings). Captures HTTP errors (400, 401, 500,
  etc.) into `HttpResponse` objects without unhandled exceptions.

- **`dhan_lean/data/downloader.py`** (`DhanIntradayDownloader`,
  `build_intraday_payload`): Enforces strict NSE cash equity payload structure
  (`securityId`, `exchangeSegment="NSE_EQ"`, `instrument="EQUITY"`,
  `interval="1"`, `oi`, `fromDate`, `toDate`) without `sort_keys`. Enforces
  single-day IST range and derives session date automatically. Writes exact
  untouched request and response bytes, headers, HTTP status, validation result,
  and SHA-256 manifest to 6 immutable artifacts. Safe Dhan error extraction
  (`_extract_safe_dhan_error`) parses scalar `errorCode`/`errorMessage` fields
  without exposing the token or request headers.

## Repository state before this task

- Branch: `feature/lean-foundation`
- Commit `4707d0c` ("feat: add Dhan intraday downloader") committed, pushed,
  and synchronized to `/srv/dhan-lean`.
- 45 unit tests verified passing on swingserver (45/45).

## Current repository state

- Branch: `feature/lean-foundation`
- Pre-planner synchronized baseline: `e3bc06945507ee8d914c976dc36fe347c1685c3d`
  (`test: expand artifact storage coverage`)
- The offline planner checkpoint adds `DownloadWorkItem`,
  `plan_one_minute_downloads`, and pure lexical raw-artifact path construction.
- **76 total unit tests passing locally**:
  - storage: 10
  - planner: 29
  - complete suite: 76
- This checkpoint changes no downloader, transport, validator, or request-execution behavior.

## LEAN and Docker state

- LEAN engine pinned at commit `1fee999e4f437d09e255be5c3fde783206e05389`
- Canonical clean image: `dhan-lean:poc` (contains global metadata only; no
  bundled sample datasets)
- Legacy image retained: `dhan-lean:sample-backup`
- **Docker images must not be pruned.**

## Data architecture

```
Dhan API
  → permanent raw unadjusted one-minute archive
  → validation and resumable state
  → higher intervals derived on demand
  → temporary LEAN exports
  → backtests / results
```

**Rules:**
- Raw one-minute data is **permanent**.
- LEAN exports are **disposable**.
- Real market data **must not be committed to Git**.

## Approved vs. unapproved actions

The following actions require **separate human approval** and must not be
performed as part of a documentation checkpoint or engineering task:

- Broad live API downloads or broad historical backfills.
- Repeated live API calls or retry sweeps.
- Any live Dhan API call beyond the single controlled pilot described above.

## Recommended next task

Implement attempt completion transitions only.
