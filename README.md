# dhan-lean

A controlled Python environment for systematic trading research using
[Dhan](https://dhan.co) as the authoritative historical-data source and
[LEAN](https://lean.io) (QuantConnect) as the backtesting engine, deployed to a
dedicated VPS runtime.

---

## Project Purpose

| Component | Role |
|-----------|------|
| **Dhan** | Authoritative source for Indian equity historical data via the `dhanhq` Python SDK |
| **LEAN** | Backtesting engine — QuantConnect's open-source framework running on VPS |
| **VPS** | Controlled, isolated runtime for all live and backtesting execution |

Dhan-to-LEAN compatibility has **not yet been proven**. The current phase is
environment preparation and reference hardening.

---

## Verified LEAN Build & Setup Sequence

To set up and compile the LEAN engine reproducibly on a local environment or server:

```powershell
# 1. Bootstrap LEAN repository checkout & apply custom patches
.\scripts\bootstrap-lean.ps1

# 2. Prepare local runtime configuration from example template
Copy-Item lean_config.example.json lean_config.json

# 3. Build local LEAN Docker image
docker build -t dhan-lean:pinned .
```

---

## Current Phase: Environment Preparation

- [x] Dhan agent skill installed
- [x] Official Dhan API v2 documentation export added
- [x] Stable DhanHQ-py v2.2.0 reference checkout committed
- [x] Pre-release DhanHQ-py main reference checkout committed
- [x] SDK version matrix completed
- [x] Git baseline established & reproducible LEAN bootstrap created
- [ ] LEAN installation verification (local minimal backtest PoC)
- [ ] Dhan → LEAN data bridge (not yet designed)
- [ ] Live credentials (not committed — never will be)
- [ ] Trading strategy (not yet designed)

---

## SDK Target

| Attribute | Value |
|-----------|-------|
| Package | `dhanhq` |
| Stable version | `2.2.0` |
| Python requirement | `>=3.10` |
| Pre-release reference | `2.3.0rc1` (read-only, do not use in production) |

All implementation code must target `dhanhq==2.2.0` unless an upgrade is
explicitly approved. See [`docs/dhan-sdk-version-matrix.md`](docs/dhan-sdk-version-matrix.md)
for the full version comparison and difference classifications.

---

## Repository Layout

```
dhan-lean/
│
├── AGENTS.md                          # Agent rules — evidence, precedence, security
├── README.md                          # This file
├── Dockerfile                         # Canonical LEAN Dockerfile
├── lean_config.example.json           # Template configuration file for LEAN engine
│
├── scripts/
│   └── bootstrap-lean.ps1            # Reproducible LEAN checkout, patch, and build script
│
├── patches/
│   └── lean/
│       ├── README.md                  # Explanation of LEAN patches
│       └── Market.cs                  # Custom Market.India definition patch
│
├── .agents/
│   └── skills/dhanhq/                 # Installed Dhan agent skill
│
├── docs/                              # Project documentation & runbooks
│
└── references/                        # SDK reference snapshots
```

---

## Security and Credential Policy

- **No credentials, tokens, access keys, PINs, or TOTP secrets are committed.**
- No `.env` files are committed. `.env` and `.env.*` are in `.gitignore`.
- No live-order code exists in this repository.
- See [`AGENTS.md`](AGENTS.md) for the full credential and security rules.

---

## Key Reference Documents

| Document | Purpose |
|----------|---------|
| [`AGENTS.md`](AGENTS.md) | Agent operating rules, evidence classification, security policy, SDK targeting rule |
| [`docs/PROJECT_BLUEPRINT.md`](docs/PROJECT_BLUEPRINT.md) | Durable repository blueprint and current architecture |
| [`docs/AGENT_HANDOFF.md`](docs/AGENT_HANDOFF.md) | Operational handoff and current project state |
| [`docs/dhan-sdk-version-matrix.md`](docs/dhan-sdk-version-matrix.md) | Comparison of stable v2.2.0 vs pre-release v2.3.0rc1 |
