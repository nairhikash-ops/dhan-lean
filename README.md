# dhan-lean

This repository currently provides an offline market-data pipeline for LEAN backtests.

```text
source adapter -> normalized bars -> validation -> planning / ledger / execution -> LEAN ZIP data
```

Providers must normalize payloads into immutable `NormalizedBar` values before calling generic pipeline code. The project has no active brokerage, credential, network, or live-execution integration. A separate Zerodha authentication service exists outside this repository and is not connected to LEAN execution.

The converter writes India equity minute data in LEAN's CSV-in-ZIP format through `convert_minute_bars_to_lean`. It uses `Decimal` price scaling, timezone-aware bars, deterministic ZIP member names, and collision-safe publication.

The repository name and Python package remain unchanged temporarily. Retired-provider history is preserved by Git tag `dhan-capable-2026-07-25`; the active checkout contains no provider runtime or credentials.

Run the offline tests with:

```text
.venv\Scripts\python.exe -B -m unittest discover -s tests -t . -q
```
