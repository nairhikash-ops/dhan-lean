# Source Provenance

> Created: 2026-07-21
> Purpose: Authoritative record of every external reference source used in this
> project, with exact version identifiers and authority designations.

---

## 1. DhanHQ Python SDK — Stable Reference

| Attribute | Value |
|-----------|-------|
| **Directory** | `references/DhanHQ-py-v2.2.0/` |
| **Repository URL** | https://github.com/dhan-oss/DhanHQ-py |
| **Git tag** | `v2.2.0` |
| **Commit hash** | `06c830c4f5a7593ede3deeabbf203debd8632826` |
| **VERSION** | `2.2.0` |
| **Cloned** | 2026-07-21 |
| **Clone method** | `git clone --branch v2.2.0 --depth 1` |
| **`.git` in repo** | Excluded via `.gitignore` — source files only are committed |

This is the **production-targeting SDK version**. All implementation code must
use this version unless an upgrade is explicitly approved.

---

## 2. DhanHQ Python SDK — Pre-Release Reference

| Attribute | Value |
|-----------|-------|
| **Directory** | `references/DhanHQ-py/` |
| **Repository URL** | https://github.com/dhan-oss/DhanHQ-py |
| **Branch** | `main` |
| **Commit hash** | `1670f818f4a695434192b66eecb03c764cb14622` |
| **Commit date** | 2026-07-07 12:01:14 +0530 |
| **Commit message** | `Merge pull request #137 from Mirochill/fix-133-utcfromtimestamp-deprecation` |
| **`git describe`** | `v2.3.0rc1-2-g1670f81` |
| **VERSION** | `2.3.0rc1` |
| **`python_requires`** | `>=3.10` |
| **Cloned** | 2026-07-21 |
| **`.git` in repo** | Excluded via `.gitignore` — source files only are committed |

This directory is a **read-only inspection reference**. It must not be used as
a source for implementation code or examples without explicit approval.

---

## 3. Dhan API v2 Documentation Export

| Attribute | Value |
|-----------|-------|
| **File** | `docs/dhan-docs-export.md` |
| **Source URL** | https://docs.dhanhq.co |
| **Export generated** | 2026-07-16 |
| **Added to project** | 2026-07-21 |
| **Format** | Markdown export of official Dhan API v2 documentation |
| **Scope** | Full API v2: orders, historical data, live feed, portfolio, funds, option chain, global stocks, conditional orders |

---

## 4. DhanHQ Agent Skill

| Attribute | Value |
|-----------|-------|
| **Directory** | `.agents/skills/dhanhq/` |
| **Installed** | 2026-07-21 |
| **SKILL.md states Python** | `>=3.8` (see version matrix — this is a documentation mismatch; use `>=3.10`) |
| **Contents** | SKILL.md, examples (equity/F&O orders), reference docs (12 topics), scripts (4 helpers) |

The skill provides workflow patterns and usage examples. It does not override
the official documentation or SDK source code for API behaviour or signatures.

---

## 5. SDK Version Comparison

| Attribute | Value |
|-----------|-------|
| **File** | `docs/dhan-sdk-version-matrix.md` |
| **Generated** | 2026-07-17 |
| **Compares** | v2.2.0 stable vs v2.3.0rc1 pre-release vs skill examples vs docs export |

---

## 6. Authority Designations

| Domain | Authoritative Source | Basis |
|--------|---------------------|-------|
| **API behaviour** (endpoints, fields, response shapes, rate limits) | `docs/dhan-docs-export.md` / https://docs.dhanhq.co | Official Dhan documentation |
| **SDK method signatures** (exact params, defaults, validation logic) | `references/DhanHQ-py-v2.2.0/src/dhanhq/` | Stable source code — `CONFIRMED BY SOURCE CODE` |
| **SDK runtime behaviour** (what the code actually does) | `references/DhanHQ-py-v2.2.0/src/dhanhq/` | Stable source code — `CONFIRMED BY SOURCE CODE` |
| **Agent workflow patterns and usage examples** | `.agents/skills/dhanhq/` | Skill — subordinate to (1) and (2) |
| **Project rules and implementation constraints** | `AGENTS.md` | Project-defined rules |
| **Version difference classifications** | `docs/dhan-sdk-version-matrix.md` | This project's analysis |

### Precedence Order

1. Official Dhan documentation (`docs/dhan-docs-export.md` / docs.dhanhq.co)
2. Stable SDK source code (`references/DhanHQ-py-v2.2.0/`)
3. Agent skill (`.agents/skills/dhanhq/`)
4. Pre-release SDK (`references/DhanHQ-py/`) — inspection only

### Conflict Resolution

When any two sources contradict each other, classify the conflict per
`AGENTS.md` evidence labels and record it in `docs/dhan-sdk-version-matrix.md`
as **documentation mismatch** or **unresolved** before using either value.

---

## 7. Verification Record

| Check | Date | Result |
|-------|------|--------|
| Pre-release clone metadata recorded | 2026-07-21 | `1670f818`, `v2.3.0rc1-2-g1670f81` |
| Stable v2.2.0 tag checkout verified | 2026-07-21 | `06c830c4`, tag `v2.2.0` confirmed |
| All three focus signatures verified from source | 2026-07-21 | `historical_daily_data`, `intraday_minute_data`, `fetch_security_list` identical in both versions |
| Credential scan on project files | 2026-07-21 | No real credentials found; `.test.env.sample` contains only placeholder values |
| Large file check | 2026-07-21 | `docs/dhan-docs-export.md` is 385 KB (acceptable); no files >1 MB in project source |

---

## 8. LEAN Engine Repository

| Attribute | Value |
|-----------|-------|
| **Repository URL** | https://github.com/QuantConnect/Lean |
| **License** | Apache-2.0 |
| **Latest formal release** | `v2.4.0.1` (2024-08-08) — **recommended for PoC pinning** |
| **Latest commit tag** | `17932` (2026-07-17) — rolling commit on `master`, ahead of `v2.4.0.1` |
| **Versioning scheme** | Formal releases (v2.x.x.x) + rolling commit tags on `master` |
| **Primary language** | C# 94.2%, Python 5.6% |
| **Runtime** | .NET 10 SDK |
| **Python integration** | Python.NET (`QuantConnect.pythonnet 2.0.64`) |
| **Docker base image** | `quantconnect/lean:foundation` |
| **Docker entry point** | `dotnet QuantConnect.Lean.Launcher.dll` |

**Important**: `v2.4.0.1` and commit `17932` are different checkpoints.
`v2.4.0.1` is the latest tagged formal release. `17932` is a rolling commit
on `master` that is ahead of `v2.4.0.1`. For the PoC, pin to `v2.4.0.1`
(the formal release) unless a specific feature from a newer commit is needed.

This is the **backtesting engine**. LEAN is a C# application that runs
algorithms written in C# or Python (via Python.NET). Docker is required for
local execution via `lean-cli`.

---

## 9. LEAN CLI (lean-cli)

| Attribute | Value |
|-----------|-------|
| **Repository URL** | https://github.com/QuantConnect/lean-cli |
| **PyPI package** | `lean` |
| **Latest version** | `1.0.227` |
| **Upload date** | 2026-06-26 |
| **Python requirement** | `>=3.9` |
| **License** | Apache-2.0 |
| **Key dependency** | Docker (required for local backtesting) |

This is the **command-line interface** for running LEAN backtests locally.
It manages Docker containers, data downloads, and project scaffolding.

---

## 10. LEAN Documentation

| Attribute | Value |
|-----------|-------|
| **Website** | https://www.lean.io |
| **Docs URL** | https://www.lean.io/docs |
| **Algorithm Framework** | https://www.lean.io/docs/algorithm-fundamentals/algorithm-framework |
| **Supported Markets** | https://www.lean.io/docs/algorithm-fundamentals/market-hours/exchange-hours |
| **Data Format** | https://www.lean.io/docs/algorithm-fundamentals/data/supported-data-sources |
| **Custom Data** | https://www.lean.io/docs/algorithm-fundamentals/data/supported-data-sources/custom-data |
| **API Reference** | https://www.lean.io/api-reference |
| **Boot Camp** | https://www.lean.io/docs/bootcamp |

---

## 11. Authority Designations — Extended

| Domain | Authoritative Source | Basis |
|--------|---------------------|-------|
| **API behaviour** (endpoints, fields, response shapes, rate limits) | `docs/dhan-docs-export.md` / https://docs.dhanhq.co | Official Dhan documentation |
| **SDK method signatures** (exact params, defaults, validation logic) | `references/DhanHQ-py-v2.2.0/src/dhanhq/` | Stable source code — `CONFIRMED BY SOURCE CODE` |
| **SDK runtime behaviour** (what the code actually does) | `references/DhanHQ-py-v2.2.0/src/dhanhq/` | Stable source code — `CONFIRMED BY SOURCE CODE` |
| **Agent workflow patterns and usage examples** | `.agents/skills/dhanhq/` | Skill — subordinate to (1) and (2) |
| **LEAN engine behaviour** (market support, data format, indicators) | https://github.com/QuantConnect/Lean | LEAN source code — `CONFIRMED BY SOURCE CODE` |
| **LEAN CLI behaviour** (commands, Docker integration) | https://github.com/QuantConnect/lean-cli | LEAN CLI source code — `CONFIRMED BY SOURCE CODE` |
| **LEAN documentation** (concepts, tutorials, API reference) | https://www.lean.io/docs | Official QuantConnect documentation |
| **Project rules and implementation constraints** | `AGENTS.md` | Project-defined rules |
| **Version difference classifications** | `docs/dhan-sdk-version-matrix.md` | This project's analysis |
| **LEAN integration feasibility** | `docs/lean-foundation-audit.md` | This project's analysis |

### Precedence Order

1. Official Dhan documentation (`docs/dhan-docs-export.md` / docs.dhanhq.co)
2. Stable SDK source code (`references/DhanHQ-py-v2.2.0/`)
3. LEAN engine source code (`github.com/QuantConnect/Lean`)
4. LEAN CLI source code (`github.com/QuantConnect/lean-cli`)
5. Agent skill (`.agents/skills/dhanhq/`)
6. Pre-release SDK (`references/DhanHQ-py/`) — inspection only
7. LEAN documentation (`www.lean.io/docs`)

### Conflict Resolution

When any two sources contradict each other, classify the conflict per
`AGENTS.md` evidence labels and record it in `docs/dhan-sdk-version-matrix.md`
or `docs/lean-foundation-audit.md` as **documentation mismatch** or
**unresolved** before using either value.

---

## 12. Verification Record

The following items are classified **UNRESOLVED** pending a live API call or
further documentation:

- Actual populated response shape of `response["data"]` for `historical_daily_data`
  and `intraday_minute_data` (test fixtures use empty `{}`)
- Minimum Python version for `dhanhq==2.2.0` (not declared in its `setup.py`;
  effective floor treated as `>=3.10` based on v2.3.0rc1 declaration)
- Behaviour of `expiry_code=0` on live API (accepted by SDK, not listed in docs Annexure)
