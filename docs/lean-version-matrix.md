# LEAN Version Matrix

> Created: 2026-07-21
> Purpose: Exact version identifiers, release dates, compatibility, and
> unresolved items for all LEAN components used or considered in this project.

---

## 1. LEAN Engine (Pinned)

| Attribute | Value |
|-----------|-------|
| **Repository** | https://github.com/QuantConnect/Lean |
| **Pinned Commit Hash** | `1fee999e4f437d09e255be5c3fde783206e05389` (CONFIRMED BY AGENTS.md RULE) |
| **License** | Apache-2.0 |
| **Build Method** | Direct open-source engine built locally / local Docker image (No LEAN CLI, No QC pre-built hub images) |
| **Primary language** | C# / .NET |
| **Python integration** | Python.NET (`QuantConnect.pythonnet`) |

---

## 2. Docker & Container Specification

| Attribute | Value |
|-----------|-------|
| **Docker Engine Target** | Docker Engine pinned version (To be installed on host) |
| **Image Source** | Locally built Docker image from commit `1fee999e4f437d09e255be5c3fde783206e05389` |
| **Tagging Rule** | Specific tag with OCI provenance labels (Never `latest`) |

---

## 3. Host System Baseline

| Component | Pinned Version / Requirement |
|-----------|----------------------------|
| **Host OS** | Ubuntu 26.04 LTS (x86_64) |
| **Host Kernel** | `7.0.0-22-generic` |
| **Host Python** | `Python 3.14.0` |
| **DhanHQ SDK** | `dhanhq==2.2.0` (CONFIRMED BY AGENTS.md RULE) |
