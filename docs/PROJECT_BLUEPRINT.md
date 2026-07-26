# Dhan Lean — Project Blueprint

> Historical project name retained temporarily. Active architecture is provider-neutral and offline-only.

## Current offline Zerodha protocol checkpoint (2026-07-26)

Phase 2C.2 adds an offline standalone broker-service application shell around
the completed Unix server. It is explicitly launched with a required fake-only
mode and accepts only safe socket/lifecycle settings; it constructs no HTTP,
credential, session, or provider implementation. The service emits sanitized
structured lifecycle events after a successful bind/listen, handles SIGINT and
SIGTERM by setting a shutdown event, uses deterministic exit statuses, and
delegates owned-socket cleanup and stale-socket policy to the Unix server.
Stale cleanup remains disabled by default. Client/server retries remain absent;
adapter orchestration remains the budget and retry owner. This is development
and test-only: production ownership/provisioning, user/group setup, systemd,
credentials/session loading, Zerodha HTTP, `OfflineDownloader`, `StateLedger`,
LEAN conversion, live data, and trading remain unimplemented. No live Zerodha
request occurred. Windows focused service tests have 6 passes and 7 AF_UNIX
skips, while full discovery has 254 passes and 23 skips; isolated Linux service
and full discovery runs are 13/13 and 254/254 with no skips.
Service shutdown uses a single monotonic deadline rather than a per-worker
timeout. It closes owned accepted sockets before joining and reports incomplete
worker drain as a runtime failure; Python does not forcibly kill an injected
broker blocked inside a call, so real upstream calls must be cooperative and
bounded for graceful shutdown. Readiness publication is mandatory and aborts
startup on failure, while ordinary operational logging remains best effort.

Phase 2C.1 adds an offline Unix-domain-socket historical broker transport:
`ZerodhaHistoricalAdapter` can use `UnixHistoricalBrokerClient` over one local
AF_UNIX connection per attempt to a bounded local `UnixHistoricalBrokerServer`
that receives an injected deterministic fake broker. The existing 4-byte
big-endian length-prefixed JSON protocol and base64 body representation are
reused unchanged, so raw provider bytes remain exact and immutable artifacts
remain unchanged. The client has no hidden retries or budgets; retries remain
adapter-side and the server dispatches once per accepted request. Socket paths
are validated; stale cleanup is explicit opt-in and only removes an unchanged
socket after a refused-connect probe, while active or ambiguous endpoints fail
closed. Cleanup similarly verifies server-owned device/inode identity.
Configurable POSIX mode defaults conceptually to `0660`. This reduces but does
not claim to eliminate hostile filesystem races; production ownership and
deployment controls are not implemented. Credentials, session files, Zerodha HTTP,
Kite Connect, systemd/deployment, user/group provisioning, `OfflineDownloader`,
`StateLedger`, LEAN conversion, and trading remain unimplemented. No live
Zerodha request occurred. The project test network guard permits only AF_UNIX
through its normal guarded operations; TCP remains restricted. On this Windows
Python build `AF_UNIX` is unavailable, so 14 Unix-specific transport tests skip.
An isolated Linux worktree ran all 16 transport tests and full discovery (240/240)
without skips.

Phase 2B.5 now composes the complete offline Zerodha historical adapter flow:
`DataWorkItem` resolution, deterministic planning, durable fake-broker budget
and retry execution, per-attempt observation, mandatory immutable artifact
publication, historical response parsing, and generic normalized-bar
validation. A successful provider workflow returns only a non-empty tuple of
validated `NormalizedBar` values. The deterministic fake broker remains the
only broker implementation used; no live Zerodha request occurred. Unix-socket
transport, the protected broker service, real Zerodha HTTP requests,
`OfflineDownloader`, `StateLedger`, and LEAN conversion remain unimplemented.
The focused Phase 2B.5 adapter suite has 8 passing tests; the full project-owned
suite has 224 passing tests and one Windows-limited symlink skip.

Phase 2B.3 adds provider-specific, offline request orchestration under
`dhan_lean/providers/zerodha/`. A planned request is admitted through the
existing durable SQLite `RequestBudget`, assigned a fresh request UUID per
attempt, sent to a `HistoricalBroker` seam, and classified using the existing
error-policy metadata. Approved retries use pure deterministic backoff and do
not sleep. Every attempt shares one explicit `(scope, window_id)` budget
identity. Attempt histories and final results are immutable and redact raw
provider bytes from summaries. No network, authentication, session access,
live data, downloader integration, or trading is active. Offline raw artifact
writing and redaction integration is active through
`dhan_lean/providers/zerodha/artifacts.py`; it only uses the deterministic fake
broker and stores immutable, hash-manifested raw evidence. Publication uses
isolated staging directories and atomic non-overwriting final-directory
publication; incomplete staging state is never treated as a final artifact. No
Unix-socket client or broker service exists yet; the request-budget and retry
orchestration currently operate only through the protocol and fake-broker seam,
with no live Zerodha request. Unix-socket transport, broker service,
`OfflineDownloader`, `StateLedger`, and LEAN conversion remain unimplemented
for this provider phase.

## Retirement and active scope (2026-07-25)

The previous provider runtime was retired and archived. The active repository accepts normalized bars from future offline adapters, validates them, tracks work through a SQLite ledger, and converts bars into LEAN minute ZIP data. No brokerage API, credential management, network ingestion, or live trading is part of the active implementation. Zerodha authentication exists separately and is not wired into this execution path.

The current project-owned offline suite contains 215 passing tests and one platform-limited symlink skip. The archival tag `dhan-capable-2026-07-25` retains the retired implementation and historical evidence.

## Historical pre-retirement record (non-active)

Everything below this heading records the project state before the 2026-07-25 retirement. It is retained only as historical context; it does not describe current dependencies, supported commands, or runtime behavior.

- Last verified date and time: 2026-07-21 22:43:00 +05:30
- Repository path: D:\Hikash Development\dhan-lean
- Current branch: feature/lean-foundation
- Verification status: Partially verified from repository files and Git state; runtime integration remains unverified.

## 1. Project purpose

This repository is a controlled environment for trading-research work that uses Dhan as the authoritative source for Indian-market historical data and LEAN (QuantConnect) as the backtesting engine. The project is currently in an environment-preparation and reference-hardening phase rather than a production trading implementation.

The repository contains both project-specific documentation and a vendored copy of the LEAN engine source under the Lean directory. It also contains reference snapshots for the Dhan Python SDK in the references directory.

## 2. Current implementation status

### Working

- Repository-level agent instructions and project guidance are present.
- The Dhan SDK reference material has been collected and versioned.
- The repository includes a LEAN source tree and a sample LEAN configuration file.
- The repo contains documentation for LEAN runtime, Docker, deployment, and server operations.

### Partially working

- The LEAN environment setup is documented but not yet fully installed or verified in this repo.
- Dhan-to-LEAN compatibility has not yet been proven.
- Docker/runtime setup remains blocked by the infrastructure issues documented in the runtime blocker report.

### Planned or not implemented

- Live trading or order execution code.
- A full Dhan-to-LEAN data bridge.
- A production trading strategy.
- A completed LEAN backtest pipeline for Indian equities.

### Known broken or unverified areas

- Runtime execution of LEAN against Dhan data is not yet verified.
- Docker runtime health is currently impacted by the storage issue described in docs/docker-runtime-blocker.md.
- Any live credentials or secrets are intentionally excluded from the repository and must not be added.

## 3. Technology stack

### Languages

- Python
- C#
- Markdown
- JSON

### Frameworks and platforms

- LEAN (QuantConnect open-source backtesting engine)
- Dhan API v2 via the Python SDK package dhanhq
- Docker for runtime packaging and deployment guidance

### Runtime versions when discoverable

- Project target Python requirement for Dhan SDK work: >=3.10
- LEAN source tree is present and documented for .NET-based execution; the specific local runtime version is not yet verified in this repository snapshot.

### Package managers

- Python packaging is referenced through the Dhan SDK references and Python environment work.
- Docker is used for runtime and deployment guidance.

### Databases

- No application database is configured in this repository snapshot.

### External services

- Dhan API v2
- QuantConnect / LEAN engine
- Docker runtime and optional VPS deployment

### Development environment

- Windows workspace with a repository under D:\Hikash Development\dhan-lean
- Git-based development workflow

### Deployment environment

- A dedicated VPS runtime is referenced in the repository documentation, with the host name swingserver and SSH access details recorded.

## 4. Repository structure

```text
AGENTS.md                  # Canonical agent instructions for this repository
README.md                  # Project overview and current phase
Dockerfile                 # LEAN container definition
Dockerfile_pin             # Additional pinned runtime container definition
lean_config.json           # LEAN configuration template
Market.cs                  # LEAN-related market identifier definitions
docs/                      # Project documentation, runbooks, implementation notes
Lean/                      # QuantConnect LEAN source tree
references/                # Dhan SDK reference snapshots, including stable and pre-release copies
.test-runtime/             # Temporary runtime experimentation directory (not part of core app)
```

### Directory responsibilities

- docs/: project plans, runbooks, API export, version matrices, and handoff documentation.
- Lean/: the open-source LEAN engine source tree used as the backtesting foundation.
- references/: authoritative reference snapshots for the Dhan SDK, including stable v2.2.0 and pre-release material.
- .agents/: repository-specific agent rules and skills.

## 5. Main entry points

| File or command | Purpose | How it is invoked | Verification status |
|---|---|---|---|
| AGENTS.md | Canonical instructions for coding agents | Read directly by agents before work | Verified in repository |
| README.md | High-level project overview and status | Read as repository documentation | Verified in repository |
| lean_config.json | LEAN configuration template | Used as a config input for LEAN-based runs | Present; not yet exercised |
| Dockerfile / Dockerfile_pin | Container definitions for the runtime | Used by Docker build workflows | Present; build not yet verified in this task |
| Lean/QuantConnect.Lean.sln | Visual Studio solution for the LEAN source tree | Opened in Visual Studio or built with dotnet | Present; build not yet run here |
| docs/implementation_plan.md | Planned implementation steps | Read as reference documentation | Verified in repository |
| docs/docker-runtime-blocker.md | Records current Docker runtime issue | Read as diagnostic documentation | Verified in repository |

## 6. System architecture

The repository is organized around a layered architecture:

1. Dhan provides market-data access through the Python SDK.
2. The project documentation and reference snapshots define the supported SDK version and expected data contract.
3. LEAN provides the backtesting engine and expects data in a format compatible with its engine.
4. Docker and VPS deployment files provide the environment where the runtime can be exercised.
5. The existing SQLite ledger also stores persistent request-budget state for
   explicitly configured execution windows.
6. The default Dhan HTTP network executor requires that persistent budget and
   consumes one unit immediately before each outbound attempt.

Text flow:

Dhan API -> Permanent Raw 1m Archive (/srv/market-data) -> Validation & Resumable State -> Derived Intervals / LEAN Converter -> Temporary LEAN Export (/srv/market-data/lean) -> LEAN Engine -> Backtest/Reporting Output

## 7. Core workflows

### Application startup

Not yet implemented as a dedicated application entry point. The repository is centered on environment preparation and reference validation rather than shipping a runnable app.

### Data ingestion

Dhan 1-minute historical data is downloaded via Python SDK (`dhanhq==2.2.0`) in chunked requests, validated (OHLC relationships, timestamp ordering, non-zero volume), and stored in a permanent raw unadjusted 1-minute archive rooted at `/srv/market-data/raw`. Download state tracking ensures interruption-safe, resumable ingestion and duplicate prevention. Higher intervals (5m, 15m, 30m, 60m, daily) are aggregated on demand from the 1m raw archive.

### Market-data handling

The raw 1-minute data is converted on demand into temporary LEAN-native CSV-in-ZIP format (`/srv/market-data/lean/Data/equity/india/minute/` and `daily/`) with deci-cent price scaling ($10,000\times$) for backtesting execution.

### Strategy execution

No trading strategy implementation exists in this repository snapshot.

### Backtesting

LEAN is present as a source tree and configuration template, but no verified backtest run has been completed in this task.

### Broker or Dhan integration

Dhan integration is documented and referenced, but runtime calls have not been executed as part of the current task.

### Database access

No database-backed application is present in this repository snapshot. Filesystem-based raw archives and state files on `/srv/market-data` manage data persistence.

### Reporting

The LEAN engine includes reporting and result-generation capabilities, but no project-specific reporting workflow has been implemented here.

## 8. Data model

### Databases

- No application database is configured.

### Files used as persistent storage

- `{STORAGE_ROOT}/raw/` (default `/srv/market-data/raw/`) for permanent unadjusted 1-minute raw market data archives downloaded via `intraday_minute_data`. Path is configurable; `/srv/market-data` is the current server-local default, not a hardcoded requirement.
- `{STORAGE_ROOT}/state/` (default `/srv/market-data/state/`) for resumable download tracking and gap reports.
- `{STORAGE_ROOT}/lean/` (default `/srv/market-data/lean/`) for temporary, disposable LEAN-native exported CSV-in-ZIP datasets generated on demand.
- lean_config.json for LEAN configuration.
- docs files for project state and implementation notes.

### Migration systems

- None identified in this repository snapshot.

## 9. Configuration

| Configuration file or environment-variable name | Purpose | Required or optional | Safe default, when verified | Where it is used |
|---|---|---|---|---|
| lean_config.json | LEAN runtime configuration template | Optional for local experimentation | The file exists and contains default backtesting settings | LEAN-based runs |
| .env or .env.* | Secret-bearing runtime environment files | Optional but should be kept out of version control | Not committed; not verified | Future runtime or API integration |
| Dockerfile / Dockerfile_pin | Container build definitions | Optional for deployment | Not yet verified in this environment | Docker-based runtime |

## 10. External integrations

| Integration | Purpose | Relevant files | Authentication method without secret values | Current implementation status |
|---|---|---|---|---|
| Dhan API v2 | Historical data and market-related access | docs/dhan-docs-export.md, references/DhanHQ-py-v2.2.0, references/DhanHQ-py | Credentials are not stored in the repository; authentication method remains unverified in this task | Documented and referenced, not yet exercised |
| LEAN engine | Backtesting and strategy execution | Lean/, lean_config.json, Dockerfile | No credentials required in the repository snapshot | Source tree present, runtime integration not yet proven |
| Docker runtime | Container execution environment | Dockerfile, Dockerfile_pin, docs/deployment-runbook.md, docs/docker-runtime-blocker.md | Local host credentials only; not stored here | Partially verified; current runtime blocked by storage issues |

## 11. Important architectural decisions

| Decision | Reason | Relevant files | Date discovered or recorded | Status |
|---|---|---|---|---|
| Use Dhan API v2 as the authoritative data source | Project documentation and SDK references state this explicitly | README.md, AGENTS.md, docs/dhan-docs-export.md | 2026-07-17 / 2026-07-21 | Confirmed by repository documentation |
| Target stable DhanHQ SDK 2.2.0 unless explicitly upgraded | Existing repository instructions require stable targeting | AGENTS.md, docs/dhan-sdk-version-matrix.md | 2026-07-17 | Confirmed by repository documentation |
| Use LEAN as the backtesting engine | Project purpose and documentation define LEAN as the engine | README.md, AGENTS.md | 2026-07-17 / 2026-07-21 | Confirmed by repository documentation |
| Store raw 1m data permanently before converting for LEAN | Enables multi-interval derived candles and decouples raw archive from LEAN export | docs/dhan-to-lean-options.md, docs/PROJECT_BLUEPRINT.md | 2026-07-23 | Confirmed by repository documentation |
| Do not commit secrets or credentials | Security guidance is explicit in the repository | AGENTS.md, .gitignore | 2026-07-21 | Confirmed by repository files |

## 12. Development commands

The following commands were verified from repository evidence and local Git state only; they were not all executed as part of this documentation task.

| Command | Purpose | Status |
|---|---|---|
| git status | Inspect working tree state | Verified in this task |
| git branch | Inspect current branch | Verified in this task |
| git diff | Inspect uncommitted changes | Verified in this task |
| git diff --check | Check for whitespace issues | To be run as part of final verification |
| dotnet build QuantConnect.Lean.sln | Build the LEAN solution | Not yet verified in this task |
| docker build / docker run | Runtime container tasks | Not yet verified; current blocker exists |
| python -m pip install dhanhq==2.2.0 | Install the pinned Dhan SDK | Not yet verified in this task |

## 13. Testing and validation

### Existing test framework

- The LEAN source tree contains its own test suite under the Lean/Tests directory.
- The repository’s current documentation also references validation and runtime checks.

### Test locations

- Lean/Tests/
- docs/environment_verification_report.md
- docs/docker-runtime-blocker.md

### Current known test status

- Repository documentation and Git inspection were verified during this task.
- On 2026-07-25, Python 3.14.6 ran the project-owned `tests/` suite with
  181 passing tests and no failures, skips, or errors, including 19 focused
  LEAN minute-data converter tests.
- LEAN runtime execution remains unverified because of the Docker runtime issue.

### Validation gaps

- No end-to-end Dhan-to-LEAN backtest has been run yet.
- No automated validation of vendored SDK/reference tests was performed.
- Request-budget persistence and concurrency are offline-verified only; no
  live Dhan API calls were made.
- The default network executor is offline-verified to fail closed without
  explicit budget configuration; injected transport executors are test seams.
- SQLite transaction control uses `isolation_level=None` and explicit
  `BEGIN IMMEDIATE`/`COMMIT`/`ROLLBACK`, compatible with Python 3.10+.
- LEAN minute-bar format conversion is source-verified against pinned LEAN
  commit `1fee999e4f437d09e255be5c3fde783206e05389` and tested offline with 19
  unit tests including `os.link` exclusive publication, integer-safe epoch normalization,
  semantic timestamp-key comparison, and safe Decimal parsing; loading converted ZIP
  artifacts into LEAN engine will be tested in a subsequent task.




## 14. Known issues and technical debt

| Description | Impact | Relevant files | Current status | Suggested direction |
|---|---|---|---|---|
| Docker runtime storage corruption affected the runtime gate | Prevents container pulls and LEAN runtime execution | docs/docker-runtime-blocker.md | Verified in documentation | Investigate and repair the Docker storage backend before runtime work |
| LEAN runtime integration is not yet proven | Limits confidence in end-to-end backtesting | docs/implementation_plan.md, docs/dhan-to-lean-options.md | Not yet verified | Continue with environment prep and bridge design |
| The project is still in a preparatory phase | Prevents full strategy execution | README.md, docs/implementation_plan.md | Confirmed by docs | Keep changes scoped to documentation, environment, and reference validation |

## 15. Current priorities

The repository evidence points to the following current priorities:

- Preserve and extend the shared agent-instruction system.
- Keep the Dhan SDK target pinned to stable v2.2.0.
- Continue environment preparation for LEAN and Docker.
- Investigate and resolve the Docker runtime blocker before deeper runtime work.

## 16. Blueprint maintenance rules

This blueprint must be updated when durable project facts change, such as architecture, execution flow, supported commands, deployment approach, or major dependencies. Minor task history or formatting-only changes should not be recorded here.
