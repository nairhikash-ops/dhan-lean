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

## Current Phase: Environment Preparation

- [x] Dhan agent skill installed
- [x] Official Dhan API v2 documentation export added
- [x] Stable DhanHQ-py v2.2.0 reference checkout committed
- [x] Pre-release DhanHQ-py main reference checkout committed
- [x] SDK version matrix completed
- [x] Git baseline established
- [ ] LEAN installation (not yet begun)
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
│
├── .agents/
│   └── skills/dhanhq/                 # Installed Dhan agent skill
│       ├── SKILL.md                   # Skill definition
│       ├── examples/                  # Usage examples (equity, F&O orders)
│       ├── references/                # Skill reference docs (orders, market data, etc.)
│       └── scripts/                   # Helper scripts (dhan_helpers, trade_logger, etc.)
│
├── docs/
│   ├── dhan-docs-export.md            # Official Dhan API v2 documentation export
│   ├── dhan-sdk-version-matrix.md     # v2.2.0 vs v2.3.0rc1 comparison with classifications
│   └── source-provenance.md           # Authoritative record of all reference sources
│
└── references/
    ├── DhanHQ-py/                     # Pre-release snapshot — main branch, v2.3.0rc1
    │   └── (source files only — .git excluded)
    └── DhanHQ-py-v2.2.0/             # Stable snapshot — Git tag v2.2.0
        └── (source files only — .git excluded)
```

---

## Security and Credential Policy

- **No credentials, tokens, access keys, PINs, or TOTP secrets are committed.**
- No `.env` files are committed. `.env` and `.env.*` are in `.gitignore`.
- No live-order code exists in this repository.
- See [`AGENTS.md`](AGENTS.md) for the full credential and security rules.

---

## LEAN Status

LEAN has **not yet been installed**. No LEAN configuration, data, or backtest
results exist in this repository. LEAN work will begin on the
`feature/lean-foundation` branch after this baseline is verified.

---

## Key Reference Documents

| Document | Purpose |
|----------|---------|
| [`AGENTS.md`](AGENTS.md) | Agent operating rules, evidence classification, security policy, SDK targeting rule |
| [`docs/dhan-sdk-version-matrix.md`](docs/dhan-sdk-version-matrix.md) | Full comparison of stable v2.2.0 vs pre-release v2.3.0rc1; all differences classified |
| [`docs/dhan-docs-export.md`](docs/dhan-docs-export.md) | Official Dhan API v2 documentation export (authoritative for API behaviour) |
| [`docs/source-provenance.md`](docs/source-provenance.md) | Source provenance record for all reference materials |

---

## API Version

This project targets **Dhan API v2**. v1 endpoints, field names, and SDK
methods are not used.
