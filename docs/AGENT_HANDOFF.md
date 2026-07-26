# Agent Handoff

## Zerodha Phase 2C.1 offline Unix-domain-socket checkpoint (2026-07-26)

- Added `dhan_lean/providers/zerodha/unix_transport.py`: a provider-local,
  one-request-per-connection `UnixHistoricalBrokerClient` and explicit
  `UnixHistoricalBrokerServer` lifecycle for the existing length-prefixed
  protocol. Both use only `AF_UNIX` when it is available.
- The client reuses the existing `CandleRequest` / `BrokerResponse` schema,
  4-byte big-endian JSON framing, strict base64 body representation, payload
  limits, and typed broker errors. It maps unavailable sockets, timeouts, and
  malformed peer data to the existing closed error model without exposing
  paths, frames, bodies, or OS messages. It has no retry loop.
- The server takes an injected `HistoricalBroker`; Phase 2C.1 tests inject
  only `DeterministicFakeBroker`. It has bounded worker threads, exact frame
  I/O, request/response correlation, safe malformed-client closure, safe
  injected-exception responses, and owned-only stale-socket cleanup. Stale
  cleanup is disabled by default; explicit opt-in requires an `ECONNREFUSED`
  probe and unchanged socket device/inode identity before unlinking. Active,
  ambiguous, replaced, or non-socket entries fail closed. Socket mode is
  configurable (production design default `0660`); no user/group,
  ownership, systemd, deployment, HTTP, credentials, or session work exists.
- The adapter needs no orchestration change: it can use the Unix client through
  `HistoricalBroker`, retaining adapter-owned retry, request-budget admission,
  immutable per-attempt artifacts, fingerprint stability, and exact provider
  byte preservation.
- The project test guard now permits only `AF_UNIX` calls through its original
  `connect`/`connect_ex` implementations; TCP remains guarded and loopback
  remains allowed. This Windows Python build has no `socket.AF_UNIX`; 14
  Unix-specific transport tests skip while the two guard tests pass. The
  isolated Linux worktree ran the transport suite **16/16** and full discovery
  **240/240**, with Unix and symlink tests unskipped. Existing focused suites
  remain adapter **8/8**, protocol **32/32**, retry **20/20**, storage **15/15**,
  and artifacts **14 passing, 1 Windows symlink skip**.
- No live Zerodha request, HTTP transport, credential/session-file access,
  `OfflineDownloader`, `StateLedger`, LEAN conversion, trading, deployment,
  systemd, nested LEAN change, commit, or push occurred. Identity revalidation
  reduces stale-socket TOCTOU risk but cannot claim to eliminate hostile
  filesystem races; production ownership and deployment controls remain absent.

## Zerodha Phase 2B.5 offline historical-adapter checkpoint (2026-07-26)

- Added `dhan_lean/providers/zerodha/adapter.py`, an immutable provider-local
  composition boundary for the full offline Zerodha historical flow.
- The adapter resolves the exact instrument snapshot record, builds the
  existing `ZerodhaPlanningInput` and deterministic `ZerodhaPlannedRequest`,
  executes through `run_planned_request`, observes each admitted response,
  publishes every eligible attempt through `publish_budgeted_result`, then
  parses and validates only the final successful response.
- Added typed `ZerodhaAdapterStatus`, immutable
  `ZerodhaHistoricalAdapterInput`, and safe immutable
  `ZerodhaHistoricalAdapterResult`. Results contain no raw response bytes,
  credentials, session data, exception objects, or absolute paths. Successful
  results require at least one validated normalized bar; empty responses,
  malformed responses, provider failures, budget exhaustion, retry-limit
  exhaustion, reauthentication, validation failure, and artifact failure are
  distinct outcomes.
- Planning and attempt request-ID factories are separate injected seams:
  planning remains deterministic while every admitted retry receives a fresh
  request ID. Artifact failure is terminal for the adapter and cannot cause a
  retry or an additional broker call.
- Phase 2B.5 focused tests: **8/8 passing**. Existing focused suites: planning
  **18/18**, retry **20/20**, storage **15/15**, and artifacts **14 passing with
  1 Windows symlink skip**. Full project-owned discovery is **224 passing, 1
  skipped**. `git diff --check`
  passed after documentation edits.
- The deterministic fake broker remains the only broker implementation used.
  No live Zerodha request, credentials/session access, socket, HTTP transport,
  downloader, ledger, server, deployment, trading, LEAN conversion, commit, or
  push occurred. `OfflineDownloader` and `StateLedger` integration remain
  unimplemented.

## Zerodha Phase 2B.4 raw-artifact and redaction checkpoint (2026-07-26)

- Added offline-only artifact orchestration in `dhan_lean/providers/zerodha/artifacts.py`.
- `execute_and_publish` runs the existing deterministic fake-broker/retry seam and observes each admitted attempt without adding raw bytes to `AttemptRecord` or `BudgetedBrokerResult`.
- Artifacts use `raw/zerodha/{venue}/historical/{symbol}/{provider_instrument_id}/minute/{YYYY}/{MM}/{DD}/{request_fingerprint}/attempt-{number}-{request_id}/` and are published through the reusable immutable `ArtifactWriter.write_immutable_bundle` boundary.
- Metadata is strict allowlist JSON, uses `provider_instrument_id`, rejects credential-like keys case-insensitively, and never serializes request IPC mappings, credentials, URLs, session paths, or raw exception text. Raw provider bytes are stored separately as `response-body.bin` byte-for-byte with length/hash verification.
- Successful 2xx bodies are passed unchanged to the existing Zerodha parser and normalized-bar validator. Empty candles preserve raw evidence, parse successfully, and receive the existing `EMPTY_BARS` validation outcome. Provider errors and malformed bodies preserve evidence without unsafe summaries.
- Manifest publication is exclusive and cleaned on failure. Replays verify every file and canonical manifest hash; identical attempts are reused, conflicting bytes/metadata fail closed, and incomplete sets are reviewable typed failures. Retry attempts remain separate; budget-only/local-failure attempts publish metadata only.
- Immutable bundles now write only to unique sibling staging directories, flush and hash-verify payloads, write the manifest last, then atomically rename under a scoped non-overwrite publication lock. A failed staging publication never creates or removes a final bundle directory.
- Filename and path-component validation rejects traversal, separators, controls, trailing dots/spaces, drive/UNC forms, and Windows reserved device names. Replay rejects unexpected entries, directories, symlinks, special files, missing files, and manifest/payload changes. Per-attempt raw response evidence is mandatory when an attempt claims a body.
- Focused Phase 2B.4 artifact tests: **13 passing, 1 symlink test skipped because this Windows environment cannot create symlinks**. Focused generic storage tests: **15/15 passing**. Full project-owned suite: **215 passing, 1 skipped**. `git diff --check` passed.
- Phase 2B.4 remains offline and fake-broker-only: no live Zerodha request, session-file access, credentials, Unix socket, HTTP transport, broker service, `OfflineDownloader`, `StateLedger`, server/deployment change, trading, or LEAN conversion/integration was added. No commit or push was made.

## Zerodha Phase 2B.3 request-budget and retry checkpoint (2026-07-26)

- Added offline-only provider orchestration in `dhan_lean/providers/zerodha/retry.py`.
- `RetryPolicy` is immutable and requires explicit non-empty budget scope/window; defaults are 3 attempts, 1-second base, 30-second cap, 250ms jitter maximum, and 60-second maximum `Retry-After`.
- Retry classification uses the Phase 2B.1 policy metadata and permits only `BROKER_UNAVAILABLE`, `BROKER_TIMEOUT`, `PROVIDER_429`, `PROVIDER_5XX`, `NETWORK_TIMEOUT`, and `DNS_TLS_CONNECTION_FAILURE`.
- The runner constructs a fresh canonical UUID and immutable `CandleRequest`, then atomically consumes exactly one durable budget unit immediately before every fake-broker call. Retries share the same configured scope/window and never refund.
- Backoff is pure and immediate: `max(min(cap, base * 2**(retry-1)) + deterministic jitter, bounded Retry-After)` for valid provider 429 metadata. No sleeping is implemented.
- `AttemptRecord` and `BudgetedBrokerResult` are immutable and contain only safe metadata; raw body bytes are retained only on the final `BrokerResponse`, never in summaries or errors.
- Focused Phase 2B.3 tests: **20/20 passing**. Full project-owned suite: **198/198 passing**. `git diff --check` passed.
- Phase 2B.3 is offline-only: the protocol/fake-broker seam has no Unix-socket client or broker service yet, and has no live Zerodha request, session-file access, credentials, HTTP, artifact, `OfflineDownloader`, server, deployment, trading, or LEAN integration. No commit or push was made.

## Provider-neutral cleanup checkpoint (2026-07-25)

- The retired provider runtime, credentials, and reference material were archived outside the repository before this source cleanup.
- Active code is offline and provider-neutral: source adapter -> normalized bars -> validation -> ledger/execution -> LEAN conversion.
- No active brokerage integration exists. Zerodha authentication remains separate and is not connected to this repository.
- This cleanup is intentionally uncommitted on `refactor/provider-neutral-data-pipeline` pending review.
- Current offline test baseline: 13 tests passing.

## Historical pre-retirement handoff record (non-active)

Everything below this heading is preserved as historical context only. It must not be used as active configuration, deployment guidance, or runtime evidence after the 2026-07-25 retirement.

- Updated date and time: 2026-07-24 11:30:00 +05:30
- Updated by: Offline Sequential Batch Coordinator milestone
- Local repository: `D:\Hikash Development\dhan-lean`
- Server repository: `/srv/dhan-lean`
- Server SSH: `hacker@100.121.84.8` (Tailscale)
- SSH key: `C:\Users\DELL\.ssh\swingserver_ed25519`
- Current branch: `feature/lean-foundation`

## Most recently completed task

Implemented and verified the offline sequential batch coordinator module (`dhan_lean/data/coordinator.py`).

### Offline Sequential Batch Coordinator Milestone

- **Proven Milestone**: The first offline sequential batch coordinator is implemented and verified. It processes an explicitly supplied bounded list safely, one item at a time.
- Explicit ordered work-item keys supplied by the caller
- Strictly sequential single-item execution
- Configurable `max_items` limit enforcement
- Injectable inter-request delay (`delay_seconds`, `sleep_fn`)
- Delay occurs **only** between actual downloader executions (no delay before first request, no delay after last item, no delay for blocked items)
- Duplicate and malformed keys rejected in preflight before execution
- Blocked items do not call the downloader
- Correct `stop_on_failure` behavior for `FAILED` and `INTERRUPTED` statuses
- Unexpected exceptions produce a safe early stop (`UNEXPECTED_EXCEPTION`)
- Immutable `BatchSummary` dataclass with ordered processed results and counts
- No automatic ledger discovery
- No retries or retry authorizations
- No concurrency, scheduling, credentials, or live API calls
- Coordinator tests: **13/13 passing**
- Full test suite: **146/146 passing**

### Current scope boundary

- **Still unimplemented**:
  - persistent request-budget guard across process restarts
  - automatic ledger discovery / scanning
  - stale-lease review
  - retry authorization
  - approved retries
  - reconciliation
  - scheduled background execution
- Planning, registration, single-item execution, private token-management service, and offline sequential batch coordination only.
- All live batch testing remains suspended until an offline-only persistent request-budget guard is implemented and reviewed.


## Controlled Two-Item Live Batch Pilot Execution (2026-07-24)

Executed an end-to-end controlled live batch pilot on `swingserver` testing the batch coordinator (`execute_batch`).

### Technical Verification Outcomes
- **Coordinator Pipeline**: Proven end-to-end (`execute_batch` → `execute_single_work_item` → `DhanIntradayDownloader` → `validate_dhan_response` → `ArtifactWriter` → `StateLedger`).
- **Final Run ID**: `20260724T061448Z`
- **Work Items**: `HDFCBANK:1333:1m:2026-07-21` and `TCS:11536:1m:2026-07-21` on `NSE_EQ`.
- **Candle Verification**: Exactly 375 candles per item (09:15:00 to 15:29:00 IST), 200 HTTP status, strictly increasing timestamps within date.
- **Inter-Request Delay**: Injected 2.23-second delay observed between requests.
- **Token Security**: `TOKEN_LEAK_FOUND=false` across all ledger records, artifacts, and output.
- **Git State**: Clean at `24b017374497fa89c6dcc62feaba5d35a24f85c0`.

### Execution-Control Audit Finding
- **Status**: Technical pipeline succeeded, but overall pilot failed execution-control requirements; pilot must NOT be described as compliant or fully successful.
- **Audited Runs**: 11 total pilot run directories created under `/srv/market-data/raw/batch-pilot/`.
- **Live Requests Executed**: 7 runs executed live requests for a total of 14 Dhan API POST requests across script invocations.
- **HTTP Statuses & Outcomes**: All 14 requests returned HTTP 200 and succeeded.
- **Retries & Authorizations**: Exactly zero retries and zero retry authorizations occurred.
- **Token Security**: No token leak was found (`TOKEN_LEAK_FOUND=false`).
- **Evidence State**: All evidence is preserved on `swingserver`.
- **Current Action**: All live batch testing is suspended.
- **Next Required Milestone**: An offline-tested persistent request-budget guard so approved allowances survive process restarts.




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

Commit and synchronize the private token-management service before deployment.

## Local Windows environment verification (2026-07-25)

- **Environment**: Newly restored Windows workstation; repository remains on
  `feature/lean-foundation` with no application-code changes.
- **Tools**: Git `2.55.0.windows.3`, Python `3.14.6`, pip `26.1.2`.
- **Virtual environment**: `.venv` created with the standard-library `venv`
  module and verified runnable.
- **Declared dependency**: `dhanhq==2.2.0` installed exactly; `pip check`
  reported no broken requirements.
- **Project-owned tests**: `python -m unittest discover -s tests -t . -v`
  ran **181/181 passing** (0 failures, 0 skipped, 0 errors) in the latest
  verified run; the earlier 172-test and 180-test results are historical.
- **Vendored/reference tests**: not included; discovery was explicitly scoped
  to the repository `tests/` directory.
- **Lint/format**: no repository lint or formatting command/configuration was
  found.
- The earlier documented **76-test**, **146-test**, and **160-test** results are stale historical checkpoints.

## Persistent request-budget guard (offline-only, 2026-07-25)

- Added `dhan_lean.data.request_budget.RequestBudget`, stored in the existing
  SQLite ledger database; no service or dependency was added.
- Budget identity is `(scope, window_id)`. A new `window_id` is the explicit
  reset boundary; allowance and consumed count are durable in `request_budgets`.
- Consumption uses a SQLite `BEGIN IMMEDIATE` transaction and guarded update,
  so concurrent processes cannot oversubscribe the allowance.
- Missing, malformed, conflicting, or inaccessible state fails closed with a
  clear `RequestBudgetStateError`; exhausted allowance raises
  `RequestBudgetExceeded` without mutation.
- Transport is the canonical budget-consumption boundary; executor and
  coordinator do not consume allowance. Live batch testing remains suspended;
  only offline tests were run.
- Focused budget tests: **11/11 passing**, including reopen persistence,
  restart-equivalent observation, exact boundary, rejection immutability,
  concurrency, and corrupt-state fail-closed behavior.

## Network-boundary budget enforcement (offline-only, 2026-07-25)

- **Call graph confirmed from source**: project-owned runtime modules are
  `DhanHttpTransport.post_intraday` → `_default_executor` → `urllib.request.urlopen`;
  `DhanIntradayDownloader` reaches that transport, and the executor/coordinator
  wrappers reach the downloader. No project CLI, pilot script, or service
  invokes these paths; repository callers outside runtime code are tests with
  injected executors or mocks.
- The default network executor now requires an explicit configured
  `RequestBudget`, `budget_scope`, and `budget_window_id`, and consumes one unit
  immediately before the outbound attempt. Missing or exhausted configuration
  fails before the executor is called.
- The default transport has no retry loop, so each outbound attempt consumes
  exactly one unit. Injected executors remain an intentional offline/test seam.
- SQLite uses explicit `BEGIN IMMEDIATE`/`COMMIT`/`ROLLBACK` with
  `isolation_level=None`, preserving compatibility with Python 3.10+.
- Focused network-boundary tests: **8/8 passing** (including mocked reachability,
  missing configuration, exhaustion, restart persistence, concurrency, and
  failed-attempt accounting). No further network calls were made after a
  fixture initially failed to intercept a transport executor; that accidental
  endpoint attempt returned HTTP 400 and is explicitly not live verification.
- Live batch activity remains suspended pending review and a separately
  authorised, tightly bounded pilot.

## Project test network guard (offline-only, 2026-07-25)

- Importing the project-owned `tests` package automatically installs a global
  standard-library guard for normal `unittest discover` runs.
- External `urllib.request.urlopen` and non-loopback socket connections are
  blocked with clear test failures. Local loopback test servers and injected
  transport executors remain permitted.
- Passing offline tests is not live verification; live batch activity remains
  suspended pending a separately authorised pilot.

## LEAN Minute Data Format Converter (offline-only, 2026-07-25)

- Implemented reusable offline converter `convert_dhan_minute_to_lean` in
  `dhan_lean/data/converter.py` for converting validated Dhan 1-minute intraday
  bar data into LEAN-native equity minute-data CSV-in-ZIP format.
- Format source-verified against pinned LEAN commit `1fee999e4f437d09e255be5c3fde783206e05389`
  (`LeanData.cs` & `TradeBar.cs`).
- Target layout: `Data/equity/india/minute/{symbol}/{YYYYMMDD}_trade.zip`
  containing `{YYYYMMDD}_{symbol}_minute_trade.csv`.
- Encodes timestamps as `TimeMs` (milliseconds since midnight in `Asia/Kolkata` IST)
  using integer-safe microsecond epoch arithmetic, supporting Unix seconds and milliseconds.
- Scales float/Decimal/str INR prices to LEAN deci-cents ($10,000\times$) using `Decimal`
  arithmetic with `ROUND_HALF_UP` rounding.
- Enforces safe `os.link` exclusive publication: fails closed if target exists (preventing race condition overwrites),
  writes to standard library temporary file in target directory, performs atomic hard link publication,
  cleans up temporary files on failure, and normalizes all OS/Decimal/datetime errors to `LeanConversionError`.
- Resolves timestamp-key ambiguity explicitly: compares `"timestamp"` and `"start_Time"` semantically across all indices if both present.
- Focused converter tests: **19/19 passing** (`tests/test_converter.py`).
- Documentation updated in `docs/lean-data-converter.md`. Format is verified
  against official LEAN engine source; loading converted ZIP artifacts into LEAN
  will be verified in a subsequent task.
