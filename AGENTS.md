# dhan-lean — Project Agent Rules

## Evidence-First, No-Assumption Approach

All technical conclusions drawn in this project must be labeled with one of the
following evidence classifications:

- **CONFIRMED BY OFFICIAL DOCUMENTATION** — sourced from `docs/dhan-docs-export.md`
  or the live Dhan API documentation at https://docs.dhanhq.co
- **CONFIRMED BY SOURCE CODE** — sourced from `references/DhanHQ-py/` (the official
  Python SDK source)
- **OBSERVED IN TEST** — reproduced in an actual running test against the Dhan API
- **UNRESOLVED** — conflicting or missing information; must be explicitly flagged
- **ASSUMPTION** — a reasonable inference not yet confirmed by any of the above

Never state an API field, endpoint, response value, rate limit, or platform
capability without attaching one of these labels.

---

## Source Precedence Rules

1. Official Dhan documentation (`docs/dhan-docs-export.md` / docs.dhanhq.co)
   takes precedence over any example code in skills or the SDK repository.
2. `references/DhanHQ-py/` source code takes precedence when verifying exact
   SDK method signatures, response structures, and runtime behavior.
3. The agent skill at `.agents/skills/dhanhq/` provides workflow patterns and
   usage examples; it does not override (1) or (2).
4. Do not mix JavaScript API v1 examples into the Python API v2 implementation.

---

## Credential and Security Rules

- **Never** place credentials, access tokens, PINs, TOTP secrets, or account
  identifiers in source files, logs, prompts, or Git history.
- No credential mechanism should be selected or implemented yet.
  - For VPS/local Python code: credentials may later be supplied through a
    secure secret-management method (e.g., environment variables from a secret
    store, Vault, or an encrypted file outside the repository). No specific
    mechanism is chosen at this stage.
  - For any future Dhan Cloud code: generic `os.getenv` or `.env` examples must
    **not** override Dhan Cloud's documented variable-substitution model once
    that model is confirmed from official documentation.

---

## Execution Isolation Rules

- Do not place any live-order code into this project until explicitly approved.
- Historical-data and research code must remain isolated from live execution code.
- Do not build a custom backtesting engine. LEAN (QuantConnect) will be used for
  all backtesting on the VPS.

---

## Data Source Rules

- Dhan is the authoritative historical-data source for this project.
- Do not use any previous project database or previous Dhan client configuration.
- Do not re-use data pipelines, schemas, or configuration from prior workspaces.

---

## Implementation Boundaries

- Do not install Python packages without explicit instruction.
- Do not install LEAN without explicit instruction.
- Do not connect to the Dhan API without explicit instruction.
- Do not design or implement a trading strategy without explicit instruction.
- Do not create database schemas without explicit instruction.

---

## Dhan API Version

This project targets **Dhan API v2** (Python SDK `dhanhq`). Do not reference
v1 endpoints, v1 field names, or v1 SDK methods unless specifically comparing
versions.

---

## LEAN Source Precedence Rules

1. LEAN engine source code (`github.com/QuantConnect/Lean`) takes precedence
   over LEAN documentation for exact data format, market support, and
   engine behaviour.
2. LEAN CLI source code (`github.com/QuantConnect/lean-cli`) takes precedence
   for command-line behaviour and Docker integration.
3. LEAN documentation (`www.lean.io/docs`) is authoritative for concepts,
   tutorials, and API reference.
4. Do not assume LEAN supports a feature for Indian markets without
   confirming it in the engine source code or documentation.
5. Do not assume a data format works without testing it in the PoC.

---

## LEAN Version Pinning Rule

All LEAN components must be pinned to specific versions before installation:

- **LEAN engine**: Pin to a specific commit tag (e.g., `17932`) or Docker
  image tag. Never use `latest`.
- **LEAN CLI**: Pin to a specific PyPI version (e.g., `1.0.227`).
- **Docker images**: Use specific tags, never `latest` in production.
- **Python**: `>=3.10` (system-level, managed by Docker).

Record all version pins in `docs/lean-version-matrix.md` before any
installation.

---

## LEAN Execution Rules

- Do not build a custom backtesting engine. LEAN (QuantConnect) is the
  backtesting engine for this project.
- Do not modify LEAN engine source code. Use LEAN as-is.
- Do not write LEAN algorithms until the PoC confirms data format compatibility.
- Do not install LEAN or Docker without explicit instruction.
- Do not run LEAN backtests without confirming the data format first.

---

## LEAN Data Rules

- LEAN's native equity data format is the primary integration route (Route A).
- Dhan historical data must be converted to LEAN's CSV-in-ZIP format before
  backtesting.
- Dhan historical data API returns OHLCV as `float` type (CONFIRMED BY
  OFFICIAL DOCUMENTATION, `docs/dhan-docs-export.md` lines 768-773).
  LEAN equity data uses `_scaleFactor = 1/10000m` (CONFIRMED BY SOURCE CODE,
  `TradeBar.cs`). The converter must multiply Dhan float prices by 10,000 to
  produce LEAN's deci-cent format.
- Do not assume LEAN's India equity dataset is complete. Supply own data.
- Do not assume mapping or factor files exist for a given ticker without
  verifying.

---

## DhanHQ SDK Version Targeting Rule

Production implementation must target the stable DhanHQ SDK version selected by
the project. Source or examples from main/pre-release must not be used unless
the required feature is unavailable in stable and I explicitly approve the upgrade.

- The currently selected stable version is **`dhanhq==2.2.0`** (Git tag `v2.2.0`,
  commit `06c830c`, path `references/DhanHQ-py-v2.2.0/`).
- The pre-release reference (`references/DhanHQ-py/`, branch `main`,
  `v2.3.0rc1`) is retained for inspection only and must not be used as a
  source for implementation code or examples.
- Before adopting any feature, constant, method, or behaviour observed only in
  `references/DhanHQ-py/`, the version matrix at
  `docs/dhan-sdk-version-matrix.md` must be consulted and the item must be
  classified as `compatible` or explicitly approved for upgrade.
